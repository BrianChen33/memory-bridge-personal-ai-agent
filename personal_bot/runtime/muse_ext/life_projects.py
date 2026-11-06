"""Model-authored virtual projects. Future drafts remain outside source/recall tables."""
import hashlib
import json
import math
from contextlib import contextmanager
from functools import wraps

from muse_ext import companion as c


@contextmanager
def _lock(b):
    # _life_event commits its own source capture; keep mutations serialized across those commits.
    path = b.root / 'state' / 'companion-projects.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        try:
            import fcntl
        except ImportError:
            import msvcrt
            if not path.stat().st_size:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('activity_project_busy') from exc
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError('activity_project_busy') from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _serialized(operation):
    @wraps(operation)
    def run(b, *args, **kwargs):
        with _lock(b):
            return operation(b, *args, **kwargs)
    return run


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS ct_activity_project(
      id TEXT PRIMARY KEY,activity TEXT NOT NULL,origin TEXT NOT NULL,
      started REAL NOT NULL,ends REAL NOT NULL,status TEXT NOT NULL DEFAULT 'awaiting_plan',
      version INTEGER NOT NULL DEFAULT 0,topic TEXT NOT NULL DEFAULT '',paused REAL,reason TEXT);
    CREATE TABLE IF NOT EXISTS ct_activity_plan(
      project TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL,
      PRIMARY KEY(project,version));
    CREATE TABLE IF NOT EXISTS ct_activity_stage(
      project TEXT NOT NULL,version INTEGER NOT NULL,position INTEGER NOT NULL,due REAL NOT NULL,
      description TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'sealed',event TEXT,
      PRIMARY KEY(project,version,position));
    CREATE INDEX IF NOT EXISTS ct_activity_due ON ct_activity_stage(project,version,state,due);
    ''')


def _number(value, lo, hi):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi or not math.isfinite(value):
        raise ValueError('invalid_activity_number')
    return float(value)


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid_activity_text')
    return value


def _row(b, project_id):
    _text(project_id, 128)
    row = b.db.execute('SELECT * FROM ct_activity_project WHERE id=?', (project_id,)).fetchone()
    if not row:
        raise ValueError('activity_project_not_found')
    return row


@_serialized
def register(b, current):
    """Bind a legacy-shaped selected activity; return its stable started ct_life id."""
    if not isinstance(current, dict) or current.get('origin') != 'virtual' or current.get('phone_intent'):
        raise ValueError('virtual_non_phone_activity_required')
    activity = _text(current.get('name'), 80)
    if activity in ('真实阅读', '梦境', '刷手机'):
        raise ValueError('virtual_non_phone_activity_required')
    start = _number(current.get('started_at'), 0, 1e13)
    end = _number(current.get('ends_at'), start + 1, start + 86400)
    pid = current.get('project_id') or hashlib.sha256(c.dump([activity, start, end]).encode()).hexdigest()[:32]
    _text(pid, 128)
    with b.db:
        b.db.execute('INSERT OR IGNORE INTO ct_activity_project(id,activity,origin,started,ends) VALUES(?,?,?,?,?)',
                     (pid, activity, 'virtual', start, end))
        previous = _row(b, pid)
        if (previous['activity'], previous['origin'], previous['started']) != (activity, 'virtual', start):
            raise ValueError('activity_project_identity_conflict')
    current['project_id'] = pid
    current.pop('outcome', None)
    current['ends_at'] = previous['ends']
    return c._life_event(b, activity, 'started', '开始' + activity + '。',
                         origin='virtual', occurred=start, event_id=pid)


def _current_id(b):
    activity = c._get(b, 'life', {}).get('activity') or {}
    return activity.get('project_id') if not activity.get('phone_intent') else None


def view(b, project_id=None):
    """Bounded read-only projection. Due stages are visible; originals/artifacts never are."""
    pid = project_id or _current_id(b)
    if not pid:
        return None
    row = _row(b, pid)
    where = "project=? AND (state='revealed' OR (version=? AND state='sealed' AND due<=? AND ?='active'))"
    args = (pid, row['version'], c.stamp(), row['status'])
    visible = b.db.execute('SELECT * FROM ct_activity_stage WHERE ' + where +
                           ' ORDER BY due DESC,version DESC,position DESC LIMIT 3', args).fetchall()
    count = b.db.execute('SELECT count(*) FROM ct_activity_stage WHERE ' + where, args).fetchone()[0]
    result = dict(project_id=pid, activity=row['activity'], name=row['activity'], origin='virtual', status=row['status'],
                  version=row['version'], topic=row['topic'], started_at=row['started'], ends_at=row['ends'],
                  visible_count=count, visible_stages=[], artifact_ready=row['status'] == 'completed')
    for stage in visible:
        item = dict(version=stage['version'], index=stage['position'], occurred_at=stage['due'],
                    description=stage['description'][:240])
        result['visible_stages'].insert(0, item)
        excess = len(c.dump(result)) - 1050
        if excess > 0:
            item['description'] = item['description'][:max(0, len(item['description']) - excess)]
            if len(c.dump(result)) > 1050:
                result['visible_stages'].pop(0)
    return result


def _advance_project(b, pid, now):
    row = _row(b, pid)
    created = []
    if row['status'] == 'active':
        stages = b.db.execute("SELECT * FROM ct_activity_stage WHERE project=? AND version=? AND state='sealed' "
                              "AND due<=? ORDER BY position", (pid, row['version'], now)).fetchall()
        final = b.db.execute('SELECT max(position) FROM ct_activity_stage WHERE project=? AND version=?',
                             (pid, row['version'])).fetchone()[0]
        for stage in stages:
            current = _row(b, pid)
            if current['status'] != 'active' or current['version'] != row['version']:
                break
            eid = 'activity:' + pid + ':v' + str(stage['version']) + ':' + str(stage['position'])
            event = c._life_event(b, row['activity'], 'completed' if stage['position'] == final else 'progress',
                                  stage['description'], origin='virtual', occurred=stage['due'], event_id=eid)
            if not event:
                break
            with b.db:
                b.db.execute("UPDATE ct_activity_stage SET state='revealed',event=? WHERE project=? AND version=? AND position=? AND state='sealed'",
                             (event, pid, stage['version'], stage['position']))
            created.append(event)
        pending = b.db.execute("SELECT count(*) FROM ct_activity_stage WHERE project=? AND version=? AND state='sealed'",
                               (pid, row['version'])).fetchone()[0]
        if final is not None and not pending and now >= row['ends']:
            with b.db:
                b.db.execute("UPDATE ct_activity_project SET status='completed' WHERE id=? AND version=? AND status='active'",
                             (pid, row['version']))
    row = _row(b, pid)
    return dict(created=created, completed=row['status'] == 'completed', project_id=pid, status=row['status'])


@_serialized
def advance(b, now):
    """Materialize due canonical events. An unplanned or paused project never finishes."""
    now = _number(now, 0, 1e13)
    pid = _current_id(b)
    return _advance_project(b, pid, now) if pid else dict(created=[], completed=False, project_id=None, status='none')


def _validate_plan(plan, activity):
    if not isinstance(plan, dict) or set(plan) != {'version', 'origin', 'activity', 'topic', 'stages', 'artifact'}:
        raise ValueError('activity_plan_fields_required')
    if type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('activity_plan_version_1_required')
    if plan['origin'] != 'virtual' or plan['activity'] != activity:
        raise ValueError('activity_plan_identity_conflict')
    _text(plan['topic'], 160)
    stages = plan['stages']
    if not isinstance(stages, list) or not 2 <= len(stages) <= 6:
        raise ValueError('activity_2_to_6_stages_required')
    previous = 0
    for stage in stages:
        if not isinstance(stage, dict) or set(stage) != {'after_seconds', 'description'}:
            raise ValueError('activity_stage_fields_required')
        after = _number(stage['after_seconds'], 1, 21600)
        if after <= previous:
            raise ValueError('activity_stage_times_must_increase')
        previous = after
        _text(stage['description'], 1800)
    artifact = plan['artifact']
    if not isinstance(artifact, dict) or set(artifact) != {'title', 'text'}:
        raise ValueError('activity_native_artifact_required')
    _text(artifact['title'], 160)
    _text(artifact['text'], 24000)
    return c.dump(plan)


def _version(q):
    value = q.get('expected_version')
    if type(value) is not int or not 0 <= value <= 1000000:
        raise ValueError('activity_expected_version_required')
    return value


def _save_plan(b, q, action, now):
    pid = _text(q.get('project_id'), 128)
    expected = _version(q)
    plan = q.get('plan')
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        row = _row(b, pid)
        payload = _validate_plan(plan, row['activity'])
        old = b.db.execute('SELECT payload FROM ct_activity_plan WHERE project=? AND version=?', (pid, expected + 1)).fetchone()
        if old:
            if old[0] != payload:
                raise ValueError('activity_plan_content_conflict')
            replayed = True
        else:
            if expected != row['version'] or (action == 'plan' and (expected != 0 or row['status'] not in ('awaiting_plan', 'paused'))):
                raise ValueError('activity_plan_version_conflict')
            if action == 'revise' and row['status'] != 'paused':
                raise ValueError('activity_pause_before_revision_required')
            version, end = expected + 1, now + plan['stages'][-1]['after_seconds']
            b.db.execute('INSERT INTO ct_activity_plan VALUES(?,?,?,?)', (pid, version, payload, now))
            b.db.execute("UPDATE ct_activity_stage SET state='superseded' WHERE project=? AND state='sealed'", (pid,))
            b.db.executemany('INSERT INTO ct_activity_stage(project,version,position,due,description) VALUES(?,?,?,?,?)',
                             [(pid, version, i, now + s['after_seconds'], s['description']) for i, s in enumerate(plan['stages'], 1)])
            b.db.execute("UPDATE ct_activity_project SET status='active',version=?,topic=?,ends=?,paused=NULL,reason=NULL WHERE id=?",
                         (version, plan['topic'], end, pid))
            life = c._get(b, 'life', {})
            if (life.get('activity') or {}).get('project_id') == pid:
                life['activity']['ends_at'] = end
                c._set(b, 'life', life)
            replayed = False
    return dict(ok=True, replayed=replayed, project=view(b, pid))


@_serialized
def dispatch(b, q):
    if q.get('scope', 'owner-private') != 'owner-private':
        raise ValueError('companion_owner_scope_required')
    action, now = q.get('action', 'view'), c.stamp()
    if action == 'pending':
        pid = _current_id(b)
        project = view(b, pid) if pid else None
        return dict(ok=True, projects=[project] if project and project['status'] in ('awaiting_plan', 'paused') else [],
                    author='same_host_reply_model', schema_version=1, stages_min=2, stages_max=6,
                    stage_fields=['after_seconds', 'description'], stage_seconds_bounds=[1, 21600],
                    plan_fields=['version', 'origin', 'activity', 'topic', 'stages', 'artifact'],
                    artifact_fields=['title', 'text'],
                    policy='Model supplies concrete virtual topic, process and native artifact. Offsets begin at acceptance. '
                           'Future drafts are sealed; no observed web reading or factual learning may be invented. '
                           'Use expected_version and pause before revising only the future. No extra model or timer.')
    if action == 'view':
        return dict(ok=True, project=view(b, q.get('project_id')))
    if action in ('plan', 'revise'):
        return _save_plan(b, q, action, now)
    pid = _text(q.get('project_id'), 128)
    if action == 'artifact':
        _advance_project(b, pid, now)
        row = _row(b, pid)
        if row['status'] != 'completed' or now < row['ends']:
            return dict(ok=True, ready=False, project=view(b, pid))
        stored = b.db.execute('SELECT payload FROM ct_activity_plan WHERE project=? AND version=?', (pid, row['version'])).fetchone()
        return dict(ok=True, ready=True, project_id=pid, version=row['version'], origin='virtual',
                    artifact=json.loads(stored[0])['artifact'])
    if action == 'interrupt':
        expected = _version(q)
        _advance_project(b, pid, now)
        with b.db:
            b.db.execute('BEGIN IMMEDIATE')
            row = _row(b, pid)
            if row['version'] != expected or row['status'] not in ('active', 'paused', 'awaiting_plan'):
                raise ValueError('active_activity_version_required')
            replayed = row['status'] == 'paused'
            if not replayed:
                if b.db.execute("SELECT 1 FROM ct_activity_stage WHERE project=? AND version=? AND state='sealed' AND due<=?",
                                 (pid, expected, now)).fetchone():
                    raise ValueError('activity_due_events_not_recorded')
                reason = _text(q.get('reason', '暂停当前虚拟活动'), 300)
                b.db.execute("UPDATE ct_activity_project SET status='paused',paused=?,reason=? WHERE id=?", (now, reason, pid))
        return dict(ok=True, replayed=replayed, project=view(b, pid))
    raise ValueError('unknown_activity_action')
