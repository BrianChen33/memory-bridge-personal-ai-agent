"""Durable bounded reading. A queue is not permission, a browser, or a sender."""
import hashlib
import json
import math
import time
from contextlib import contextmanager
from datetime import datetime, timezone

from . import sources, store


@contextmanager
def serialized(b):
    """Short local mutations only. OS releases this lock on process exit."""
    path=b.root/'state'/'social-reading.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as handle:
        if __import__('os').name=='nt':
            import msvcrt
            if handle.tell()==0:
                handle.write(b'0');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            yield
        finally:
            if __import__('os').name=='nt':
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(handle,fcntl.LOCK_UN)


def require_document(b, document_id):
    """Recheck permission and queue eligibility immediately before new effects."""
    enabled(b)
    doc=b.db.execute('SELECT * FROM sr_document WHERE id=?',(document_id,)).fetchone()
    if not doc:
        raise ValueError('real_observed_document_required')
    sources.active(b,doc['source'])
    rows=list(b.db.execute('SELECT * FROM sr_read_queue WHERE document=?',(document_id,)))
    if rows:
        eligible=[row for row in rows if row['status'] in ('observed','done')]
        if not eligible:
            raise ValueError('reading_request_not_accepting_finalization')
        for row in eligible:
            source(b,row)
    return doc


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS sr_read_queue(
      id TEXT PRIMARY KEY,job TEXT UNIQUE,source TEXT,manual INTEGER,owner_event INTEGER,
      intent TEXT,status TEXT,lease TEXT,document TEXT,cursor TEXT,payload TEXT,
      created REAL,updated REAL,next_at REAL,attempts INTEGER DEFAULT 0,
      browser_task TEXT,receipt TEXT,staged TEXT,observed_at REAL,problem TEXT,
      schedule TEXT,worker TEXT,worker_until REAL DEFAULT 0);
    CREATE INDEX IF NOT EXISTS sr_read_queue_work ON sr_read_queue(status,next_at,manual,created);
    ''')


def enabled(b):
    if not b.available('input') or not b.available('memory') or not b.feature('reading'):
        raise ValueError('reading_disabled_by_core')


def get(b, q):
    row = b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (q.get('request_id'),)).fetchone()
    if not row:
        raise ValueError('real_reading_request_required')
    return row


def source(b, row):
    enabled(b)
    if not row['manual'] and not store.settings(b)['auto_browse']:
        raise ValueError('autonomous_reading_paused')
    return sources.active(b, row['source'])


def view(row):
    return {**{k: row[k] for k in ('id', 'source', 'manual', 'status', 'lease', 'document',
        'created', 'updated', 'next_at', 'attempts', 'browser_task', 'problem')},
        'cursor': json.loads(row['cursor'] or '{}'), 'schedule': json.loads(row['schedule'] or '{}')}


def enqueue(b, q):
    enabled(b)
    from . import reader
    intent, manual = q.get('life_intent'), q.get('manual') is True
    if intent and manual:
        raise ValueError('manual_and_life_intent_are_distinct')
    if not manual and not store.settings(b)['auto_browse']:
        return dict(ok=True, action='paused', queued=False)
    owner = sources.owner_event(b, q) if manual else None
    if not manual and not isinstance(intent, str):
        raise ValueError('real_owner_request_or_life_phone_intent_required')
    if intent:
        intent = sources.text(intent, 200, True)
        prior = b.db.execute('SELECT * FROM sr_read_queue WHERE intent=? ORDER BY created LIMIT 1', (intent,)).fetchone()
        if prior:
            source(b, prior)
            return dict(ok=True, queued=prior['status'] not in ('done', 'cancelled'), replayed=True, request=view(prior))
    allowed = list(b.db.execute("SELECT * FROM sr_source WHERE active=1 AND status='verified' ORDER BY last_read,verified_at"))
    selected = next((r for r in allowed if r['id'] == q.get('source_id')), None)
    if q.get('source_id') and not selected:
        raise ValueError('requested_source_not_allowed')
    selected = selected or (allowed[0] if allowed else None)
    if selected is None:
        return dict(ok=True, action='awaiting_sources', queued=False)
    target = q.get('target_url')
    if target is not None:
        reader.thread_url(target)  # Canonical validation; preserve a real page query.
        target = sources.text(target, 1600, True)
    if manual and not q.get('source_id'):
        prior = b.db.execute('SELECT * FROM sr_read_queue WHERE owner_event=? ORDER BY created LIMIT 1', (owner['id'],)).fetchone()
        if prior and json.loads(prior['payload'])['target_url'] == target:
            source(b, prior)
            return dict(ok=True, queued=prior['status'] not in ('done', 'cancelled'), replayed=True, request=view(prior))
    key = ('owner:' + str(owner['id']) if owner else 'life-phone:' + intent)
    payload = dict(source_id=selected['id'], target_url=target)
    rid = hashlib.sha256(dump([key, payload]).encode()).hexdigest()[:32]
    old = b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (rid,)).fetchone()
    if old:
        source(b, old)
        return dict(ok=True, queued=old['status'] not in ('done', 'cancelled'), replayed=True, request=view(old))
    if intent:
        from muse_ext import life_routine
        life_routine.require(b, intent)
    now = time.time()
    cursor = {}
    archived = (b.db.execute("SELECT * FROM sr_document WHERE source=? AND url=? ORDER BY created DESC LIMIT 1",
                (selected['id'], reader.thread_url(target))).fetchone() if target else None)
    if archived and archived['status'] == 'partial':
        data = json.loads(archived['payload'])
        cursor = dict(url=archived['url'], document_id=archived['id'], coverage=data.get('coverage', {}))
    with b.db:
        b.db.execute('''INSERT OR IGNORE INTO sr_read_queue
          (id,job,source,manual,owner_event,intent,status,cursor,payload,created,updated,next_at)
          VALUES(?,?,?,?,?,?,'queued',?,?,?,?,?)''',
          (rid, key + ':' + rid, selected['id'], int(manual), owner['id'] if owner else None,
           intent, dump(cursor), dump(payload), now, now, now))
    return dict(ok=True, queued=True, request=view(b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (rid,)).fetchone()),
        next='Reply to the owner after the normal full48/draw gate. A bounded background worker consumes this queue; do not browse in the emotion heartbeat.')


def status(b):
    counts = {r['status']: r['n'] for r in b.db.execute('SELECT status,count(*) n FROM sr_read_queue GROUP BY status')}
    rows = [view(r) for r in b.db.execute('SELECT * FROM sr_read_queue ORDER BY updated DESC LIMIT 12')]
    return dict(ok=True, counts=counts, requests=rows, concurrency=1,
        boundary='actual native browser and scheduler bindings remain host-owned; no page is read by a queue claim')


def work(b, q):
    enabled(b)
    from . import reader
    worker = sources.text(q.get('worker_id'), 200, True)
    now = time.time()
    # An overdue native task must be reconciled, not silently started a second time.
    active = b.db.execute("SELECT * FROM sr_read_queue WHERE status IN ('browsing','cancel_requested') ORDER BY created LIMIT 1").fetchone()
    if active:
        try:
            source(b, active)
        except ValueError:
            return dict(ok=True, action='confirm_browser_stop', request=view(active),
                        next='Source/core permission changed. Stop only this bound native browser, then queue_release; no new browsing.')
        lease = b.db.execute('SELECT * FROM sr_lease WHERE id=?', (active['lease'],)).fetchone()
        action = 'reconcile' if not lease or lease['deadline'] <= now or active['status'] == 'cancel_requested' else 'busy'
        return dict(ok=True, action=action, request=view(active),
            next='Query this exact native browser task. Stage its real result or release only after confirmed stop; never browse again to repair registration.')
    candidates = list(b.db.execute("SELECT * FROM sr_read_queue WHERE status IN ('staged','observed','ingesting') "
        'AND (worker_until<? OR worker=?) ORDER BY manual DESC,created LIMIT 1', (now, worker)))
    if candidates:
        item = candidates[0]
        try:
            source(b, item)
        except ValueError:
            with b.db:
                b.db.execute("UPDATE sr_read_queue SET status='paused',problem='source_unavailable',worker_until=0 WHERE id=?", (item['id'],))
            return dict(ok=True, action='paused', request_id=item['id'], reason='source_unavailable')
        with b.db:
            b.db.execute('UPDATE sr_read_queue SET worker=?,worker_until=? WHERE id=?', (worker, now+120, item['id']))
        return dict(ok=True, action='finalize' if item['status'] == 'observed' else 'ingest', request=view(item))
    item = b.db.execute("SELECT * FROM sr_read_queue WHERE status='queued' AND next_at<=? "
                        'ORDER BY manual DESC,created LIMIT 1', (now,)).fetchone()
    if not item:
        return dict(ok=True, action='idle')
    try:
        source(b, item)
    except ValueError:
        with b.db:
            b.db.execute("UPDATE sr_read_queue SET status='paused',problem='source_unavailable' WHERE id=?", (item['id'],))
        return dict(ok=True, action='paused', request_id=item['id'], reason='source_unavailable')
    if item['intent'] and not item['manual']:
        from muse_ext import life_routine
        phone = life_routine.pending(b)['request'] or {}
        if phone.get('id') != item['intent'] or phone.get('deadline', 0) <= now or phone.get('status') not in ('pending', 'claimed'):
            with b.db:
                b.db.execute("UPDATE sr_read_queue SET status='paused',problem='life_session_finished' WHERE id=?", (item['id'],))
            return dict(ok=True, action='paused', request_id=item['id'], reason='life_session_finished')
    # The existing lease transaction remains the one-browser arbiter, including
    # older clients. A busy result leaves the durable request untouched.
    claimed = reader._plan(b, dict(manual=bool(item['manual']), source_id=item['source'],
        job_id='queue:' + item['id'] + ':batch:' + str(item['attempts'])))
    if claimed.get('action') != 'browse':
        return dict(claimed, queued=True, request=view(item))
    lease_id = claimed['lease_id']
    with b.db:
        changed = b.db.execute("UPDATE sr_read_queue SET status='browsing',lease=?,browser_task=NULL,receipt=NULL,"
            "staged=NULL,observed_at=NULL,document=NULL,updated=?,attempts=attempts+1,worker=?,worker_until=?,problem='' "
            "WHERE id=? AND status='queued'", (lease_id, now, worker, now+120, item['id'])).rowcount
        if not changed:
            b.db.execute("UPDATE sr_lease SET status='released' WHERE id=? AND status='claimed'", (lease_id,))
            return dict(ok=True, action='busy', queued=True)
    item = b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (item['id'],)).fetchone()
    if item['intent']:
        from muse_ext import life_routine
        life_routine.mark(b, item['intent'], 'claimed', lease_id=lease_id, provider='tieba')
    policy = claimed['budget']
    target = json.loads(item['payload'])['target_url']
    resume = json.loads(item['cursor'] or '{}') or (None if target else claimed.get('resume'))
    return dict(claimed, request=view(item), resume=resume,
        target_url=json.loads(item['payload'])['target_url'],
        batch_budget=dict(max_pages=min(3, policy['max_pages']), target_seconds=min(180, policy['budget_seconds'])),
        next='Bind the real browser task ID immediately. Read only a bounded batch; stage its observed packet before reflection. Configured maximums are unchanged.')


def bind_browser(b, q):
    row = get(b, q)
    source(b, row)
    task = sources.text(q.get('browser_task_id'), 200, True)
    if row['status'] != 'browsing' or row['lease'] != q.get('lease_id'):
        raise ValueError('request_browser_lease_binding_required')
    if row['browser_task'] and row['browser_task'] != task:
        raise ValueError('reading_browser_task_conflict')
    with b.db:
        b.db.execute('UPDATE sr_read_queue SET browser_task=?,updated=? WHERE id=?', (task, time.time(), row['id']))
    return dict(ok=True, request_id=row['id'], browser_task_id=task)


def stage(b, q):
    from . import reader
    row = get(b, q)
    selected = source(b, row)
    if row['status'] in ('cancel_requested', 'cancelled', 'paused'):
        raise ValueError('reading_request_not_accepting_results')
    if (not row['browser_task'] or row['browser_task'] != q.get('browser_task_id') or
            row['lease'] != q.get('lease_id')):
        raise ValueError('request_browser_lease_binding_required')
    lease = b.db.execute('SELECT * FROM sr_lease WHERE id=?', (row['lease'],)).fetchone()
    if not lease or lease['source'] != row['source']:
        raise ValueError('bound_reading_lease_required')
    at = q.get('completed_at')
    now = time.time()
    if (isinstance(at, bool) or not isinstance(at, (int, float)) or not math.isfinite(at) or
            not lease['created'] <= at <= now+5):
        raise ValueError('actual_browser_completion_time_required')
    value = reader.normalize(q, selected, json.loads(lease['settings']))
    target = json.loads(row['payload'])['target_url']
    if target and value.get('url') and value['url'] != reader.thread_url(target):
        raise ValueError('reading_result_wrong_target')
    packet = dump(value)
    if row['staged']:
        if row['staged'] != packet or row['observed_at'] != at:
            raise ValueError('staged_reading_result_conflict')
        return dict(ok=True, replayed=True, request_id=row['id'], document_id=row['document'], staged=True)
    if row['status'] != 'browsing':
        raise ValueError('reading_request_not_browsing')
    if lease['status'] != 'claimed':
        raise ValueError('bound_reading_lease_already_consumed')
    with b.db:
        b.db.execute("UPDATE sr_read_queue SET status='staged',staged=?,observed_at=?,receipt=?,updated=?,"
            "worker_until=0,problem=? WHERE id=?", (packet, at, value['receipt'], now,
            'native_batch_overran_target' if at > lease['deadline'] else '', row['id']))
        b.db.execute("UPDATE sr_lease SET status=? WHERE id=?", ('staged:' + row['id'], lease['id']))
    return dict(ok=True, request_id=row['id'], staged=True, browsing_released=True,
        late=at > lease['deadline'], next='Ingest this stored packet; no new plan or browsing lease is needed.')


def ingest(b, q):
    from . import reader
    row = get(b, q)
    selected = source(b, row)
    if row['status'] in ('cancel_requested', 'cancelled', 'paused') or not row['staged']:
        raise ValueError('active_staged_reading_required')
    if row['document']:
        return dict(ok=True, replayed=True, request_id=row['id'], document_id=row['document'], action='finalize')
    now = time.time()
    with b.db:
        changed = b.db.execute("UPDATE sr_read_queue SET status='ingesting',updated=? WHERE id=? "
            "AND (status='staged' OR (status='ingesting' AND updated<?))", (now, row['id'], now-120)).rowcount
    if not changed:
        return dict(ok=True, action='busy', request_id=row['id'])
    lease = b.db.execute('SELECT * FROM sr_lease WHERE id=?', (row['lease'],)).fetchone()
    try:
        result = reader.persist_observation(b, lease, selected, json.loads(row['staged']), observed_at=row['observed_at'])
    except Exception:
        with b.db:
            b.db.execute("UPDATE sr_read_queue SET status='staged',problem='ingest_failed',worker_until=0 WHERE id=? AND status='ingesting'", (row['id'],))
        raise
    with b.db:
        b.db.execute("UPDATE sr_read_queue SET status=?,document=?,updated=?,worker_until=0 WHERE id=? AND status='ingesting'",
            ('observed' if result.get('document_id') else 'paused', result.get('document_id'), time.time(), row['id']))
    if row['intent'] and result.get('document_id'):
        from muse_ext import life_routine
        life_routine.mark(b, row['intent'], 'read', document_id=result['document_id'], source_event=result['source_event'])
    elif row['intent'] and result.get('reading_saved') is False:
        from muse_ext import life_routine
        life_routine.mark(b, row['intent'], 'blocked', reason=result.get('status'))
    return dict(result, request_id=row['id'], browsing_released=True)


def finish(b, q):
    from . import completion
    row = get(b, q)
    source(b, row)
    if row['status'] == 'done':
        return dict(ok=True, replayed=True, request=view(row))
    if row['status'] != 'observed' or not row['document']:
        raise ValueError('observed_reading_request_required')
    checked = completion(b, dict(document_id=row['document']))
    if not checked['complete']:
        return dict(checked, action='finalize', request_id=row['id'])
    doc = b.db.execute('SELECT * FROM sr_document WHERE id=?', (row['document'],)).fetchone()
    data = json.loads(doc['payload'])
    cursor = dict(url=doc['url'], document_id=doc['id'], coverage=data.get('coverage', {}))
    continuing = q.get('continue_reading') is True
    if continuing and not (doc['status'] == 'partial' and cursor['coverage'].get('next_url')):
        raise ValueError('observed_continuation_cursor_required')
    with b.db:
        b.db.execute('UPDATE sr_read_queue SET status=?,cursor=?,next_at=?,updated=?,worker_until=0 WHERE id=?',
            ('queued' if continuing else 'done', dump(cursor), time.time()+30, time.time(), row['id']))
    return dict(ok=True, request=view(b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (row['id'],)).fetchone()))


def release(b, q):
    row = get(b, q)
    reason = sources.text(q.get('reason'), 240, True)
    if row['status'] in ('done', 'paused', 'cancelled'):
        return dict(ok=True, replayed=True, request=view(row))
    if row['staged']:
        raise ValueError('staged_result_must_be_ingested_or_explicitly_cancelled')
    if row['browser_task']:
        if q.get('browser_stopped') is not True or q.get('browser_task_id') != row['browser_task']:
            return dict(ok=True, action='confirm_browser_stop', browser_task_id=row['browser_task'], request_id=row['id'])
        sources.text(q.get('stop_receipt'), 200, True)
    with b.db:
        b.db.execute("UPDATE sr_lease SET status='released' WHERE id=? AND status='claimed'", (row['lease'],))
        b.db.execute('UPDATE sr_read_queue SET status=?,problem=?,updated=?,worker_until=0 WHERE id=?',
            ('cancelled' if row['status'] == 'cancel_requested' else 'paused', reason, time.time(), row['id']))
    return dict(ok=True, released=True, request_id=row['id'], next='Paused work remains visible; never silently retry the browser.')


def cancel(b, q):
    sources.owner_event(b, q)
    row = get(b, q)
    if row['status'] in ('done', 'cancelled'):
        return dict(ok=True, replayed=True)
    pending_stop = row['status'] in ('browsing', 'cancel_requested') and bool(row['browser_task'])
    with b.db:
        b.db.execute('UPDATE sr_read_queue SET status=?,updated=?,worker_until=0 WHERE id=?',
            ('cancel_requested' if pending_stop else 'cancelled', time.time(), row['id']))
        if not pending_stop:
            b.db.execute("UPDATE sr_lease SET status='released' WHERE id=? AND status='claimed'", (row['lease'],))
    return dict(ok=True, action='stop_bound_browser' if pending_stop else 'cancelled',
                browser_task_id=row['browser_task'] if pending_stop else None, request_id=row['id'])


def resume(b, q):
    owner = sources.owner_event(b, q)
    row = get(b, q)
    enabled(b)
    sources.active(b, row['source'])
    if row['status'] != 'paused':
        raise ValueError('paused_reading_request_required')
    with b.db:
        b.db.execute('UPDATE sr_read_queue SET status=?,manual=1,owner_event=?,problem=?,next_at=?,updated=?,worker_until=0 WHERE id=?',
            ('staged' if row['staged'] else 'queued', owner['id'], '', time.time(), time.time(), row['id']))
    return dict(ok=True, request=view(b.db.execute('SELECT * FROM sr_read_queue WHERE id=?', (row['id'],)).fetchone()))


def handoff(b, q):
    """Generate a future plan, then verify the actual native scheduler read-back."""
    row = get(b, q)
    source(b, row)
    if row['status'] in ('done', 'cancelled', 'cancel_requested'):
        raise ValueError('active_reading_handoff_required')
    now = time.time()
    if q.get('native_task_id') is not None:
        saved = json.loads(row['schedule'] or '{}')
        actual = q.get('scheduled_for')
        task = sources.text(q.get('native_task_id'), 200, True)
        if saved.get('bound') and saved.get('native_task_id') != task:
            raise ValueError('native_reading_handoff_conflict')
        if (not saved or isinstance(actual, bool) or not isinstance(actual, (int, float)) or
                actual != saved.get('scheduled_for') or actual <= now):
            raise ValueError('future_native_schedule_readback_required')
        saved.update(native_task_id=task, bound=True)
    else:
        current = json.loads(row['schedule'] or '{}')
        if current.get('bound') and current.get('scheduled_for', 0) > now:
            return dict(ok=True, replayed=True, schedule=current)
        delay = q.get('delay_seconds', 60)
        if type(delay) is not int or not 30 <= delay <= 3600:
            raise ValueError('handoff_delay_30_to_3600_seconds_required')
        due = math.ceil(now+delay)
        saved = dict(scheduled_for=due, at_utc=datetime.fromtimestamp(due, timezone.utc).isoformat(),
            suggested_task_id='reading-' + row['id'][:20], bound=False)
    with b.db:
        b.db.execute('UPDATE sr_read_queue SET schedule=? WHERE id=?', (dump(saved), row['id']))
    return dict(ok=True, request_id=row['id'], schedule=saved,
        next='Use the real scheduler schema and read it back. An unbound plan is not a scheduled task; do not report a guessed time.')
