"""Small SQLite camera ledger, sharing the companion's consistent backup."""
import json
import math

DEFAULTS = dict(automatic=True, mode='balanced', cooldown_minutes=30,
                camera_preference='auto', character_id='', max_references=4)


def now():
    from muse_ext.companion import stamp
    return stamp()


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS lc_asset(
      category TEXT NOT NULL,id TEXT NOT NULL,payload TEXT NOT NULL,
      PRIMARY KEY(category,id));
    CREATE TABLE IF NOT EXISTS lc_job(
      id TEXT PRIMARY KEY,binding TEXT NOT NULL UNIQUE,life_id TEXT,
      manual INTEGER NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
      updated REAL NOT NULL,expires REAL,plan TEXT NOT NULL,
      generation TEXT NOT NULL DEFAULT '{}',delivery TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX IF NOT EXISTS lc_job_queue ON lc_job(status,manual,created);
    ''')


def settings(b):
    from muse_ext.companion import _get
    return {**DEFAULTS, **_get(b, 'life_camera_settings', {})}


def configure(b, q):
    from muse_ext.companion import _set
    patch = q.get('patch')
    if q.get('authorized') is not True or not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError('authorized_camera_settings_required')
    current = {**settings(b), **patch}
    interval = current['cooldown_minutes']
    if (type(current['automatic']) is not bool or
            type(interval) not in (int, float) or not math.isfinite(interval) or not 0 <= interval <= 240 or
            current['mode'] not in ('manual', 'balanced', 'proactive') or
            current['camera_preference'] not in ('auto', 'selfie', 'rear', 'mirror') or
            type(current['max_references']) is not int or not 2 <= current['max_references'] <= 8 or
            not isinstance(current['character_id'], str) or len(current['character_id']) > 80):
        raise ValueError('invalid_camera_settings')
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        current = {**settings(b), **patch}
        _set(b, 'life_camera_settings', current)
    return dict(ok=True, settings=current)


def host_binding(b):
    from muse_ext.companion import _get
    value = _get(b, 'life_camera_host', {})
    return value if value.get('host_identity') == host_identity(b) else {}


def host_identity(b):
    import hashlib
    import socket
    return hashlib.sha256((socket.gethostname() + '\n' + str(b.root.resolve())).encode()).hexdigest()


def bind_host(b, q):
    from muse_ext.companion import _set
    value = q.get('binding')
    if q.get('authorized') is not True or not isinstance(value, dict):
        raise ValueError('verified_camera_host_binding_required')
    fields = ('image_tool', 'background_runner', 'delivery_route', 'receipt')
    if (set(value) != set(fields) | {'reference_images', 'separate_delivery'} or
            any(not isinstance(value.get(key), str) or not value[key].strip() or len(value[key]) > 500 for key in fields) or
            value.get('reference_images') is not True or value.get('separate_delivery') is not True):
        raise ValueError('verified_camera_host_binding_required')
    value = {**value, 'verified_at': now(), 'host_identity': host_identity(b)}
    with b.db:
        _set(b, 'life_camera_host', value)
    return dict(ok=True, bound=True)


def get_job(b, identity):
    row = b.db.execute('SELECT * FROM lc_job WHERE id=?', (identity,)).fetchone()
    if not row:
        raise ValueError('camera_job_not_found')
    return row


def public_job(row):
    plan = json.loads(row['plan'])
    return dict(id=row['id'], status=row['status'], manual=bool(row['manual']),
                created=row['created'], updated=row['updated'], camera=plan['camera'],
                caption=plan['caption'], life_id=row['life_id'])


def quiet():
    from datetime import datetime, timezone, timedelta
    return 1 <= datetime.fromtimestamp(now(), timezone(timedelta(hours=8))).hour < 7


def scene_expiry(occurred):
    from datetime import datetime, timezone, timedelta
    released = datetime.fromtimestamp(occurred, timezone(timedelta(hours=8)))
    if 1 <= released.hour < 7:
        return released.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()
    return occurred + 2 * 3600


def cooldown(b):
    from muse_ext.companion import _get
    last = _get(b, 'life_camera_last_photo', {}).get('at')
    return max(0, last + settings(b)['cooldown_minutes'] * 60 - now()) if last else 0


def status(b):
    counts = dict(b.db.execute('SELECT status,count(*) FROM lc_job GROUP BY status'))
    recent = [public_job(row) for row in b.db.execute('SELECT * FROM lc_job ORDER BY created DESC,rowid DESC LIMIT 8')]
    return dict(ok=True, settings=settings(b), counts=counts, recent=recent,
                quiet=quiet(), cooldown_seconds=round(cooldown(b)),
                backend='host-native', background_binding_required=True)
