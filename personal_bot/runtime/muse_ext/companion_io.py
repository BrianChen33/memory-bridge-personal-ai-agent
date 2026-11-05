"""Bounded local retrieval, native snapshots, private offline management view."""
import hashlib
from contextlib import closing
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from pathlib import Path
from muse_ext.companion import dump, stamp, _get, _set, context, mood, VERSION, TZ


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def atomic(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(data,encoding='utf-8'); os.chmod(tmp,0o600); tmp.replace(path)


def metric(b,kind,ms):
    # Sample only computations; cache hits do not turn every read into a write.
    with b.db:
        b.db.execute('INSERT INTO ct_metric(kind,ms,at) VALUES(?,?,?)',(kind,ms,stamp()))
        b.db.execute('DELETE FROM ct_metric WHERE id < (SELECT max(id)-200 FROM ct_metric)')


def revision(b,scope):
    r=b.db.execute('SELECT revision FROM ct_revision WHERE scope=?',(scope,)).fetchone()
    return r[0] if r else 0


def cached_recall(b,q,old):
    if not b.available('memory'): return old(b,q)
    scope=q.get('scope')
    # Date expressions must be resolved against NOW; transcripts never cached.
    temporal='start' in q or 'end' in q
    if b.feature('time_query'):
        from muse_ext.temporal import resolve_query
        temporal=temporal or bool(resolve_query(q.get('text','')))
    key=dump({k:q[k] for k in ('text','start','end','actor','entities','limit') if k in q})
    key=hashlib.sha256((key+dump(b.config())).encode()).hexdigest()
    rev=revision(b,scope); now=stamp()
    if not temporal:
        hit=b.db.execute('SELECT * FROM ct_cache WHERE scope=? AND query=? AND revision=? AND expires>?',
                         (scope,key,rev,now)).fetchone()
        if hit:
            data=json.loads(hit['value']); data['cache']='hit'; return data
    start=time.perf_counter(); result=old(b,q)
    # Cache bounded RESULT, not all memories or unscoped chat state.
    if not temporal and result.get('ok') and not result.get('disabled'):
        with b.db:
            b.db.execute('INSERT OR REPLACE INTO ct_cache VALUES(?,?,?,?,?)',(scope,key,rev,dump(result),now+45))
            b.db.execute('DELETE FROM ct_cache WHERE expires<?',(now,))
            b.db.execute('DELETE FROM ct_cache WHERE rowid NOT IN (SELECT rowid FROM ct_cache ORDER BY expires DESC LIMIT 128)')
    metric(b,'recall_compute',(time.perf_counter()-start)*1000)
    result['cache']='bypass_time' if temporal else 'miss'
    return result


def origin(row):
    source=row['source']
    if source.startswith('companion:dream'): return 'dream'
    if source.startswith('companion:virtual'): return 'virtual'
    return 'inference' if row['evidence']=='inference' else 'real'


def source_rows(b,scope,ids):
    if not isinstance(ids,list) or not ids or len(ids)>48 or any(type(i) is not int for i in ids):
        raise ValueError('invalid_summary_sources')
    marks=','.join('?' for _ in ids)
    return b.db.execute(f"SELECT * FROM memories WHERE scope=? AND status='active' AND id IN ({marks})",
                        [scope]+ids).fetchall()


def valid_summary(b,row):
    refs=json.loads(row['sources']); ids=[r['id'] for r in refs]
    try: rows=source_rows(b,row['scope'],ids)
    except ValueError: return False
    return len(rows)==len(refs) and {r['id']:r['fingerprint'] for r in rows}=={r['id']:r['hash'] for r in refs}


def summaries(b,q):
    if not b.available('memory'): return dict(scene_context=[],persona_context=[])
    if 'start' in q or 'end' in q: return dict(scene_context=[],persona_context=[])
    text=q.get('text','')
    from brain import tokens
    terms=set(tokens(text)[:32]); scene=[]; stable=[]; budget=1200
    rows=b.db.execute('SELECT * FROM ct_summary WHERE scope=? ORDER BY level DESC,updated DESC LIMIT 32',
                      (q['scope'],)).fetchall()
    for row in rows:
        if not valid_summary(b,row): continue
        if row['level']==2 and terms and not terms.intersection(tokens(row['content'])): continue
        if row['level']==2 and not terms: continue
        if budget<=0: break
        item=dict(level=row['level'],key=row['key'],origin=row['origin'],
                  content=row['content'][:min(450,budget)],source_ids=[r['id'] for r in json.loads(row['sources'])],
                  evidence='model_summary_not_original',updated=row['updated'])
        target=stable if row['level']==3 else scene
        if len(target)<3: target.append(item); budget-=len(item['content'])
    return dict(scene_context=scene,persona_context=stable)


def summary_work(b,q):
    scope=q.get('target_scope','owner-private')
    # Explicit one-scope batch; no implicit joining across private/group scopes.
    rows=b.db.execute("SELECT m.* FROM memories m LEFT JOIN ct_summarized s ON s.scope=m.scope AND s.memory=m.id "
                      "WHERE m.scope=? AND m.status='active' AND (s.memory IS NULL OR s.fingerprint!=m.fingerprint) "
                      "ORDER BY m.occurred_at,m.id LIMIT 48",(scope,)).fetchall()
    groups={}
    for r in rows: groups.setdefault(origin(r),[]).append(r)
    batches=[]
    for typ,items in groups.items():
        fingerprints=hashlib.sha256(dump([(r['id'],r['fingerprint']) for r in items]).encode()).hexdigest()
        key='summary_cursor:'+scope+':'+typ
        payload=[]; budget=12000
        for r in items:
            if budget<=0: break
            value=dict(r); value['text']=value['text'][:min(700,budget)]; budget-=len(value['text'])
            payload.append({k:value[k] for k in ('id','text','kind','evidence','occurred_at','source')})
        batches.append(dict(scope=scope,origin=typ,revision=fingerprints,memories=payload,
                            allowed_levels=[2,3] if typ=='real' else [2]))
        with b.db:
            _set(b,'summary_batch:'+scope+':'+typ,dict(revision=fingerprints,refs=[dict(id=r['id'],hash=r['fingerprint']) for r in items if r['id'] in {v['id'] for v in payload}]))
    return dict(ok=True,batches=batches,policy='background_only; preserve disagreements and provenance; do not infer permanent facts from one mood')


def summary_commit(b,q):
    scope=q.get('target_scope','owner-private'); typ=q.get('origin'); level=q.get('level')
    if typ not in ('real','virtual','dream','inference') or level not in (2,3): raise ValueError('invalid_summary')
    if level==3 and typ!='real': raise ValueError('stable_summary_requires_real_sources')
    content=q.get('content'); key=q.get('key')
    if not isinstance(content,str) or not content.strip() or len(content)>900 or not isinstance(key,str) or not 1<=len(key)<=100:
        raise ValueError('invalid_summary_content')
    rows=source_rows(b,scope,q.get('source_ids'))
    if len(rows)!=len(set(q['source_ids'])) or any(origin(r)!=typ for r in rows): raise ValueError('summary_scope_or_origin_mismatch')
    if level==3 and (len({r['event_id'] for r in rows})<2): raise ValueError('stable_summary_requires_repeated_evidence')
    refs=[dict(id=r['id'],hash=r['fingerprint']) for r in rows]
    with b.db:
        b.db.execute('INSERT OR REPLACE INTO ct_summary VALUES(?,?,?,?,?,?,?)',
                     (scope,key,level,typ,content,dump(refs),stamp()))
    return dict(ok=True,key=key,meaning='derived_summary_with_original_sources')


def people_sync(b,q):
    # Paths are installed local host bindings, never arbitrary model-supplied paths.
    cfg=_get(b,'host_paths',{})
    source=Path(cfg.get('people_json',str(b.root/'native'/'channel-people.json'))).expanduser()
    pages=Path(cfg.get('people_dir',str(b.root/'native'/'people'))).expanduser()
    now=stamp(); seen=0
    if source.is_file():
        records=json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(records,dict): raise ValueError('invalid_people_source')
        for pid,value in records.items():
            if not isinstance(value,dict): continue
            person='qq:'+str(pid)
            with b.db:
                b.db.execute('INSERT INTO ct_person(id,name,role,note,path,at) VALUES(?,?,?,?,?,?) '
                             'ON CONFLICT(id) DO UPDATE SET name=excluded.name,role=excluded.role,note=excluded.note,path=excluded.path',
                             (person,str(value.get('name') or pid)[:120],'bot' if value.get('type')=='bot' else 'known',
                              str(value.get('note',''))[:1200],str(source),now))
            seen+=1
    mapped=_get(b,'person_map',{})
    if pages.is_dir():
        for file in sorted(pages.glob('*.md')):
            if file.is_symlink() or file.name=='INDEX.md': continue
            text=file.read_text(encoding='utf-8')[:12000]
            heading=re.search(r'^#\s+(.+)$',text,re.M)
            pid=mapped.get(file.name,'page:'+file.stem)
            # No fuzzy joins: pages without explicit id links stay separate.
            with b.db:
                b.db.execute('INSERT INTO ct_person(id,name,note,path,at) VALUES(?,?,?,?,?) '
                             'ON CONFLICT(id) DO UPDATE SET name=excluded.name,note=excluded.note,path=excluded.path',
                             (pid,heading.group(1).strip()[:120] if heading else file.stem,text,str(file),now))
            seen+=1
    return dict(ok=True,sources=seen,policy='explicit_identity_map_only; relationship_values_are_model_inferences_not_permissions')


def backup(b,q):
    from datetime import datetime
    day=q.get('day') or datetime.now(TZ).date().isoformat()
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): raise ValueError('invalid_backup_day')
    summary=_get(b,'daily_summary:'+day)
    if not summary: return dict(ok=False,error='daily_summary_not_completed')
    delivery_id='native-memory:'+day
    previous=b.db.execute('SELECT * FROM ct_delivery WHERE id=?',(delivery_id,)).fetchone()
    if previous: return dict(ok=True,replayed=True,delivery=dict(previous))
    directory=b.root/'exports'/('memory-'+day)
    directory.mkdir(parents=True,exist_ok=True); os.chmod(directory,0o700)
    dest=directory/'brain.sqlite'
    files=[]
    # Native files are copied byte for byte; secrets/channel account files excluded.
    sources=[b.root/'brain.py',*sorted((b.root/'muse_ext').glob('*.py')),
             b.root/'muse_ext'/'companion_panel.html',b.root/'PERSONA.md',b.root/'companion-protocol.md']
    config=b.root/'config.json'
    if config.is_file():
        conf=json.loads(config.read_text(encoding='utf-8'))
        if re.search(r'"[^"\n]*(?:token|password|secret|api.?key|authorization)[^"\n]*"\s*:',dump(conf),re.I):
            raise ValueError('config_contains_secrets_move_credentials_to_env')
        sources.append(config)
    paths=_get(b,'host_paths',{})
    people=Path(paths.get('people_dir',str(b.root/'native'/'people'))).expanduser()
    if people.is_dir(): sources+=sorted(p for p in people.glob('*.md') if not p.is_symlink())
    selected={}
    for file in sources:
        if not file.is_file() or file.is_symlink(): continue
        if file.is_relative_to(b.root): rel=file.relative_to(b.root)
        elif file.parent==people: rel=Path('people')/file.name
        else: continue
        selected[rel.as_posix()]=file
    # Native people.json is included, never bridge .env / account state / tokens.
    pj=Path(paths.get('people_json',str(b.root/'native'/'channel-people.json'))).expanduser()
    if pj.is_file() and not pj.is_symlink():
        selected['people.json']=pj
    # Extend the already-approved native allowlist, without old deployment/
    # rollback journals. Missing REQUIRED sources stop delivery, never fake full.
    registry=b.root/'backup-sources.json'
    if registry.is_file():
        catalog=json.loads(registry.read_text(encoding='utf-8'))
        for entry in catalog.get('sources',[]):
            file=Path(entry['path']).expanduser(); name=entry['name']
            if not file.is_file():
                if entry.get('required'): raise ValueError('required_native_backup_source_missing:'+name)
                continue
            selected['native/'+name]=file
        for entry in catalog.get('trees',[]):
            folder=Path(entry['path']).expanduser()
            if folder.name not in ('memory','companion','definitions','library'): raise ValueError('invalid_native_backup_tree')
            if not folder.is_dir():
                if entry.get('required'): raise ValueError('required_native_backup_tree_missing')
                continue
            for file in folder.rglob('*'):
                if file.is_file() and file.suffix.lower() in ('.md','.json','.jsonl','.txt'):
                    selected['native/'+entry['name']+'/'+file.relative_to(folder).as_posix()]=file
        selected['backup-sources.json']=registry
    for pattern in ('templates/**/*.md','state/**/*.json','state/**/*.jsonl','state/**/*.txt','library/**/*.md','library/**/*.txt'):
        for file in b.root.glob(pattern):
            if file.is_file() and file.name not in ('deployment.json',): selected[file.relative_to(b.root).as_posix()]=file
    # Validate paths + freeze native versions before the consistent database snapshot.
    for name,file in selected.items():
        parts=Path(name).parts+file.parts
        if Path(name).is_absolute() or '..' in Path(name).parts or any(p.lower().startswith('.env') or p.lower() in ('secrets','credentials','vault') for p in parts):
            raise ValueError('credential_or_unsafe_backup_source')
        if any(p.is_symlink() for p in (file,*file.parents)): raise ValueError('backup_symlink_refused')
    before={name:digest(file) for name,file in selected.items()}
    with closing(sqlite3.connect(dest)) as target: b.db.backup(target)
    os.chmod(dest,0o600); files.append(dest)
    for name,file in selected.items():
        target=directory/name; target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,target); os.chmod(target,0o600); files.append(target)
        if digest(target)!=before[name]: raise ValueError('native_backup_source_changed')
    if any(digest(file)!=before[name] for name,file in selected.items()): raise ValueError('native_backup_source_changed')
    manifest=dict(version=VERSION,day=day,summary=summary,created=stamp(),
                  files=[dict(path=str(p.relative_to(directory)),size=p.stat().st_size,sha256=digest(p)) for p in files],
                  omitted=['credentials','.env','channel_account_state','temporary_files','nested_backups'],
                  formats='native; sqlite via consistent SQLite backup API; others byte-identical')
    atomic(directory/'manifest.json',dump(manifest))
    atomic(directory/'attachments.md','\n\n'.join('!['+p.name+'](sandbox://workspace/'+str(p.relative_to(b.root.parent)).replace('\\','/')+')' for p in files+[directory/'manifest.json']))
    with b.db:
        b.db.execute('INSERT INTO ct_delivery VALUES(?,?,?,?,?,NULL)',(delivery_id,'native_backup','prepared',dump(manifest),stamp()))
    return dict(ok=True,id=delivery_id,directory=str(directory),attachment_body=str(directory/'attachments.md'),manifest=manifest)


def delivery(b,q):
    row=b.db.execute('SELECT * FROM ct_delivery WHERE id=?',(q.get('id'),)).fetchone()
    if not row: raise ValueError('backup_not_prepared')
    action=q.get('action','claim')
    with b.db:
        if action=='claim':
            count=b.db.execute("UPDATE ct_delivery SET status='sending',at=? WHERE id=? AND status IN ('prepared','failed')",(stamp(),row['id'])).rowcount
            return dict(ok=True,claimed=bool(count),id=row['id'],status='sending' if count else row['status'])
        state=q.get('outcome')
        if state not in ('accepted','unknown','failed'): raise ValueError('invalid_delivery_outcome')
        receipt=str(q.get('receipt') or '')[:500]
        count=b.db.execute("UPDATE ct_delivery SET status=?,receipt=?,at=? WHERE id=? AND status='sending'",(state,receipt,stamp(),row['id'])).rowcount
        return dict(ok=True,settled=bool(count),status=state if count else row['status'])


def panel(b,q):
    from muse_ext.humor import settings
    from muse_ext.meme_store import status as meme_status
    snapshot=dict(version=VERSION,generated_at=stamp(),timezone='Asia/Shanghai',
                  expression_settings=settings(b),meme_knowledge=meme_status(b),
                  mood=mood(b,'owner-private'),companion=context(b,'owner-private'),
                  stored_mood=[dict(r) for r in b.db.execute('SELECT * FROM mood')],
                  people=[dict(r) for r in b.db.execute('SELECT * FROM ct_person ORDER BY role,name')],
                  life=[dict(r) for r in b.db.execute('SELECT * FROM ct_life ORDER BY occurred DESC LIMIT 50')],
                  summaries=[dict(r) for r in b.db.execute('SELECT scope,key,level,origin,content,updated FROM ct_summary ORDER BY updated DESC LIMIT 30')],
                  counts={name:b.db.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('memories','source_events','ct_summary','ct_expectation')},
                  backup=[dict(r) for r in b.db.execute('SELECT id,status,at,receipt FROM ct_delivery ORDER BY at DESC LIMIT 14')],
                  latency=[dict(r) for r in b.db.execute('SELECT kind,count(*) samples,round(avg(ms),2) avg_ms,round(max(ms),2) max_ms FROM ct_metric GROUP BY kind')],
                  tasks=_get(b,'task_bindings',{}),
                  disclaimer='本地管理快照；数值为虚拟角色状态/模型推断，不代表真实心理测量；关系等级不授予权限。')
    from muse_ext.panel_home import enrich
    enrich(b,snapshot)
    template=(Path(__file__).parent/'companion_panel.html').read_text(encoding='utf-8')
    # </script>, markup and Unicode separators cannot escape the JSON script block.
    payload=dump(snapshot).replace('<','\\u003c').replace('>','\\u003e').replace('&','\\u0026').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    target=b.root/'exports'/'Companion面板.html'
    atomic(target,template.replace('__MUSE_SNAPSHOT_JSON__',payload))
    return dict(ok=True,path=str(target),snapshot_at=snapshot['generated_at'],offline=True,read_only=True)


def operations(b,q):
    op=q['op']
    if op=='companion_summary_work': return summary_work(b,q)
    if op=='companion_summary_commit': return summary_commit(b,q)
    if op=='companion_summary_ack':
        # Ack a batch only after ALL summaries for that batch have committed.
        typ=q.get('origin'); scope=q.get('target_scope','owner-private'); rev=q.get('revision')
        if typ not in ('real','virtual','dream','inference') or not isinstance(rev,str) or len(rev)!=64: raise ValueError('invalid_ack')
        batch=_get(b,'summary_batch:'+scope+':'+typ)
        if not batch or batch['revision']!=rev: raise ValueError('unknown_summary_batch')
        with b.db:
            for ref in batch['refs']:
                current=b.db.execute("SELECT fingerprint FROM memories WHERE id=? AND scope=? AND status='active'",(ref['id'],scope)).fetchone()
                if current and current[0]==ref['hash']:
                    b.db.execute('INSERT OR REPLACE INTO ct_summarized VALUES(?,?,?)',(scope,ref['id'],ref['hash']))
            _set(b,'summary_cursor:'+scope+':'+typ,rev)
        return dict(ok=True)
    if op=='companion_people_sync': return people_sync(b,q)
    if op=='companion_summary_done':
        day=q.get('day'); reference=q.get('reference')
        if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) or not isinstance(reference,str) or not reference.strip():
            raise ValueError('summary_reference_required')
        with b.db: _set(b,'daily_summary:'+day,dict(reference=reference[:500],at=stamp()))
        return dict(ok=True,day=day,next='companion_backup')
    if op=='companion_backup': return backup(b,q)
    if op=='companion_delivery': return delivery(b,q)
    if op=='companion_panel': return panel(b,q)
    if op=='companion_bind':
        # Local admin operation; never exposed as an untrusted chat/group tool.
        for key in ('host_paths','task_bindings','person_map'):
            if key in q:
                if not isinstance(q[key],dict): raise ValueError('invalid_binding')
                with b.db: _set(b,key,q[key])
        return dict(ok=True)
    raise ValueError('unknown_companion_operation')
