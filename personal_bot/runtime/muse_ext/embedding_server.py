"""Pinned Chinese ONNX encoder. One CPU inference; no public listener."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .embeddings import MODEL_ID, DIMENSION, normalized


def verify_assets(folder, manifest):
    folder=Path(folder)
    for asset in manifest['assets']:
        path=folder/asset['path']
        if not path.is_file() or path.is_symlink() or path.stat().st_size!=asset['size'] or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
            raise ValueError('model_asset_mismatch:'+asset['path'])


def download_assets(folder, manifest):
    folder=Path(folder).resolve()
    folder.mkdir(parents=True,exist_ok=True)
    repo,revision=manifest['repository'],manifest['revision']
    if repo!='Xenova/bge-small-zh-v1.5' or revision!='75c43b069aac4d136ba6bc1122f995fedcfd2781':
        raise ValueError('unexpected_model_repository')
    for asset in manifest['assets']:
        if asset['path'] not in ('config.json','tokenizer.json','tokenizer_config.json','special_tokens_map.json','onnx/model_quantized.onnx'):
            raise ValueError('unexpected_model_asset')
        path=folder/asset['path']
        if path.exists():
            if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=asset['sha256']:
                raise ValueError('existing_model_asset_mismatch')
            continue
        if path.parent.is_symlink():raise ValueError('unsafe_model_path')
        path.parent.mkdir(parents=True,exist_ok=True)
        url=f'https://huggingface.co/{repo}/resolve/{revision}/'+asset['path']
        tmp=path.with_suffix(path.suffix+'.part')
        with urllib.request.urlopen(url,timeout=90) as source,open(tmp,'xb') as dest:
            remaining=asset['size']
            while remaining:
                block=source.read(min(1<<20,remaining))
                if not block:raise ValueError('incomplete_model_asset')
                dest.write(block);remaining-=len(block)
            if source.read(1):raise ValueError('oversized_model_asset')
        if hashlib.sha256(tmp.read_bytes()).hexdigest()!=asset['sha256']:
            raise ValueError('download_model_hash_mismatch')
        os.replace(tmp,path)
    verify_assets(folder,manifest)


class Encoder:
    def __init__(self,folder,manifest):
        verify_assets(folder,manifest)
        import onnxruntime as ort
        ort.disable_telemetry_events()
        from tokenizers import Tokenizer
        opts=ort.SessionOptions()
        opts.intra_op_num_threads=1;opts.inter_op_num_threads=1
        opts.enable_cpu_mem_arena=False;opts.enable_mem_pattern=False
        opts.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        self.session=ort.InferenceSession(str(Path(folder)/'onnx/model_quantized.onnx'),sess_options=opts,providers=['CPUExecutionProvider'])
        self.tokenizer=Tokenizer.from_file(str(Path(folder)/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=512)
        self.prefix=manifest['query_prefix'];self.lock=threading.Lock()

    def encode(self,text,query=False):
        import numpy as np
        if not isinstance(text,str) or not text or len(text)>12000 or not isinstance(query,bool):
            raise ValueError('invalid_input')
        entry=self.tokenizer.encode((self.prefix if query else '')+text)
        arrays={'input_ids':entry.ids,'attention_mask':entry.attention_mask,'token_type_ids':entry.type_ids}
        feed={x.name:np.array([arrays[x.name]],dtype=np.int64) for x in self.session.get_inputs()}
        result=self.session.run(None,feed)[0]
        vector=result[0,0,:].tolist() if result.ndim==3 else result[0].tolist()
        if len(vector)!=DIMENSION:raise ValueError('model_dimension_mismatch')
        return normalized(vector)


def serve(encoder):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass  # Never log private query text.
        def do_POST(self):
            if (self.path!='/encode' or self.headers.get('Origin') or
                self.headers.get('X-Muse-Embedding')!='local-v2' or
                self.headers.get('Content-Type')!='application/json'):
                self.send_error(403);return
            try:n=int(self.headers.get('Content-Length','0'))
            except ValueError:n=0
            if not 0<n<=65536:self.send_error(413);return
            if not encoder.lock.acquire(blocking=False):self.send_error(503);return
            try:
                self.connection.settimeout(.5)
                q=json.loads(self.rfile.read(n))
                started=time.monotonic()
                v=encoder.encode(q['text'],q.get('query',False))
                payload=json.dumps({'model':MODEL_ID,'vector':v,'elapsed_ms':(time.monotonic()-started)*1000}).encode()
                self.send_response(200);self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            except (ValueError,KeyError,TypeError):self.send_error(400)
            except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
            finally:encoder.lock.release()
    server=ThreadingHTTPServer(('127.0.0.1',18765),Handler)
    server.daemon_threads=True
    server.serve_forever()


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--folder',required=True);p.add_argument('--manifest',required=True)
    p.add_argument('--download',action='store_true');p.add_argument('--check',action='store_true')
    a=p.parse_args();manifest=json.loads(Path(a.manifest).read_text(encoding='utf-8'))
    if a.download:
        download_assets(a.folder,manifest);print('verified model assets');return
    encoder=Encoder(a.folder,manifest)
    if a.check:
        q=encoder.encode('上班用什么交通工具',True)
        a=encoder.encode('每天骑自行车去公司');b=encoder.encode('今天午饭吃红烧肉')
        related=sum(x*y for x,y in zip(q,a));other=sum(x*y for x,y in zip(q,b))
        print(json.dumps({'model':MODEL_ID,'dimension':len(q),'related':related,'unrelated':other,'semantic_check':related>other+.08}))
        if related<=other+.08:raise SystemExit(1)
        return
    encoder.encode('启动检查')
    print('loopback encoder ready',flush=True)
    serve(encoder)


if __name__=='__main__':main()
