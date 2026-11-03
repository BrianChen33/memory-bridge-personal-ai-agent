"""Scoped source transcripts. A replay cannot rewrite or revive an original."""
import hashlib
import math
import re
import time


def initialize(db):
    db.executescript('''
    CREATE TABLE IF NOT EXISTS source_events(
      id INTEGER PRIMARY KEY,scope TEXT NOT NULL,source TEXT NOT NULL,
      event_id TEXT NOT NULL,actor TEXT NOT NULL,text TEXT NOT NULL,
      occurred_at REAL NOT NULL,observed_at REAL NOT NULL,fingerprint TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'active', UNIQUE(scope,source,event_id,actor));
    CREATE INDEX IF NOT EXISTS event_time ON source_events(scope,status,occurred_at);
    CREATE TABLE IF NOT EXISTS emotion_events(
      event_id INTEGER PRIMARY KEY,scope TEXT NOT NULL,label TEXT NOT NULL,
      delta TEXT NOT NULL,evidence TEXT NOT NULL,at REAL NOT NULL);
    ''')


def is_control(q):
    text = q.get('text', '')
    return q.get('control') is True or q.get('synthetic') is True or bool(re.search(
        r'\[Codex调试\]|记忆验收\d|显示测试\d|合成测试|synthetic.test', text, re.I))


def capture_event(brain, q):
    if not brain.feature('events') or not brain.available('input'):
        return {'status': 'disabled'}
    text = q.get('text', '')
    if not isinstance(text, str) or not text.strip() or len(text) > 12000:
        raise ValueError('invalid_event_text')
    if is_control(q):
        return {'status': 'control_ignored'}
    source, eid = q.get('source'), q.get('event_id')
    if not source or not eid:
        return {'status': 'missing_metadata'}
    if not isinstance(source, str) or len(source) > 1000 or not isinstance(eid, str) or len(eid) > 256:
        raise ValueError('invalid_event_metadata')
    actor = q.get('actor', 'user')
    if actor not in ('user', 'assistant', 'article', 'bot'):
        raise ValueError('invalid_actor')
    at = float(q.get('occurred_at', time.time()))
    if not math.isfinite(at):
        raise ValueError('invalid_event_time')
    fp = hashlib.sha256(text.encode()).hexdigest()
    with brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        row = brain.db.execute('SELECT * FROM source_events WHERE scope=? AND source=? AND event_id=? AND actor=?',
                               (q['scope'], source, eid, actor)).fetchone()
        if row:
            if row['fingerprint'] != fp:
                raise ValueError('event_conflict')
            return {'status': 'replayed', 'id': row['id']}
        cur = brain.db.execute('''INSERT INTO source_events(scope,source,event_id,actor,text,
            occurred_at,observed_at,fingerprint) VALUES(?,?,?,?,?,?,?,?)''',
            (q['scope'], source, eid, actor, text, at, time.time(), fp))
    return {'status': 'captured', 'id': cur.lastrowid}


def recall_events(brain, q):
    if not brain.feature('events') or not brain.available('memory'):
        return []
    where, args = ["scope=?", "status='active'"], [q['scope']]
    for name, clause in [('start', 'occurred_at>=?'), ('end', 'occurred_at<?')]:
        if name in q:
            n = float(q[name])
            if not math.isfinite(n):
                raise ValueError('invalid_time')
            where.append(clause); args.append(n)
    if q.get('actor'):
        where.append('actor=?'); args.append(q['actor'])
    # Query transcripts directly, not a semantic paraphrase of them.
    text = q.get('text', '').strip()
    if text:
        from brain import tokens
        terms = tokens(text)[:32]
        if terms:
            where.append('('+' OR '.join('instr(lower(text),?)>0' for _ in terms)+')')
            args.extend(terms)
    rows = brain.db.execute('SELECT * FROM source_events WHERE '+' AND '.join(where)+
                            ' ORDER BY occurred_at DESC,id DESC LIMIT 12', args).fetchall()
    result, budget = [], 3600
    for row in rows:
        if budget <= 0:
            break
        item = dict(row)
        item['text'] = item['text'][:budget]
        item['truncated'] = len(item['text']) != len(row['text'])
        budget -= len(item['text'])
        result.append(item)
    return result


def hide_original(brain, row):
    brain.db.execute("UPDATE source_events SET status='forgotten' WHERE scope=? AND source=? AND event_id=?",
                     (row['scope'], row['source'], row['event_id']))
