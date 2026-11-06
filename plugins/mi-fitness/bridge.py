"""Restricted worker. No raw endpoint, independent vitals, GPS or public server."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from datetime import datetime, timedelta, timezone

ALLOWED = ('sleep', 'steps', 'activity_daily', 'workouts')
TZ = timezone(timedelta(hours=8))
GUIDANCE = ('Owner sleep/activity only, not your own energy/mood or a new repeated emotional stimulus. '
            'Use when relevant; missing is unknown, cloud data can lag; no diagnosis, shared-channel '
            'disclosure or bulk memory import. Raw stores/credentials never enter backups; owner-approved '
            'conversational summaries follow normal private chat memory and backup.')


def day_at(now):
    return datetime.fromtimestamp(now, TZ).date()


def private_root(value):
    path = Path(value).expanduser().absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('health_symlink_refused')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError('health_directory_not_private')
    return path


def atomic(path, value):
    temp = path.with_name(path.name + '.tmp')
    if path.is_symlink() or temp.is_symlink():
        raise ValueError('health_symlink_refused')
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    os.replace(temp, path)


def database(root):
    path = root / 'health.sqlite'
    if path.is_symlink():
        raise ValueError('health_symlink_refused')
    db = sqlite3.connect(path, timeout=5)
    db.row_factory = sqlite3.Row
    os.chmod(path, 0o600)
    db.executescript('''CREATE TABLE IF NOT EXISTS state(k TEXT PRIMARY KEY,v TEXT);
      CREATE TABLE IF NOT EXISTS daily(metric TEXT,day TEXT,payload TEXT,fetched REAL,
        PRIMARY KEY(metric,day));
      CREATE TABLE IF NOT EXISTS care(id TEXT PRIMARY KEY,payload TEXT,created REAL,
        status TEXT,lease REAL DEFAULT 0,receipt TEXT DEFAULT '');''')
    return db


def get(db, key, default=None):
    row = db.execute('SELECT v FROM state WHERE k=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(db, key, value):
    db.execute('INSERT OR REPLACE INTO state VALUES(?,?)', (key, json.dumps(value)))


def timestamp(value):
    return datetime.fromtimestamp(value, TZ).isoformat() if value is not None else None


def project(metric, item):
    if metric not in ALLOWED:
        raise ValueError('health_metric_not_allowed')
    # Enumerating fields is deliberate: dataclass/asdict and raw expose other vitals.
    if metric == 'sleep':
        return {'date': item.date, 'asleep_min': item.asleep_min,
                'deep_min': item.deep_min, 'light_min': item.light_min,
                'rem_min': item.rem_min, 'awake_min': item.awake_min,
                'sessions': [{'start': timestamp(s.start_epoch_s), 'end': timestamp(s.end_epoch_s),
                              'asleep_min': s.asleep_min} for s in item.sessions]}
    if metric == 'steps':
        return {'date': item.date, 'steps': item.steps, 'distance_m': item.distance_m}
    if metric == 'activity_daily':
        return {'date': item.date, 'activity_count': item.activity_count,
                'activity_min': item.activity_min, 'active_kcal': item.active_kcal}
    return {'date': day_at(item.start_epoch_s).isoformat(), 'start': timestamp(item.start_epoch_s),
            'end': timestamp(item.end_epoch_s), 'sport': item.sport,
            'duration_s': item.duration_s, 'distance_m': item.distance_m,
            'active_kcal': item.active_kcal, 'steps': item.steps}


def cached(db, days, now):
    if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
        raise ValueError('health_history_days_out_of_range')
    first = (day_at(now) - timedelta(days=days - 1)).isoformat()
    last = day_at(now).isoformat()
    rows = db.execute('SELECT metric,day,payload,fetched FROM daily WHERE day>=? AND day<=? ORDER BY day DESC,metric',
                      (first, last)).fetchall()
    return [{'metric': r['metric'], 'date': r['day'], 'records': json.loads(r['payload']),
             'fetched_at': r['fetched'], 'stale': now - r['fetched'] > 21600} for r in rows]


def care_rows(metric, record):
    if metric == 'sleep':
        return 'sleep:' + record['date'], {'kind': 'sleep', 'observation': record}
    if metric == 'workouts':
        return 'workout:' + record['start'] + ':' + str(record['sport']), {'kind': 'workout', 'observation': record}
    return None, None


def refresh_projection(db, root, now):
    rows = cached(db, 2, now)
    # One latest day per category, not an expanding diary in every reply.
    recent = {}
    stale_metrics = []
    for r in rows:
        metric = r['metric']
        if metric in recent:
            continue
        if r['stale']:
            stale_metrics.append(metric)
        records = r['records'][:2] if metric == 'workouts' else r['records'][:1]
        if metric == 'sleep':
            for record in records:
                record['sessions'] = record['sessions'][-2:]
        recent[metric] = records
    errors = get(db, 'last_error', {})
    value = {'schema': 'owner-sleep-activity-context-v1', 'status': 'partial' if errors else 'ready',
             'source': 'Mi Fitness cloud; observed owner data', 'scope': 'owner-private',
             'fetched_at': get(db, 'last_success', 0), 'unavailable': list(errors),
             'stale_metrics': sorted(set(stale_metrics) | set(errors)),
             'allowed': list(ALLOWED), 'recent': recent, 'guidance': GUIDANCE}
    atomic(root / 'context.json', value)


def sync(root, client=None, now=None):
    now = time.time() if now is None else now
    root = private_root(root)
    db = database(root)
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            last = get(db, 'last_attempt')
            if last is not None and now - last < 3600:
                return {'ok': True, 'status': 'cached', 'next_sync_at': last + 3600}
            put(db, 'last_attempt', now)
        baseline = get(db, 'initialized', False)
        if client is None:
            from mifit import MiFit
            from mifit.auth.session import load_session
            credential = root / 'session.json'
            if credential.is_symlink() or (os.name != 'nt' and credential.exists() and credential.stat().st_mode & 0o077):
                raise ValueError('health_credentials_not_private')
            session = load_session(credential)
            if not session:
                return {'ok': False, 'status': 'login_required'}
            client = MiFit(session=session)
        first = (day_at(now) - timedelta(days=2 if baseline else 6)).isoformat()
        last_day = day_at(now).isoformat()
        counts, errors = {}, {}
        for metric in ALLOWED:
            try:
                result = getattr(client, metric)(first, last_day)
                grouped = {}
                for item in result.records:
                    record = project(metric, item)
                    if not first <= record['date'] <= last_day:
                        continue
                    grouped.setdefault(record['date'], []).append(record)
                with db:
                    for day, values in grouped.items():
                        db.execute('INSERT OR REPLACE INTO daily VALUES(?,?,?,?)',
                                   (metric, day, json.dumps(values, ensure_ascii=False), now))
                        for record in values:
                            cid, payload = care_rows(metric, record)
                            if cid:
                                observed_end = (record['sessions'][-1]['end'] if metric == 'sleep' and record['sessions']
                                                else record.get('end') or record.get('start'))
                                recent = bool(observed_end and 0 <= now - datetime.fromisoformat(observed_end).timestamp() <= 86400)
                                db.execute('INSERT OR IGNORE INTO care(id,payload,created,status) VALUES(?,?,?,?)',
                                           (cid, json.dumps(payload, ensure_ascii=False), now,
                                            'pending' if baseline and recent else 'baseline'))
                    # Empty cloud responses stay missing, never a fabricated zero.
                    put(db, 'coverage:' + metric, {'from': first, 'to': last_day, 'record_count': len(result.records),
                                                  'at': now, 'notes': result.notes})
                counts[metric] = len(result.records)
            except Exception as exc:
                errors[metric] = type(exc).__name__  # No signed URLs, tokens, payloads or account IDs.
        with db:
            if counts:
                put(db, 'initialized', True)
                put(db, 'last_success', now)
            put(db, 'last_error', errors)
            cutoff = (day_at(now) - timedelta(days=89)).isoformat()
            db.execute('DELETE FROM daily WHERE day<?', (cutoff,))
            db.execute('DELETE FROM care WHERE created<? AND status!=?', (now - 90 * 86400, 'unknown'))
        # The explicit session is never saved by the upstream client itself.
        if getattr(client, 'session', None) is not None:
            from mifit.auth.session import save_session
            save_session(client.session, root / 'session.json')
        refresh_projection(db, root, now)
        return {'ok': not errors, 'status': 'partial' if errors else 'synced', 'counts': counts,
                'errors': errors, 'initial_baseline': not baseline, 'raw_values_emitted': False}
    finally:
        db.close()


def care_work(db, now):
    if 1 <= datetime.fromtimestamp(now, TZ).hour < 7:
        return {'ok': True, 'status': 'quiet_hours', 'candidates': []}
    with db:
        db.execute('BEGIN IMMEDIATE')
        # An interrupted/unknown delivery is not automatically resent.
        db.execute("UPDATE care SET status='unknown' WHERE status='claimed' AND lease<?", (now,))
        rows = db.execute("SELECT * FROM care WHERE status='pending' AND created>=? ORDER BY created LIMIT 2",
                          (now - 86400,)).fetchall()
        for row in rows:
            db.execute("UPDATE care SET status='claimed',lease=? WHERE id=? AND status='pending'", (now + 900, row['id']))
    return {'ok': True, 'candidates': [{'id': r['id'], **json.loads(r['payload'])} for r in rows],
            'instruction': 'Same current life-task model may naturally share or suppress. Owner-private only; '
                           'use existing proactive/sticker/send receipt flow. Never diagnose or force a message.'}


def settle(db, candidate, outcome, receipt):
    if outcome not in ('delivered', 'suppressed', 'unknown') or (outcome == 'delivered' and not receipt.strip()):
        raise ValueError('real_delivery_receipt_required')
    row = db.execute('SELECT status FROM care WHERE id=?', (candidate,)).fetchone()
    if not row:
        raise ValueError('health_candidate_not_found')
    if row['status'] != 'claimed':
        return {'ok': row['status'] == outcome, 'status': row['status'], 'replayed': True}
    with db:
        db.execute('UPDATE care SET status=?,receipt=? WHERE id=?', (outcome, receipt[:400], candidate))
    return {'ok': True, 'status': outcome}


def main():
    # mifit interprets day strings in process-local time; the cloud VM may be UTC.
    os.environ['TZ'] = 'Asia/Shanghai'
    if hasattr(time, 'tzset'):
        time.tzset()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-dir', required=True)
    parser.add_argument('--scope', required=True, choices=['owner-private'])
    parser.add_argument('action', choices=['status', 'sync', 'history', 'care_work', 'care_settle', 'import'])
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--candidate', default='')
    parser.add_argument('--outcome', default='')
    parser.add_argument('--receipt', default='')
    parser.add_argument('--envelope')
    parser.add_argument('--key')
    parser.add_argument('--transfer-id')
    parser.add_argument('--fingerprint')
    args = parser.parse_args()
    root = private_root(args.private_dir)
    if args.action == 'import':
        from handoff import import_envelope
        return import_envelope(root, args.envelope, args.key, args.transfer_id, args.fingerprint)
    if args.action == 'sync':
        return sync(root)
    db = database(root)
    try:
        if args.action == 'history':
            return {'ok': True, 'source': 'Mi Fitness cloud cache', 'scope': 'owner-private',
                    'rows': cached(db, args.days, time.time()), 'last_error': get(db, 'last_error', {})}
        if args.action == 'care_work':
            return care_work(db, time.time())
        if args.action == 'care_settle':
            return settle(db, args.candidate, args.outcome, args.receipt)
        return {'ok': True, 'allowed': list(ALLOWED), 'credentials_present': (root / 'session.json').is_file(),
                'last_success': get(db, 'last_success'), 'last_error': get(db, 'last_error', {})}
    finally:
        db.close()


if __name__ == '__main__':
    try:
        print(json.dumps(main(), ensure_ascii=False, allow_nan=False))
    except Exception as exc:
        print(json.dumps({'ok': False, 'status': 'worker_error', 'error_type': type(exc).__name__}))
        raise SystemExit(1) from None
