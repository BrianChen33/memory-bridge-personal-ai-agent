"""Private, bounded source records and model-derived speech habits."""
import hashlib
import json
import math
import time
from .sources import text, owner_event

DEFAULTS = dict(auto_browse=True, language_learning=True, share_threshold=70,
                max_threads=2, max_pages=3, budget_seconds=90, cache_ttl_seconds=600,
                sample_mode='dynamic', sample_min=50, sample_max=120,
                sample_fixed=50, sample_ratio=.2, max_text_chars=600)


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS sr_setting(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sr_source(id TEXT PRIMARY KEY,provider TEXT,name TEXT,url TEXT,
      owner_event INTEGER,active INTEGER,status TEXT,proof TEXT,created REAL,verified_at REAL,last_read REAL);
    CREATE TABLE IF NOT EXISTS sr_lease(id TEXT PRIMARY KEY,source TEXT,status TEXT,created REAL,
      deadline REAL,manual INTEGER,settings TEXT,job TEXT);
    CREATE TABLE IF NOT EXISTS sr_document(id TEXT PRIMARY KEY,source TEXT,url TEXT,title TEXT,
      fingerprint TEXT,payload TEXT,quote TEXT,event INTEGER,quote_id INTEGER,created REAL,last_seen REAL,status TEXT);
    CREATE INDEX IF NOT EXISTS sr_document_url ON sr_document(url,created);
    CREATE TABLE IF NOT EXISTS sr_reflection(document TEXT PRIMARY KEY,summary TEXT,note INTEGER,created REAL);
    CREATE TABLE IF NOT EXISTS sr_habit(id TEXT PRIMARY KEY,pattern TEXT,mechanism TEXT,example TEXT,
      status TEXT,positive INTEGER DEFAULT 0,negative INTEGER DEFAULT 0,updated REAL);
    CREATE TABLE IF NOT EXISTS sr_evidence(habit TEXT,url TEXT,document TEXT,quote TEXT,
      PRIMARY KEY(habit,url));
    CREATE TABLE IF NOT EXISTS sr_feedback(habit TEXT,event INTEGER,polarity TEXT,PRIMARY KEY(habit,event));
    ''')


def get(b, key, default=None):
    row = b.db.execute('SELECT value FROM sr_setting WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else default


def put(b, key, value):
    b.db.execute('INSERT OR REPLACE INTO sr_setting VALUES(?,?)', (key, json.dumps(value, ensure_ascii=False)))


def settings(b):
    return dict(DEFAULTS, **get(b, 'policy', {}))


def configure(b, q):
    owner_event(b, q)
    patch = q.get('patch')
    if not isinstance(patch, dict) or set(patch) - set(DEFAULTS):
        raise ValueError('unknown_social_reading_setting')
    limits = dict(share_threshold=(0, 100), max_threads=(1, 5), max_pages=(1, 30),
                  budget_seconds=(15, 180), cache_ttl_seconds=(60, 3600),
                  sample_min=(1, 120), sample_max=(1, 300), sample_fixed=(1, 300),
                  sample_ratio=(.01, 1), max_text_chars=(80, 3000))
    for key, value in patch.items():
        if key in ('auto_browse', 'language_learning'):
            if type(value) is not bool:
                raise ValueError('boolean_setting_required')
        elif key == 'sample_mode':
            if value not in ('dynamic', 'fixed', 'ratio', 'all'):
                raise ValueError('invalid_sample_mode')
        elif (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or
              not limits[key][0] <= value <= limits[key][1] or
              (key not in ('sample_ratio',) and type(value) is not int)):
            raise ValueError('invalid_social_reading_setting')
    result = dict(settings(b), **patch)
    if result['sample_min'] > result['sample_max']:
        raise ValueError('sample_min_exceeds_max')
    with b.db:
        put(b, 'policy', result)
    return dict(ok=True, settings=result)


def habit_rows(b):
    return [dict(r) for r in b.db.execute('''SELECT h.*,count(e.url) exposures FROM sr_habit h
      LEFT JOIN sr_evidence e ON e.habit=h.id GROUP BY h.id ORDER BY h.updated DESC LIMIT 40''')]


def reflect(b, q):
    doc = b.db.execute('SELECT * FROM sr_document WHERE id=?', (q.get('document_id'),)).fetchone()
    if not doc or not doc['event']:
        raise ValueError('real_observed_document_required')
    event = b.db.execute("SELECT id FROM source_events WHERE id=? AND actor='article' AND status='active'",
                         (doc['event'],)).fetchone()
    if not event:
        raise ValueError('reading_source_inactive')
    old = b.db.execute('SELECT * FROM sr_reflection WHERE document=?', (doc['id'],)).fetchone()
    if old:
        return dict(ok=True, replayed=True, reflection=dict(old))
    summary = text(q.get('summary'), 1200, True)
    candidates = q.get('style_candidates', [])
    if not isinstance(candidates, list) or len(candidates) > 3:
        raise ValueError('at_most_three_style_candidates')
    if not settings(b)['language_learning']:
        candidates = []
    checked = []
    for item in candidates:
        if not isinstance(item, dict):
            raise ValueError('style_candidate_object_required')
        pattern = text(item.get('pattern'), 140, True)
        mechanism = text(item.get('mechanism'), 200, True)
        example = text(item.get('example'), 100, True)
        evidence = text(item.get('evidence_quote'), 240, True)
        if evidence not in doc['quote']:
            raise ValueError('style_evidence_not_in_observed_text')
        hid = item.get('existing_id') or hashlib.sha256(pattern.casefold().encode()).hexdigest()[:24]
        if item.get('existing_id') and not b.db.execute('SELECT 1 FROM sr_habit WHERE id=?', (hid,)).fetchone():
            raise ValueError('existing_habit_not_found')
        checked.append((hid, pattern, mechanism, example, evidence))
    note = b._remember(dict(scope='owner-private', kind='reflection', evidence='inference',
                            source='assistant:social-reading:' + doc['id'], event_id='social-reflect:' + doc['id'],
                            occurred_at=time.time(), text=summary, importance=.45))
    from muse_ext.insights import initialize as init_insights, link
    init_insights(b.db)
    with b.db:
        link(b, note, 'owner-private', [doc['quote_id']], 'social-reading:' + doc['id'])
        for hid, pattern, mechanism, example, evidence in checked:
            row = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()
            if not row:
                b.db.execute("INSERT INTO sr_habit VALUES(?,?,?,?,'candidate',0,0,?)",
                             (hid, pattern, mechanism, example, time.time()))
            b.db.execute('INSERT OR IGNORE INTO sr_evidence VALUES(?,?,?,?)', (hid, doc['url'], doc['id'], evidence))
            count = b.db.execute('SELECT count(*) FROM sr_evidence WHERE habit=?', (hid,)).fetchone()[0]
            if not row or row['status'] != 'rejected':
                positive = row['positive'] if row else 0
                status = 'mature' if count >= 8 or (count >= 3 and positive >= 2) else 'trial' if count >= 3 else 'candidate'
                b.db.execute('UPDATE sr_habit SET status=?,updated=? WHERE id=?', (status, time.time(), hid))
        b.db.execute('INSERT INTO sr_reflection VALUES(?,?,?,?)', (doc['id'], summary, note, time.time()))
    return dict(ok=True, note_id=note, learned=len(checked), habits=habit_rows(b),
                authority='model_inference_from_observed_human_speech; subordinate_to_current_persona')


def feedback(b, q):
    event = owner_event(b, q)
    hid, polarity = q.get('habit_id'), q.get('polarity')
    row = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()
    if not row or polarity not in ('positive', 'negative', 'stop'):
        raise ValueError('invalid_habit_feedback')
    with b.db:
        if b.db.execute('SELECT 1 FROM sr_feedback WHERE habit=? AND event=?', (hid, event['id'])).fetchone():
            return dict(ok=True, replayed=True)
        b.db.execute('INSERT INTO sr_feedback VALUES(?,?,?)', (hid, event['id'], polarity))
        if polarity != 'positive':
            b.db.execute("UPDATE sr_habit SET status='rejected',negative=negative+1,updated=? WHERE id=?", (time.time(), hid))
        else:
            b.db.execute('UPDATE sr_habit SET positive=positive+1,updated=? WHERE id=?', (time.time(), hid))
            count = b.db.execute('SELECT count(*) FROM sr_evidence WHERE habit=?', (hid,)).fetchone()[0]
            if count >= 3 and row['positive'] + 1 >= 2 and row['status'] != 'rejected':
                b.db.execute("UPDATE sr_habit SET status='mature' WHERE id=?", (hid,))
    return dict(ok=True, habit=dict(b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()))


def voice(b):
    if not settings(b)['language_learning']:
        return []
    rows = [r for r in habit_rows(b) if r['status'] in ('trial', 'mature')]
    rows.sort(key=lambda r: (r['status'] == 'mature', r['positive'], r['exposures']), reverse=True)
    return [dict(id=r['id'], hint=r['pattern'], example=r['example'], status=r['status'],
                 strength=round(min(.7, .08 * r['exposures'] + .05 * r['positive']), 2)) for r in rows[:4]]
