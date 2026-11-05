"""Silent file publication after a real host event cycle; no scheduler or model API."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid

from muse_ext.panel_home import read_json


def atomic(path, data):
    path=Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp=path.with_name('.'+path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temp.open('wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.chmod(temp, 0o600); os.replace(temp, path)
    finally:
        if temp.exists(): temp.unlink()


@contextmanager
def guard(root):
    folder=Path(root)/'state'; folder.mkdir(parents=True, exist_ok=True)
    with (folder/'panel-refresh.lock').open('a+b') as stream:
        if os.name=='nt':
            import msvcrt
            if stream.seek(0, 2)==0: stream.write(b'0'); stream.flush()
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: yield
        finally:
            if os.name=='nt':
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(stream, fcntl.LOCK_UN)


def state_path(root):
    return Path(root)/'state'/'panel-update.json'


def save(root, value):
    atomic(state_path(root), json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def record(root, cycle, source_task, completed_at=None):
    """Call only AFTER the trusted host cycle successfully commits its updates."""
    if not cycle or len(cycle)>200 or not source_task or len(source_task)>200:
        raise ValueError('real_host_cycle_and_task_required')
    with guard(root):
        state=read_json(state_path(root))
        if state.get('cycle')==cycle:
            if state.get('source_task')!=source_task: raise ValueError('panel_cycle_source_conflict')
            return dict(ok=True, replayed=True, **state)
        completed=time.time() if completed_at is None else completed_at
        if isinstance(completed,bool) or not isinstance(completed,(int,float)) or not math.isfinite(completed) or completed>time.time()+1:
            raise ValueError('invalid_source_completion_time')
        due=math.ceil(completed+300)
        state.update(cycle=cycle, source_task=source_task, source_completed_at=completed,
                     due_at=due, next_at=due, cadence_seconds=1800, offset_after_event_seconds=300,
                     next_estimated=False, task_name='panel-refresh-'+hashlib.sha256(cycle.encode()).hexdigest()[:16],
                     native_task=None, status='awaiting_native_binding')
        state['at_local']=datetime.fromtimestamp(due, timezone(timedelta(hours=8))).strftime('%Y-%m-%dT%H:%M:%S')
        save(root, state)
        return dict(ok=True, replayed=False, **state)


def bind(root, cycle, task_id):
    """Persist a task ID only after the host creates AND reads back the real task."""
    if not task_id or len(task_id)>200: raise ValueError('native_task_id_required')
    with guard(root):
        state=read_json(state_path(root))
        if state.get('cycle')!=cycle: raise ValueError('stale_panel_cycle')
        if state.get('native_task') and state['native_task']!=task_id:
            raise ValueError('panel_cycle_already_bound')
        state.update(native_task=task_id, enabled=True,
                     status='published' if state.get('published_cycle')==cycle else 'scheduled')
        save(root, state)
        return dict(ok=True, **state)


def publish(root, target, cycle=None, manual=False):
    root=Path(root).resolve(); target=Path(target).absolute()
    if target.suffix.lower()!='.html' or target.is_symlink():
        raise ValueError('explicit_regular_html_target_required')
    with guard(root):
        state=read_json(state_path(root)); now=time.time()
        if not manual:
            if cycle!=state.get('cycle') or not cycle:
                return dict(ok=True, skipped='stale_or_missing_cycle')
            if state.get('published_cycle')==cycle:
                return dict(ok=True, replayed=True, snapshot_at=state.get('generated_at'))
            if now<state.get('due_at', math.inf):
                return dict(ok=True, waiting=True, due_at=state.get('due_at'), at_local=state.get('at_local'))
        if target.exists() and 'id="snapshot"' not in target.read_text(encoding='utf-8'):
            raise ValueError('refuse_overwriting_unrelated_html')
        from brain import Brain
        b=Brain(root)
        try: result=b.dispatch({'op':'companion_panel'})
        finally: b.close()
        if not result.get('ok'): return result
        content=Path(result['path']).read_bytes()
        atomic(target, content)
        state.update(generated_at=result['snapshot_at'], target_sha256=hashlib.sha256(content).hexdigest(),
                     status='published', last_publish_kind='manual' if manual else 'after_source_completion')
        if cycle: state['published_cycle']=cycle
        if state.get('due_at'):
            state['next_at']=state['due_at']+1800 if now>=state['due_at'] else state['due_at']
            state['next_estimated']=now>=state['due_at']
        save(root, state)
        return dict(ok=True, path=str(target), snapshot_at=result['snapshot_at'],
                    sha256=state['target_sha256'], notifications=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    subs=parser.add_subparsers(dest='action', required=True)
    mark=subs.add_parser('record'); mark.add_argument('--cycle', required=True); mark.add_argument('--source-task', required=True)
    mark.add_argument('--completed-at', type=float, help='Only a verified native success timestamp; never infer from chat text')
    attach=subs.add_parser('bind'); attach.add_argument('--cycle', required=True); attach.add_argument('--task-id', required=True)
    push=subs.add_parser('publish'); push.add_argument('--target', type=Path, required=True); push.add_argument('--cycle'); push.add_argument('--manual', action='store_true')
    args=parser.parse_args()
    if args.action=='record': result=record(args.root, args.cycle, args.source_task,args.completed_at)
    elif args.action=='bind': result=bind(args.root, args.cycle, args.task_id)
    else: result=publish(args.root, args.target, args.cycle, args.manual)
    print(json.dumps(result, ensure_ascii=False))


if __name__=='__main__': main()
