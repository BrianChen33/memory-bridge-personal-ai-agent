"""Native-scheduler outbox with deterministic IDs and due-time handoff fencing.

This module does not create native jobs or send messages. Muse's native tools
reconcile the outbox; unknown handoff is terminal without a delivery callback.
"""
import argparse
import hashlib
import json
import math
import time
import uuid
from datetime import datetime, timedelta

from .temporal import BJ, parse_due


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS reminders(
      id TEXT PRIMARY KEY,scope TEXT NOT NULL,source TEXT NOT NULL,event_id TEXT NOT NULL,
      request_text TEXT NOT NULL,request_hash TEXT NOT NULL,body TEXT NOT NULL,
      due_at REAL NOT NULL,wake_at REAL NOT NULL,quiet_override INTEGER NOT NULL,
      version INTEGER NOT NULL,status TEXT NOT NULL,native_job_id TEXT NOT NULL,
      attached INTEGER NOT NULL DEFAULT 0,lease TEXT,epoch INTEGER,claimed_at REAL,
      handoff_at REAL,created_at REAL NOT NULL,updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS reminder_retired_jobs(
      native_job_id TEXT PRIMARY KEY,reminder_id TEXT NOT NULL,disabled INTEGER NOT NULL DEFAULT 0);
    ''')


def _wake(brain, due, override):
    from proactive import load_policy, validate_policy
    policy = load_policy(brain.root)
    validate_policy(policy)
    # Quiet policy timezone is validated and this implementation is Beijing only.
    if policy.get('timezone') != 'Asia/Shanghai':
        raise ValueError('reminder_timezone_unsupported')
    local = datetime.fromtimestamp(due, BJ)
    def minute(value):
        return int(value[:2])*60+int(value[3:])
    start, end = minute(policy['quiet_start']), minute(policy['quiet_end'])
    current = local.hour*60+local.minute
    quiet = (start <= current < end) if start < end else (current >= start or current < end)
    if start == end:
        quiet = False
    if not quiet or override:
        return due
    until = local.replace(hour=end//60, minute=end%60, second=0, microsecond=0)
    if until.timestamp() <= due:
        until += timedelta(days=1)
    return until.timestamp()


def _public(row):
    d = dict(row)
    d['native_at'] = datetime.fromtimestamp(d['wake_at'], BJ).strftime('%Y-%m-%dT%H:%M')
    d['timezone'] = 'Asia/Shanghai'
    return d


def dispatch(brain, q):
    if q['scope'] != 'owner-private':
        raise ValueError('reminder_owner_only')
    initialize(brain.db)
    # Cancellation and reconciliation remain possible after a feature shutdown.
    if q.get('action') not in ('cancel','pending','ack_disabled') and not brain.feature('reminders'):
        return {'ok': False, 'disabled': True}
    from brain import config_guard
    with config_guard(brain.root), brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        return _dispatch_locked(brain, q)


def _dispatch_locked(brain, q):
    db, action, now = brain.db, q.get('action'), time.time()
    if action == 'pending':
        rows = db.execute("SELECT * FROM reminders WHERE status IN ('unscheduled','scheduled','claimed') ORDER BY due_at").fetchall()
        return {'ok':True, 'reminders':[_public(r) for r in rows],
                'disable_native_jobs':[r[0] for r in db.execute('SELECT native_job_id FROM reminder_retired_jobs WHERE disabled=0')]}
    if action == 'ack_disabled':
        job = q.get('native_job_id')
        if not isinstance(job, str):
            raise ValueError('invalid_native_job')
        db.execute('UPDATE reminder_retired_jobs SET disabled=1 WHERE native_job_id=?', (job,))
        return {'ok':True}
    if action == 'create':
        source, event = q.get('source'), q.get('event_id')
        if not isinstance(source,str) or not source or len(source)>1000 or not isinstance(event,str) or not event or len(event)>256:
            raise ValueError('reminder_source_required')
        body, text = q.get('body'), q.get('text')
        if not isinstance(body,str) or not body.strip() or len(body)>2400 or not isinstance(text,str) or len(text)>12000:
            raise ValueError('invalid_reminder_text')
        override = q.get('quiet_override', False)
        if not isinstance(override,bool) or (override and q.get('quiet_permission')!='explicit_user_request'):
            raise ValueError('explicit_quiet_permission_required')
        key = hashlib.sha256(json.dumps([q['scope'],source,event],ensure_ascii=False).encode()).hexdigest()[:32]
        fp = hashlib.sha256(json.dumps([text,body,override],ensure_ascii=False).encode()).hexdigest()
        old = db.execute('SELECT * FROM reminders WHERE id=?', (key,)).fetchone()
        if old:
            if old['request_hash'] != fp:
                raise ValueError('reminder_request_conflict')
            return {'ok':True, 'reminder':_public(old), 'replayed':True}
        parsed = parse_due(text, now)
        if not parsed['ok']:
            return parsed
        due = parsed['due_at']
        wake = _wake(brain, due, override)
        job = 'muse-reminder-'+key+'-v1'
        db.execute('''INSERT INTO reminders(id,scope,source,event_id,request_text,request_hash,
            body,due_at,wake_at,quiet_override,version,status,native_job_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,1,'unscheduled',?,?,?)''',
            (key,q['scope'],source,event,text,fp,body,due,wake,int(override),job,now,now))
        return {'ok':True, 'reminder':_public(db.execute('SELECT * FROM reminders WHERE id=?',(key,)).fetchone())}
    row = db.execute('SELECT * FROM reminders WHERE id=? AND scope=?', (q.get('id'),q['scope'])).fetchone()
    if not row:
        raise ValueError('reminder_not_found')
    if action == 'status':
        return {'ok':True, 'reminder':_public(row)}
    if action == 'cancel':
        db.execute('INSERT OR IGNORE INTO reminder_retired_jobs VALUES(?,?,0)', (row['native_job_id'],row['id']))
        # A handed-off final cannot be retracted; preserve honest terminal state.
        if row['status'] == 'unknown':
            return {'ok':False, 'reason':'already_handed_off', 'disable_native_job':row['native_job_id']}
        db.execute("UPDATE reminders SET status='cancelled',lease=NULL,version=version+1,updated_at=? WHERE id=?", (now,row['id']))
        return {'ok':True, 'disable_native_job':row['native_job_id']}
    if action == 'reschedule':
        if row['status'] in ('unknown','cancelled'):
            raise ValueError('reminder_terminal_create_new_request')
        parsed = parse_due(q.get('text'), now)
        if not parsed['ok']:
            return parsed
        version = row['version']+1
        due = parsed['due_at']
        wake = _wake(brain,due,bool(row['quiet_override']))
        db.execute('INSERT OR IGNORE INTO reminder_retired_jobs VALUES(?,?,0)', (row['native_job_id'],row['id']))
        db.execute('''UPDATE reminders SET request_text=?,due_at=?,wake_at=?,version=?,status='unscheduled',
            native_job_id=?,attached=0,lease=NULL,epoch=NULL,updated_at=? WHERE id=?''',
            (q['text'],due,wake,version,'muse-reminder-'+row['id']+'-v'+str(version),now,row['id']))
        return {'ok':True,'reminder':_public(db.execute('SELECT * FROM reminders WHERE id=?',(row['id'],)).fetchone())}
    if q.get('version') != row['version']:
        if action == 'attach':
            raise ValueError('stale_version')
        return {'ok':False,'reason':'stale_version'}
    if action == 'attach':
        if q.get('native_job_id') != row['native_job_id']:
            raise ValueError('native_job_mismatch')
        if row['status'] not in ('unscheduled','scheduled'):
            return {'ok':False,'reason':'not_schedulable'}
        db.execute("UPDATE reminders SET attached=1,status='scheduled',updated_at=? WHERE id=?", (now,row['id']))
        return {'ok':True}
    if action not in ('claim','authorize','handoff'):
        raise ValueError('invalid_reminder_action')
    if not brain.feature('reminders'):
        return {'ok':False,'disabled':True}
    if row['status'] in ('unknown','cancelled','unscheduled') or not row['attached']:
        return {'ok':False,'reason':'not_claimable'}
    if now < row['due_at']:
        return {'ok':False,'reason':'not_due','retry_at':row['due_at']}
    wake = _wake(brain, now, bool(row['quiet_override']))
    if wake > now:
        return {'ok':False,'reason':'quiet_hours','retry_at':wake}
    cfg = brain.config()
    if action == 'claim':
        if row['status']=='claimed' and now-(row['claimed_at'] or now)<300:
            return {'ok':False,'reason':'busy'}
        lease = uuid.uuid4().hex
        db.execute("UPDATE reminders SET status='claimed',lease=?,epoch=?,claimed_at=?,updated_at=? WHERE id=?",
                   (lease,cfg['epoch'],now,now,row['id']))
        return {'ok':True,'lease':lease,'epoch':cfg['epoch'],'version':row['version'],'due_at':row['due_at']}
    if (row['status']!='claimed' or not q.get('lease') or q.get('lease')!=row['lease'] or
        q.get('epoch')!=row['epoch'] or row['epoch']!=cfg['epoch'] or now-row['claimed_at']>=300):
        return {'ok':False,'reason':'invalid_lease_or_epoch'}
    if action == 'authorize':
        return {'ok':True,'authorized_at':now}
    db.execute("UPDATE reminders SET status='unknown',handoff_at=?,updated_at=? WHERE id=?",(now,now,row['id']))
    return {'ok':True,'status':'unknown','body':row['body'],'handoff_at':now,'due_at':row['due_at'],
            'meaning':'prepared_for_native_final_not_delivery_receipt'}


def wait_and_claim(brain, reminder_id, version, max_wait=900):
    """Actual system clock only. Each brief sleep rechecks cancellation/version."""
    deadline = time.monotonic()+max_wait
    while True:
        row = brain.db.execute('SELECT * FROM reminders WHERE id=?',(reminder_id,)).fetchone()
        if not row or row['version']!=version or row['status'] in ('unknown','cancelled') or not brain.feature('reminders'):
            return {'ok':False,'reason':'stopped'}
        delay = max(row['due_at'],row['wake_at'])-time.time()
        if delay <= 0:
            return dispatch(brain,dict(scope='owner-private',action='claim',id=reminder_id,version=version))
        if time.monotonic()+delay > deadline:
            return {'ok':False,'reason':'too_early','retry_at':max(row['due_at'],row['wake_at'])}
        time.sleep(min(1,delay))


def wait_and_handoff(brain, reminder_id, version, max_wait=900):
    claimed=wait_and_claim(brain,reminder_id,version,max_wait)
    if not claimed.get('ok'):
        return claimed
    q=dict(scope='owner-private',id=reminder_id,version=version,lease=claimed['lease'],epoch=claimed['epoch'])
    allowed=dispatch(brain,dict(q,action='authorize'))
    if not allowed.get('ok'):
        return allowed
    return dispatch(brain,dict(q,action='handoff'))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',required=True)
    parser.add_argument('--id',required=True)
    parser.add_argument('--version',required=True,type=int)
    parser.add_argument('--handoff',action='store_true')
    args=parser.parse_args()
    from brain import Brain
    brain=Brain(args.root)
    try:
        initialize(brain.db)
        operation=wait_and_handoff if args.handoff else wait_and_claim
        print(json.dumps(operation(brain,args.id,args.version),ensure_ascii=False))
    finally:
        brain.close()


if __name__=='__main__':
    main()
