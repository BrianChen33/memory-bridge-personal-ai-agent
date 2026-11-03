"""Short loopback-only encoder client and versioned local vector index."""
import hashlib
import json
import math
import urllib.request

MODEL_ID='Xenova/bge-small-zh-v1.5@75c43b069aac4d136ba6bc1122f995fedcfd2781:int8-cls'
DIMENSION=512
ENDPOINT='http://127.0.0.1:18765/encode'


def initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS memory_vectors(
      memory_id INTEGER PRIMARY KEY,model TEXT NOT NULL,dimension INTEGER NOT NULL,
      fingerprint TEXT NOT NULL,vector TEXT NOT NULL)''')


def normalized(vector):
    if not isinstance(vector,list) or not vector or len(vector)>2048 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector):
        raise ValueError('invalid_vector')
    norm=math.sqrt(sum(x*x for x in vector))
    if norm<=0:
        raise ValueError('zero_vector')
    return [float(x/norm) for x in vector]


def encode(text, query=False, timeout=.12):
    if not isinstance(text,str) or not text or len(text)>12000:
        raise ValueError('invalid_embedding_text')
    data=json.dumps({'text':text,'query':query}).encode()
    req=urllib.request.Request(ENDPOINT,data=data,headers={'Content-Type':'application/json','X-Muse-Embedding':'local-v2'})
    # Disable proxy discovery so a local query can never be routed externally.
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req,timeout=timeout) as response:
        body=response.read(65537)
    if len(body)>65536:
        raise ValueError('oversized_encoder_response')
    result=json.loads(body)
    if result.get('model')!=MODEL_ID or len(result.get('vector',[]))!=DIMENSION:
        raise ValueError('encoder_model_mismatch')
    return normalized(result['vector'])


def store_vector(brain, memory_id, vector, model=MODEL_ID):
    initialize(brain.db)
    row=brain.db.execute("SELECT * FROM memories WHERE id=? AND status='active'",(memory_id,)).fetchone()
    if not row:
        raise ValueError('inactive_vector_source')
    vector=normalized(vector)
    with brain.db:
        brain.db.execute('INSERT OR REPLACE INTO memory_vectors VALUES(?,?,?,?,?)',
                         (memory_id,model,len(vector),row['fingerprint'],json.dumps(vector)))


def index_pending(brain, limit=20):
    initialize(brain.db)
    if not brain.feature('vector'):
        return {'ok':False,'disabled':True}
    rows=brain.db.execute('''SELECT m.* FROM memories m LEFT JOIN memory_vectors v ON m.id=v.memory_id
        WHERE m.status='active' AND (v.memory_id IS NULL OR v.model!=? OR v.fingerprint!=m.fingerprint)
        ORDER BY m.id LIMIT ?''',(MODEL_ID,max(1,min(30,int(limit))))).fetchall()
    count=0
    for row in rows:
        vector=encode(row['text'],timeout=3)
        # Update may have raced the encoder: compare the live fingerprint again.
        with brain.db:
            current=brain.db.execute("SELECT * FROM memories WHERE id=? AND status='active'",(row['id'],)).fetchone()
            if current and current['fingerprint']==row['fingerprint'] and brain.feature('vector'):
                store_vector(brain,row['id'],vector)
                count+=1
    return {'ok':True,'indexed':count,'model':MODEL_ID}
