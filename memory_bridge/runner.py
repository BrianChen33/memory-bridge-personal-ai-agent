"""Bounded JSON self-test runner. No live capture, external paths or commands."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from .core import Invalid, strict_json

INPUT_LIMIT = 65536
OUTPUT_LIMIT = 16384
DEADLINE_SECONDS = 5.0
WORKER_CODE = 'from memory_bridge.runner import _worker_main; _worker_main()'

class RunnerFailure(Exception): pass


def _read_input(stream,timeout):
    result=queue.Queue(maxsize=1)
    def reader():
        try:
            try: fd=stream.fileno()
            except (AttributeError,OSError,ValueError): fd=None
            if fd is None:
                raw=stream.read(INPUT_LIMIT+1)
            else:
                # Avoid holding buffered stdin locks in a daemon during timeout.
                chunks=[]; remaining=INPUT_LIMIT+1
                while remaining:
                    chunk=os.read(fd,remaining)
                    if not chunk: break
                    chunks.append(chunk); remaining-=len(chunk)
                raw=b''.join(chunks)
            result.put(raw)
        except Exception: result.put(None)
    threading.Thread(target=reader,daemon=True).start()
    try: raw=result.get(timeout=max(0,timeout))
    except queue.Empty: raise RunnerFailure('timeout') from None
    if not isinstance(raw,(bytes,str)): raise RunnerFailure('invalid_input')
    try:
        if len(raw.encode('utf-8') if isinstance(raw,str) else raw)>INPUT_LIMIT: raise RunnerFailure('input_too_large')
        request=strict_json(raw)
    except (Invalid,UnicodeError): raise RunnerFailure('invalid_input') from None
    if not isinstance(request,dict) or set(request)!={'mode'} or request['mode']!='self-test': raise RunnerFailure('unsupported_request')
    return request


def _self_test(root):
    """Uses only the parent-created temporary directory and synthetic values."""
    from .core import Policy,Store,Denied
    from .muse import ScopeGrant,api_row_digest,transform_response
    from .sync import FakePrivateTransport,export,pull
    checks=[]
    def require(name,value):
        if not value: raise RunnerFailure('self_test_failed')
        checks.append(name)
    canary=root/'synthetic_canary.txt'; canary.write_text('Synthetic persona canary, never shared.\n')
    before=canary.read_bytes()
    row={'id':1,'text':'Synthetic project uses SQLite.','kind':'fact','source':'synthetic-test','event_id':'event-1','evidence':'confirmed','occurred_at':1000.5,'truncated':False}
    event=transform_response({'memories':[row],'style':object(),'emotion':object()},origin='recall',selected_row_id=1,selected_digest=api_row_digest(row),grant=ScopeGrant('synthetic-principal','owner-private','demo_owner','shared'),verified_principal='synthetic-principal',category='project_fact')
    p=Policy('demo_owner','shared'); q=Policy('demo_owner','shared')
    left=Store(root/'left','demo_owner',p); right=Store(root/'right','demo_owner',q)
    transport=FakePrivateTransport()
    try:
        try: left.ingest([event])
        except Denied: checks.append('unapproved_event_denied')
        else: raise RunnerFailure('self_test_failed')
        until=int(time.time())+60
        # Test-only approval of this fixed synthetic fixture is not live consent.
        for policy in (p,q): policy.approve(event,audience='shared',until=until,consent=True)
        left.ingest([event]); export(left,event['source'],transport)
        require('dry_run_unchanged',not transport.files)
        export(left,event['source'],transport,dry_run=False)
        pull(right,event['source'],transport,dry_run=False); pull(right,event['source'],transport,dry_run=False)
        require('replica_deduplicated',len(right.events())==1)
        require('untrusted_retrieval',right.query('SQLite')[0]['trust']=='untrusted_data')
        tombstone=dict(event,id='synthetic_delete',op='delete',revision=2,text='')
        for policy in (p,q): policy.approve(tombstone,audience='shared',until=until,consent=True)
        left.ingest([tombstone]); export(left,event['source'],transport,dry_run=False)
        pull(right,event['source'],transport,dry_run=False); right.ingest([event])
        require('tombstone_no_resurrection',not right.query())
        revocable=dict(event,id='synthetic_revocable',fact='synthetic_revocable_fact',text='Synthetic revocable task.')
        q.approve(revocable,audience='shared',until=until,consent=True); right.ingest([revocable])
        require_visible=bool(right.query('revocable'))
        q.revoke(revocable); require('revocation_hidden',require_visible and not right.query('revocable'))
        require('synthetic_canary_unchanged',canary.read_bytes()==before)
    finally: left.close(); right.close()
    return {'protocol':'memory-bridge-runner/1','version':'0.1.2','mode':'self-test','status':'passed','checks':checks,'check_count':len(checks),'network_used':False,'production_data_accessed':False,'native_bots_invoked':False}


def _worker_main():
    """Private fixed worker entrypoint; arguments supplied only by the parent."""
    try:
        root=Path(sys.argv[1]); delay=float(sys.argv[2])
        if delay: time.sleep(delay)
        result=_self_test(root)
        sys.stdout.write(json.dumps(result)+'\n'); sys.stdout.flush()
    except BaseException:
        sys.stdout.write('{"status":"failed"}\n'); sys.stdout.flush(); raise SystemExit(1)


def _run_worker(root,timeout,*,test_delay=0):
    child=subprocess.Popen([sys.executable,'-c',WORKER_CODE,str(root),str(test_delay)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,shell=False)
    try:
        try: output,_=child.communicate(timeout=max(0,timeout))
        except subprocess.TimeoutExpired:
            child.kill(); child.communicate(); raise RunnerFailure('timeout') from None
        if child.returncode!=0 or len(output)>OUTPUT_LIMIT: raise RunnerFailure('self_test_failed')
        try: result=strict_json(output,max_bytes=OUTPUT_LIMIT)
        except Invalid: raise RunnerFailure('self_test_failed') from None
        if not isinstance(result,dict) or result.get('status')!='passed': raise RunnerFailure('self_test_failed')
        return result
    finally:
        if child.poll() is None: child.kill(); child.wait()


def run(stream,*,timeout=DEADLINE_SECONDS,test_delay=0):
    """Deadline includes input wait and worker time. Private test knobs not in JSON."""
    started=time.monotonic()
    _read_input(stream,timeout)
    with tempfile.TemporaryDirectory(prefix='memory-bridge-self-test-') as tmp:
        os.chmod(tmp,0o700)
        return _run_worker(Path(tmp),timeout-(time.monotonic()-started),test_delay=test_delay)


def main():
    try:
        if len(sys.argv)!=1: raise RunnerFailure('unsupported_request')
        result=run(sys.stdin.buffer)
        sys.stdout.write(json.dumps(result)+'\n'); return 0
    except RunnerFailure as exc:
        # Fixed error codes only. Never reflect input, paths, credentials or traces.
        code=str(exc)
        if code not in {'timeout','invalid_input','input_too_large','unsupported_request','self_test_failed'}: code='self_test_failed'
        sys.stdout.write(json.dumps({'protocol':'memory-bridge-runner/1','version':'0.1.2','status':'failed','error':code})+'\n'); return 1
    except BaseException:
        sys.stdout.write('{"protocol":"memory-bridge-runner/1","version":"0.1.2","status":"failed","error":"runner_failed"}\n'); return 1

if __name__=='__main__': raise SystemExit(main())
