"""Derived notes are separately labelled and cannot outlive source eligibility."""
import hashlib
import json
import math


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS derived_notes(
      memory_id INTEGER PRIMARY KEY,scope TEXT NOT NULL,sources TEXT NOT NULL,
      derivation_key TEXT NOT NULL UNIQUE)''')


def link(brain,mid,scope,sources,key):
    brain.db.execute('INSERT OR IGNORE INTO derived_notes VALUES(?,?,?,?)',(mid,scope,json.dumps(sources),key))


def derive(brain,q):
    initialize(brain.db)
    if not brain.feature('consolidation') or not brain.available('memory'):
        return {'ok':False,'disabled':True}
    ids=q.get('sources');kind=q.get('kind')
    if kind not in ('reflection','skill','lesson') or not isinstance(ids,list) or not 1<=len(ids)<=10 or any(type(x)!=int for x in ids):
        raise ValueError('invalid_derivation_sources_or_kind')
    from brain import config_guard
    with config_guard(brain.root),brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        rows=[brain.db.execute("SELECT * FROM memories WHERE id=? AND scope=? AND status='active' AND evidence!='inference'",(mid,q['scope'])).fetchone() for mid in sorted(set(ids))]
        if any(r is None for r in rows):raise ValueError('invalid_derivation_sources')
        key=hashlib.sha256(json.dumps([kind,[(r['id'],r['fingerprint']) for r in rows]]).encode()).hexdigest()
        old=brain.db.execute('SELECT memory_id FROM derived_notes WHERE derivation_key=?',(key,)).fetchone()
        if old:return {'ok':True,'id':old[0],'replayed':True}
        mid=brain._remember(dict(q,source='assistant:derivation',event_id='derive:'+key,evidence='inference',importance=.6))
        link(brain,mid,q['scope'],sorted(set(ids)),key)
        return {'ok':True,'id':mid,'evidence':'inference','sources':sorted(set(ids))}


def recall(brain,q):
    if not brain.db.execute("SELECT 1 FROM sqlite_master WHERE name='derived_notes'").fetchone():return []
    from brain import tokens
    terms=tokens(q.get('text',''))[:32]
    if not terms:return []
    match=' OR '.join('"'+t+'"' for t in terms)
    bounds='';args=[match,q['scope'],q['scope']]
    for key,clause in [('start','m.occurred_at>=?'),('end','m.occurred_at<?')]:
        if key in q:
            value=float(q[key])
            if not math.isfinite(value):raise ValueError('invalid_time')
            bounds+=' AND '+clause;args.append(value)
    rows=brain.db.execute('''SELECT m.*,d.sources FROM search JOIN memories m ON m.id=search.rowid
        JOIN derived_notes d ON d.memory_id=m.id WHERE search MATCH ? AND m.scope=? AND d.scope=?
        AND m.status='active' AND m.evidence='inference' '''+bounds+' ORDER BY m.occurred_at DESC LIMIT 20',args).fetchall()
    result=[];budget=1200
    for row in rows:
        ids=json.loads(row['sources'])
        if not ids or any(not brain.db.execute("SELECT 1 FROM memories WHERE id=? AND scope=? AND status='active' AND evidence!='inference'",(mid,q['scope'])).fetchone() for mid in ids):continue
        if len(result)>=3 or budget<=0:break
        item={k:row[k] for k in ('id','text','kind','source','evidence','occurred_at')}
        item['text']=item['text'][:budget];item['sources']=ids;budget-=len(item['text']);result.append(item)
    return result
