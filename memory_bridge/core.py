"""Local-only external memory. Retrieved text is data, never instructions."""
import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path

MAX_BYTES = 1_000_000
CATEGORIES = {'project_fact', 'task_state', 'public_knowledge'}
FIELDS = {'id','owner','source','fact','revision','op','category','text','timestamp','expires','provenance'}
IDENT = re.compile(r'^[A-Za-z0-9_-]{1,64}$')
BLOCK = re.compile(r'(?i)(-----BEGIN .*PRIVATE KEY|\b(?:sk-[A-Za-z0-9]{12,}|gh[pousr]_[A-Za-z0-9]{12,})|\b(?:password|api[_ -]?key|access[_ -]?token|persona|system[_ -]?prompt)\s*[:=])')

class Invalid(ValueError): pass
class Denied(Invalid): pass

def identifier(value):
    if not isinstance(value,str) or not IDENT.fullmatch(value): raise Invalid('invalid identifier')
    return value

def canonical(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()
def strict_json(raw, max_bytes=MAX_BYTES):
    if not isinstance(raw,(bytes,str)) or len(raw.encode() if isinstance(raw,str) else raw)>max_bytes: raise Invalid('file limit')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise Invalid('duplicate JSON key')
            result[key]=value
        return result
    try: return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(Invalid('non-finite JSON')))
    except (ValueError,UnicodeError,RecursionError) as exc: raise Invalid('invalid JSON') from exc

def validate(event):
    if not isinstance(event,dict) or set(event)!=FIELDS: raise Invalid('event fields')
    for field in ('id','owner','source','fact'): identifier(event[field])
    if type(event['revision']) is not int or not 1<=event['revision']<=2**31: raise Invalid('revision')
    if event['op'] not in ('put','delete'): raise Invalid('operation')
    if not isinstance(event['category'],str) or event['category'] not in CATEGORIES: raise Denied('category not syncable')
    for field in ('timestamp','expires'):
        v=event[field]
        if (field=='expires' and v is None): continue
        if type(v) is not int or not 0<=v<=2**53: raise Invalid('timestamp')
    for field in ('text','provenance'):
        if not isinstance(event[field],str) or len(event[field])>8192: raise Invalid('text limit')
        try: event[field].encode('utf-8')
        except UnicodeError as exc: raise Invalid('invalid unicode') from exc
        if BLOCK.search(event[field]): raise Denied('potential secret or persona')
    if event['op']=='delete' and event['text']: raise Invalid('delete text must be empty')
    if len(canonical(event).encode())>20000: raise Invalid('event limit')
    return event

def safe_file(root,name):
    """Only flat files in a dedicated directory; reject all symlink ancestors."""
    root=Path(root).absolute()
    for part in (root,*root.parents):
        if part.is_symlink(): raise Denied('symlink directory')
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9_-]+\.(?:json|sqlite)',name): raise Denied('unsafe filename')
    path=root/name
    if path.is_symlink(): raise Denied('symlink file')
    return path

def read_file(root,name):
    path=safe_file(root,name)
    fd=os.open(path,os.O_RDONLY | getattr(os,'O_NOFOLLOW',0))
    with os.fdopen(fd,'rb') as stream: return strict_json(stream.read(MAX_BYTES+1))

class Policy:
    """Trusted LOCAL grants. Never loaded from an event or remote transport."""
    def __init__(self,owner,audience):
        self.owner=identifier(owner); self.audience=identifier(audience); self.grants={}
    def approve(self,event,*,audience,until,consent=False):
        validate(event)
        if event['owner']!=self.owner or audience!=self.audience or consent is not True: raise Denied('consent/scope')
        if type(until) is not int or until<=time.time(): raise Denied('grant expiry')
        self.grants[digest(event)]={'source':event['source'],'category':event['category'],'audience':audience,'until':until}
    def revoke(self,event): self.grants.pop(digest(event),None)
    def permits(self,event,now=None):
        now=time.time() if now is None else now
        grant=self.grants.get(digest(event))
        return bool(event['owner']==self.owner and grant and grant['until']>now and grant['source']==event['source'] and grant['category']==event['category'] and grant['audience']==self.audience and (event['expires'] is None or event['expires']>now))

class Store:
    def __init__(self,root,owner,policy):
        self.owner=identifier(owner)
        if policy.owner!=owner: raise Denied('policy owner')
        self.policy=policy
        path=safe_file(root,'memory.sqlite'); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(path,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
        if os.name != "nt": os.fchmod(fd,0o600)
        os.close(fd)
        self.db=sqlite3.connect(path)
        self.db.executescript('CREATE TABLE IF NOT EXISTS identity(owner TEXT PRIMARY KEY); CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, hash TEXT UNIQUE NOT NULL, body TEXT NOT NULL); CREATE TABLE IF NOT EXISTS merges(id TEXT PRIMARY KEY, survivor TEXT NOT NULL, hidden TEXT NOT NULL, active INTEGER NOT NULL);')
        existing=self.db.execute('SELECT owner FROM identity').fetchall()
        if existing and existing!=[(owner,)]: self.db.close(); raise Denied('database owner')
        self.db.execute('INSERT OR IGNORE INTO identity VALUES (?)',(owner,)); self.db.commit()
    def close(self): self.db.close()
    def ingest(self,events):
        if not isinstance(events,list) or len(events)>1000: raise Invalid('batch limit')
        checked=[]
        for event in events:
            validate(event)
            if not self.policy.permits(event): raise Denied('local approval required')
            checked.append((event['id'],digest(event),canonical(event)))
        with self.db:
            for eid,sha,body in checked:
                previous=self.db.execute('SELECT hash FROM events WHERE id=?',(eid,)).fetchone()
                if previous and previous[0]!=sha: raise Invalid('event id collision')
                self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?,?)',(eid,sha,body))
    def events(self): return [strict_json(row[0]) for row in self.db.execute('SELECT body FROM events ORDER BY id')]
    def query(self,query='',*,start=0,end=2**53,limit=50):
        if type(start) is not int or type(end) is not int or not 0<=start<=end<=2**53: raise Invalid('time bounds')
        if not isinstance(query,str) or len(query)>1000 or type(limit) is not int or not 1<=limit<=100: raise Invalid('query bounds')
        groups={}
        # Tombstones persist regardless of consent expiry/revocation.
        for event in self.events(): groups.setdefault(event['fact'],[]).append(event)
        hidden={r[0] for r in self.db.execute('SELECT hidden FROM merges WHERE active=1')}
        result=[]; tokens=query.casefold().split()
        for fact,events in groups.items():
            if fact in hidden or any(e['op']=='delete' for e in events): continue
            revision=max(e['revision'] for e in events); newest=[e for e in events if e['revision']==revision]
            variants={(e['text'],e['category']) for e in newest}
            if len(variants)>1: continue
            event=sorted(newest,key=lambda e:e['id'])[0]
            if not self.policy.permits(event) or not start<=event['timestamp']<=end: continue
            score=sum(event['text'].casefold().count(t) for t in tokens)
            if tokens and not score: continue
            result.append({'event':event,'score':score,'trust':'untrusted_data'})
        return sorted(result,key=lambda r:(-r['score'],-r['event']['timestamp'],r['event']['id']))[:limit]
    def conflicts(self):
        groups={}
        for e in self.events():
            if self.policy.permits(e): groups.setdefault((e['fact'],e['revision']),[]).append(e)
        return [v for v in groups.values() if len({(e['op'],e['text'],e['category']) for e in v})>1]
    def merge(self,merge_id,survivor,hidden):
        for value in (merge_id,survivor,hidden): identifier(value)
        if survivor==hidden: raise Invalid('self merge')
        visible={r['event']['fact'] for r in self.query(limit=100)}
        if not {survivor,hidden}<=visible: raise Invalid('merge requires visible facts')
        with self.db: self.db.execute('INSERT INTO merges VALUES (?,?,?,1)',(merge_id,survivor,hidden))
    def undo_merge(self,merge_id):
        identifier(merge_id)
        with self.db: self.db.execute('UPDATE merges SET active=0 WHERE id=?',(merge_id,))
    def backup(self,root,name):
        path=safe_file(root,name)
        if path.exists(): raise Invalid('backup already exists')
        if path.suffix!='.sqlite': raise Invalid('sqlite backup required')
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,'O_NOFOLLOW',0),0o600)
        os.close(fd)
        out=sqlite3.connect(path)
        try: self.db.backup(out)
        finally: out.close()
    def restore(self,root,name):
        """Import validated same-owner backup events; never roll back tombstones."""
        path=safe_file(root,name)
        if not path.is_file() or path.stat().st_size>10_000_000: raise Invalid('backup limit')
        incoming=sqlite3.connect(f'file:{path}?mode=ro',uri=True)
        try:
            incoming.execute('PRAGMA trusted_schema=OFF')
            if incoming.execute('SELECT owner FROM identity').fetchall()!=[(self.owner,)]: raise Denied('backup owner')
            rows=incoming.execute('SELECT body FROM events LIMIT 10001').fetchall()
            if len(rows)>1000: raise Invalid('restore event limit')
            self.ingest([strict_json(r[0]) for r in rows])
        finally: incoming.close()
