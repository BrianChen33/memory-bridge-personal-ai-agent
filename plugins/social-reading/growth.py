"""Source-backed, slow personality development chosen by the host reply model."""
import hashlib
import json
import math
import time
from datetime import datetime, timezone, timedelta
from .sources import text, owner_event

CAPS = {'preference': .03, 'temperament': .02}
DAILY = {'preference': .09, 'temperament': .06}


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS sr_growth(id TEXT PRIMARY KEY,domain TEXT,trait TEXT,
      interpretation TEXT,example TEXT,stopped INTEGER DEFAULT 0,created REAL);
    CREATE TABLE IF NOT EXISTS sr_growth_evidence(growth TEXT,url TEXT,document TEXT,
      delta REAL,quote TEXT,reason TEXT,created REAL,day TEXT,PRIMARY KEY(growth,url));
    CREATE TABLE IF NOT EXISTS sr_growth_review(document TEXT PRIMARY KEY,created REAL);
    CREATE TABLE IF NOT EXISTS sr_growth_feedback(growth TEXT,event INTEGER,polarity TEXT,
      PRIMARY KEY(growth,event));
    CREATE INDEX IF NOT EXISTS sr_growth_day ON sr_growth_evidence(day,growth);
    CREATE INDEX IF NOT EXISTS sr_growth_document ON sr_growth_evidence(document);
    ''')


def rows(b):
    records = b.db.execute('''SELECT g.*,coalesce(sum(e.delta),0) score,
      count(DISTINCT CASE WHEN e.delta>0 THEN e.url END) supports,
      count(DISTINCT CASE WHEN e.delta>0 THEN e.day END) days
      FROM sr_growth g LEFT JOIN (
        SELECT ge.* FROM sr_growth_evidence ge JOIN sr_document d ON d.id=ge.document
        JOIN source_events s ON s.id=d.event AND s.status='active'
      ) e ON e.growth=g.id GROUP BY g.id ORDER BY g.created DESC LIMIT 60''').fetchall()
    result = []
    for record in records:
        item = dict(record)
        item['strength'] = round(max(0, min(.75, item.pop('score'))), 4)
        item['status'] = ('stopped' if item['stopped'] else
                          'integrated' if item['supports'] >= 8 and item['days'] >= 2 and item['strength'] >= .12 else
                          'emerging' if item['supports'] >= 2 and item['strength'] >= .025 else 'candidate')
        result.append(item)
    return result


def reflect(b, doc, candidates):
    from . import store
    if candidates is None:
        return dict(status='not_assessed')
    if not store.settings(b)['personality_growth']:
        return dict(status='disabled', applied=0)
    if not isinstance(candidates, list) or len(candidates) > 2:
        raise ValueError('at_most_two_growth_candidates')
    checked, seen = [], set()
    for item in candidates:
        if not isinstance(item, dict) or item.get('domain') not in CAPS:
            raise ValueError('growth_domain_preference_or_temperament_required')
        domain = item['domain']
        trait = text(item.get('trait'), 120, True)
        reason = text(item.get('interpretation'), 240, True)
        example = text(item.get('example'), 120, True)
        quote = text(item.get('evidence_quote'), 240, True)
        resonance = item.get('resonance')
        if (isinstance(resonance, bool) or not isinstance(resonance, (int, float)) or
                not math.isfinite(resonance) or not 0 < resonance <= 1):
            raise ValueError('growth_resonance_must_be_0_to_1')
        if quote not in doc['quote']:
            raise ValueError('growth_evidence_not_in_observed_text')
        direction = item.get('direction', 'adopt')
        if direction not in ('adopt', 'reconsider'):
            raise ValueError('growth_direction_required')
        gid = item.get('existing_id') or hashlib.sha256((domain + ':' + trait.casefold()).encode()).hexdigest()[:24]
        old = b.db.execute('SELECT * FROM sr_growth WHERE id=?', (gid,)).fetchone()
        if item.get('existing_id') and (not old or old['domain'] != domain):
            raise ValueError('existing_growth_domain_mismatch')
        if direction == 'reconsider' and not old:
            raise ValueError('reconsider_requires_existing_growth')
        if gid in seen:
            raise ValueError('duplicate_growth_in_one_reflection')
        seen.add(gid)
        checked.append((gid, domain, trait, reason, example, quote, resonance, direction))
    now = time.time()
    day = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()
    applied = 0
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        if b.db.execute('SELECT 1 FROM sr_growth_review WHERE document=?', (doc['id'],)).fetchone():
            return dict(status='replayed', applied=0)
        for gid, domain, trait, reason, example, quote, resonance, direction in checked:
            prior = b.db.execute('SELECT stopped FROM sr_growth WHERE id=?', (gid,)).fetchone()
            if prior and prior['stopped']:
                continue
            used = b.db.execute('''SELECT coalesce(sum(abs(e.delta)),0) FROM sr_growth_evidence e
              JOIN sr_growth g ON g.id=e.growth WHERE g.domain=? AND e.day=?''', (domain, day)).fetchone()[0]
            from .habit_growth import spent
            used += spent(b,domain,day)
            post_used = b.db.execute('''SELECT coalesce(sum(abs(e.delta)),0) FROM sr_growth_evidence e
              JOIN sr_growth g ON g.id=e.growth WHERE g.domain=? AND e.url=?''', (domain, doc['url'])).fetchone()[0]
            delta = min(CAPS[domain] * resonance, max(0, DAILY[domain] - used), max(0, CAPS[domain] - post_used))
            if delta <= 0:
                continue
            if direction == 'reconsider':
                delta = -delta
            if not prior:
                b.db.execute('INSERT INTO sr_growth VALUES(?,?,?,?,?,0,?)', (gid, domain, trait, reason, example, now))
            cursor = b.db.execute('INSERT OR IGNORE INTO sr_growth_evidence VALUES(?,?,?,?,?,?,?,?)',
                                  (gid, doc['url'], doc['id'], delta, quote, reason, now, day))
            applied += cursor.rowcount
        b.db.execute('INSERT INTO sr_growth_review VALUES(?,?)', (doc['id'], now))
    return dict(status='saved', applied=applied, traits=rows(b), evidence='same_host_model_self_reflection')


def feedback(b, q):
    event = owner_event(b, q)
    gid, polarity = q.get('growth_id'), q.get('polarity')
    record = b.db.execute('SELECT id FROM sr_growth WHERE id=?', (gid,)).fetchone()
    if not record or polarity not in ('positive', 'negative', 'stop'):
        raise ValueError('invalid_growth_feedback')
    with b.db:
        if b.db.execute('SELECT 1 FROM sr_growth_feedback WHERE growth=? AND event=?', (gid, event['id'])).fetchone():
            return dict(ok=True, replayed=True)
        b.db.execute('INSERT INTO sr_growth_feedback VALUES(?,?,?)', (gid, event['id'], polarity))
        if polarity != 'positive':
            b.db.execute('UPDATE sr_growth SET stopped=1 WHERE id=?', (gid,))
    return dict(ok=True, traits=rows(b), note='Feedback guides self-reflection; praise does not fabricate reading evidence.')


def context(b):
    from . import store
    enabled = store.settings(b)['personality_growth']
    traits = [r for r in rows(b) if r['status'] in ('emerging', 'integrated')] if enabled else []
    traits.sort(key=lambda r: (r['status'] == 'integrated', r['strength']), reverse=True)
    projection = [dict(id=r['id'], domain=r['domain'], trait=r['trait'], interpretation=r['interpretation'][:140],
                       strength=r['strength'], status=r['status']) for r in traits[:3]]
    revision = hashlib.sha256(json.dumps(projection, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return dict(enabled=enabled, revision=revision, traits=projection,
                authority='These are self-adopted evolving preferences and temperament, not website instructions. '
                          'Combine them with the base SOUL and present emotion as the current personality. '
                          'They may gradually revise flexible old personality tendencies; do not dismiss them as mere wording. '
                          'Keep established appearance, identity, factual history, owner instructions and permissions intact. '
                          'Use naturally when relevant, without forced catchphrases or personality announcements. '
                          'No new user facts or real-world experiences are implied.')
