"""Reversible source-preserving equivalence views; contradictions stay separate."""
import json
import re
import time


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS merge_groups(
      id INTEGER PRIMARY KEY,scope TEXT NOT NULL,status TEXT NOT NULL,
      canonical_id INTEGER NOT NULL,assessment TEXT NOT NULL,created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS merge_members(
      group_id INTEGER NOT NULL,memory_id INTEGER NOT NULL,fingerprint TEXT NOT NULL,
      PRIMARY KEY(group_id,memory_id));
    ''')


def conflicting(rows):
    # Conservative: changing a number/date or polarity always requires review.
    values=[set(re.findall(r'\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+(?=[点时日号年月万元岁])',r['text'])) for r in rows]
    neg=[bool(re.search(r'不|没|无|从未|取消|停止|禁止|拒绝',r['text'])) for r in rows]
    return any(x!=values[0] for x in values[1:]) or len(set(neg))>1


def proposals(brain,scope):
    from brain import tokens
    rows=brain.db.execute("SELECT * FROM memories WHERE scope=? AND status='active' ORDER BY id DESC LIMIT 100",(scope,)).fetchall()
    vectors={}
    if brain.db.execute("SELECT 1 FROM sqlite_master WHERE name='memory_vectors'").fetchone():
        from .embeddings import MODEL_ID
        for r in brain.db.execute('''SELECT v.memory_id,v.vector FROM memory_vectors v JOIN memories m ON m.id=v.memory_id
            WHERE m.scope=? AND m.status='active' AND v.model=? AND v.fingerprint=m.fingerprint''',(scope,MODEL_ID)):
            vectors[r['memory_id']]=json.loads(r['vector'])
    out=[]
    for i,a in enumerate(rows):
        if brain.db.execute("SELECT 1 FROM merge_members mm JOIN merge_groups g ON g.id=mm.group_id WHERE mm.memory_id=? AND g.status='active'",(a['id'],)).fetchone():continue
        at=set(tokens(a['text']))
        for b in rows[i+1:]:
            if a['kind']!=b['kind'] or a['evidence']!=b['evidence']:continue
            bt=set(tokens(b['text']))
            overlap=len(at&bt)/max(1,len(at|bt))
            av,bv=vectors.get(a['id']),vectors.get(b['id'])
            sim=sum(x*y for x,y in zip(av,bv)) if av and bv and len(av)==len(bv) else 0
            if overlap>=.65 or sim>=.88:
                out.append(dict(ids=[a['id'],b['id']],hashes={str(r['id']):r['fingerprint'] for r in (a,b)},
                                quotes={str(r['id']):r['text'] for r in (a,b)},similarity=sim,
                                conflict_hint=conflicting([a,b]),requires_semantic_assessment=True))
                if len(out)>=10:return out
    return out


def dispatch(brain,q):
    initialize(brain.db)
    if not brain.feature('consolidation') or not brain.available('feedback'):
        return {'ok':False,'disabled':True}
    from brain import config_guard
    with config_guard(brain.root),brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        action=q.get('action');scope=q['scope']
        if action=='propose':return {'ok':True,'proposals':proposals(brain,scope)}
        if action=='undo':
            row=brain.db.execute('SELECT * FROM merge_groups WHERE id=? AND scope=?',(q.get('id'),scope)).fetchone()
            if not row:raise ValueError('group_not_in_scope')
            # Undo changes the view only; it never resurrects a hidden original.
            if row['status']=='active':brain.db.execute("UPDATE merge_groups SET status='undone' WHERE id=?",(row['id'],))
            return {'ok':True,'id':row['id']}
        if action!='merge':raise ValueError('invalid_consolidation_action')
        ids=q.get('ids')
        if not isinstance(ids,list) or not 2<=len(ids)<=8 or any(type(x)!=int for x in ids) or len(set(ids))!=len(ids):
            raise ValueError('invalid_merge_ids')
        rows=[brain.db.execute("SELECT * FROM memories WHERE id=? AND scope=? AND status='active'",(mid,scope)).fetchone() for mid in ids]
        if any(r is None for r in rows):raise ValueError('merge_requires_active_same_scope')
        if len({(r['kind'],r['evidence']) for r in rows})!=1:raise ValueError('incompatible_kind_or_evidence')
        hashes,quotes=q.get('hashes',{}),q.get('quotes',{})
        for r in rows:
            if hashes.get(str(r['id']))!=r['fingerprint']:raise ValueError('stale_source_hash')
            quote=quotes.get(str(r['id']))
            if not isinstance(quote,str) or not quote or quote!=r['text']:raise ValueError('exact_source_quote_required')
            if brain.db.execute("SELECT 1 FROM merge_members mm JOIN merge_groups g ON g.id=mm.group_id WHERE mm.memory_id=? AND g.status='active'",(r['id'],)).fetchone():
                raise ValueError('source_already_grouped')
        relation=q.get('relation');reason=q.get('reason')
        if relation not in ('equivalent','contradiction') or not isinstance(reason,str) or not 8<=len(reason)<=1000:
            raise ValueError('explicit_semantic_assessment_required')
        status='conflict' if relation=='contradiction' or conflicting(rows) else 'active'
        canonical=max(rows,key=lambda r:(r['evidence']=='confirmed',r['importance'],r['occurred_at']))['id']
        assessment=json.dumps(dict(relation=relation,reason=reason,quotes=quotes,evidence='inference'),ensure_ascii=False)
        cur=brain.db.execute('INSERT INTO merge_groups(scope,status,canonical_id,assessment,created_at) VALUES(?,?,?,?,?)',
                             (scope,status,canonical,assessment,time.time()))
        for r in rows:brain.db.execute('INSERT INTO merge_members VALUES(?,?,?)',(cur.lastrowid,r['id'],r['fingerprint']))
        return {'ok':True,'id':cur.lastrowid,'status':status,'merged':status=='active','original_ids':ids}


def apply_views(brain,response,scope):
    if not brain.feature('consolidation'):return response
    initialize(brain.db)
    seen=set();result=[]
    for item in response.get('memories',[]):
        group=brain.db.execute("SELECT g.* FROM merge_groups g JOIN merge_members mm ON mm.group_id=g.id WHERE mm.memory_id=? AND g.scope=? AND g.status='active'",(item['id'],scope)).fetchone()
        if not group:
            result.append(item);continue
        if group['id'] in seen:continue
        rows=brain.db.execute('''SELECT m.id,m.status,m.fingerprint,mm.fingerprint AS expected FROM merge_members mm
            JOIN memories m ON m.id=mm.memory_id WHERE mm.group_id=? AND m.scope=?''',(group['id'],scope)).fetchall()
        if any(r['status']!='active' or r['fingerprint']!=r['expected'] for r in rows):continue
        seen.add(group['id'])
        result.append(dict(item,merge_group=group['id'],original_ids=[r['id'] for r in rows]))
    return dict(response,memories=result)


def invalidate_group(brain,row,status):
    # Called inside the existing correct/forget transaction. No executescript.
    if not brain.db.execute("SELECT 1 FROM sqlite_master WHERE name='merge_groups'").fetchone():return
    groups=brain.db.execute("SELECT g.id FROM merge_groups g JOIN merge_members mm ON mm.group_id=g.id WHERE mm.memory_id=? AND g.scope=? AND g.status='active'",(row['id'],row['scope'])).fetchall()
    for group in groups:
        members=brain.db.execute('SELECT m.* FROM memories m JOIN merge_members mm ON m.id=mm.memory_id WHERE mm.group_id=? AND m.scope=?',(group['id'],row['scope'])).fetchall()
        for m in members:
            brain.db.execute("UPDATE memories SET status=? WHERE id=? AND status='active'",(status,m['id']))
            from .events import hide_original
            hide_original(brain,m)
        brain.db.execute('UPDATE merge_groups SET status=? WHERE id=?',(status,group['id']))
