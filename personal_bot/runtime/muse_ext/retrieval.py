"""Union lexical, local semantic and two-hop entity evidence, scoped in SQL."""
import heapq
import json
import math
import time


def recall(brain,q):
    from brain import tokens
    from . import embeddings
    scope,text=q['scope'],q.get('text','')
    terms=tokens(text)[:64]
    clauses=["m.scope=?","m.status='active'","m.evidence!='inference'"]
    args=[scope]
    for name,sql in [('start','m.occurred_at>=?'),('end','m.occurred_at<?')]:
        if name in q:
            n=float(q[name])
            if not math.isfinite(n):raise ValueError('invalid_time')
            clauses.append(sql);args.append(n)
    where=' AND '.join(clauses)
    candidates,semantic={},{}
    def collect(rows):
        for r in rows:candidates[r['id']]=r
    if terms:
        match=' OR '.join('"'+t.replace('"','""')+'"' for t in terms)
        collect(brain.db.execute('''SELECT m.* FROM search JOIN memories m ON m.id=search.rowid
            WHERE search MATCH ? AND '''+where+' ORDER BY bm25(search) LIMIT 300',[match,*args]))
    elif 'start' in q or 'end' in q:
        collect(brain.db.execute('SELECT m.* FROM memories m WHERE '+where+' ORDER BY occurred_at DESC LIMIT 300',args))
    # Real entity edges: matched entities -> directly linked records -> shared
    # entities -> second-hop records. Every hop and returned record is scoped.
    graph_ids=set()
    if text:
        names=[r[0] for r in brain.db.execute('SELECT DISTINCT name FROM entities WHERE scope=?',(scope,)) if r[0] in text][:20]
        if names:
            marks=','.join('?'*len(names))
            linked=[r[0] for r in brain.db.execute('SELECT DISTINCT memory_id FROM entities WHERE scope=? AND name IN ('+marks+') LIMIT 100',[scope,*names])]
            if linked:
                lm=','.join('?'*len(linked))
                neighbors=brain.db.execute('''SELECT m.* FROM memories m JOIN entities e ON e.memory_id=m.id
                    WHERE '''+where+''' AND e.scope=? AND e.name IN
                    (SELECT name FROM entities WHERE scope=? AND memory_id IN ('''+lm+')) LIMIT 200',
                    [*args,scope,scope,*linked]).fetchall()
                collect(neighbors);graph_ids.update(r['id'] for r in neighbors)
    vector=False;status='not_requested'
    embeddings.initialize(brain.db)
    if text:
        try:
            query=embeddings.normalized(embeddings.encode(text,query=True))
            # Stream all eligible indexed vectors; never preselect latest300.
            heap=[];deadline=time.perf_counter()+.035
            for r in brain.db.execute('''SELECT m.*,v.vector FROM memory_vectors v JOIN memories m ON m.id=v.memory_id
                WHERE '''+where+' AND v.model=? AND v.dimension=? AND v.fingerprint=m.fingerprint',
                [*args,embeddings.MODEL_ID,len(query)]):
                if time.perf_counter()>deadline:
                    # A partial corpus rank is biased by storage order. Drop it
                    # entirely and retain the independent lexical/graph union.
                    raise TimeoutError('semantic_scan_budget')
                v=json.loads(r['vector'])
                score=sum(a*b for a,b in zip(query,v))
                if score>=.35:
                    item=(score,r['id'],r)
                    if len(heap)<60:heapq.heappush(heap,item)
                    elif score>heap[0][0]:heapq.heapreplace(heap,item)
            for score,mid,r in heap:
                candidates[mid]=r;semantic[mid]=score
            vector=True;status='ready'
        except TimeoutError as exc:
            status='budget_exceeded_keyword_fallback' if str(exc)=='semantic_scan_budget' else 'unavailable_keyword_fallback'
        except (OSError,ValueError,KeyError,TypeError):
            status='unavailable_keyword_fallback'
    now=time.time();query_terms=set(terms)
    def rank(r):
        lexical=len(query_terms.intersection(tokens(r['text'])))/max(1,len(query_terms))
        signal=max(lexical,semantic.get(r['id'],0),.45 if r['id'] in graph_ids else 0)
        return signal*.7+r['importance']*.2+math.exp(-max(0,now-r['occurred_at'])/(86400*60))*.1
    result=[];budget=2400
    for r in sorted(candidates.values(),key=rank,reverse=True):
        if len(result)>=6 or budget<=0:break
        item={k:r[k] for k in ('id','text','kind','source','event_id','evidence','occurred_at')}
        item['text']=item['text'][:budget];item['truncated']=len(item['text'])<len(r['text'])
        budget-=len(item['text']);result.append(item)
    return dict(ok=True,memories=result,retrieval='keyword_vector_entity_importance_recency',
                vector=vector,vector_status=status,graph=bool(graph_ids))
