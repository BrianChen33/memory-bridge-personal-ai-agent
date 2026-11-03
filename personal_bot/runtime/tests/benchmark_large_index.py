"""Acceptance benchmark: real Node adapter -> Python -> bounded loopback fixture.

Not a semantic-quality test; real pinned model quality is verified separately.
"""
import json,sqlite3,subprocess,tempfile,shutil,threading,time
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch
from brain import Brain
from muse_ext import embeddings


def main():
    here=Path(__file__).resolve().parents[1]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            body=json.dumps(dict(model=embeddings.MODEL_ID,vector=[1.]+[0.]*511)).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    # Use a random local port and patch only the copied fixture client endpoint.
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            shutil.copy2(here/'brain.py',root/'brain.py');shutil.copy2(here/'proactive.py',root/'proactive.py')
            shutil.copytree(here/'muse_ext',root/'muse_ext',ignore=shutil.ignore_patterns('__pycache__'))
            client=root/'muse_ext/embeddings.py'
            client.write_text(client.read_text(encoding='utf-8').replace(embeddings.ENDPOINT,f'http://127.0.0.1:{server.server_port}/encode'),encoding='utf-8')
            b=Brain(root);b.dispatch(dict(op='configure',enabled=True,features={'vector':True}))
            cfg=b.config();cfg['qq_enabled']=True;b.config_path.write_text(json.dumps(cfg),encoding='utf-8')
            for i in range(5000):
                b._remember(dict(scope='owner-private',text='自行车交通资料'+str(i),source='fixture:user',event_id=str(i)))
            embeddings.initialize(b.db)
            v=json.dumps([1.]+[0.]*511)
            b.db.execute('INSERT INTO memory_vectors SELECT id,?,512,fingerprint,? FROM memories',(embeddings.MODEL_ID,v));b.db.commit();b.close()
            source='''import {enhance} from processAdapter;
const r=enhance({inbox:{id:'bench',ts:Date.now(),text:'交通通勤',sender_id:'owner',reply_target:{scope:'c2c',targetId:'owner'}},sender_identity:{sender_id:'owner',is_master:true}},{root:process.argv[1],codeRoot:process.argv[1]});
console.log(JSON.stringify({ok:r.ok,degraded:r.degraded,elapsed_ms:r.elapsed_ms,status:r.vector_status,count:r.memories.length}));
'''.replace('processAdapter',json.dumps((here/'qq-adapter.mjs').as_uri()))
            p=subprocess.run(['node','--input-type=module','-e',source,str(root)],capture_output=True,text=True,timeout=10)
            if p.returncode:raise RuntimeError(p.stderr)
            result=json.loads(p.stdout)
            print(json.dumps(dict(index_rows=5000,**result)))
            if result.get('ok') is not True or result.get('degraded') or result['elapsed_ms']>=450 or result['count']==0:
                raise SystemExit(1)
    finally:server.shutdown();server.server_close()

if __name__=='__main__':main()
