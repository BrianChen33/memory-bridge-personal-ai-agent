"""Same-host-model personality reflection grounded in verified speech habits.

Work supplies evidence, never a trait inferred from a word. Each review consumes
three actual uses across two native turns; heartbeat replay cannot add strength.
"""
import hashlib
import json
import math
import time
from datetime import datetime, timezone, timedelta

from .growth import CAPS, DAILY
from .sources import owner_event, text


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(_json(value).encode()).hexdigest()


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS sr_habit_growth(id TEXT PRIMARY KEY,domain TEXT,trait TEXT,
      interpretation TEXT,example TEXT,stopped INTEGER DEFAULT 0,created REAL,updated REAL);
    CREATE TABLE IF NOT EXISTS sr_habit_growth_proposal(id TEXT PRIMARY KEY,payload TEXT,created REAL);
    CREATE TABLE IF NOT EXISTS sr_habit_growth_receipt(proposal TEXT PRIMARY KEY,request_hash TEXT,
      growth TEXT,habit_ids TEXT,delta REAL,day TEXT,direction TEXT,reflection TEXT,created REAL);
    CREATE INDEX IF NOT EXISTS sr_habit_growth_day ON sr_habit_growth_receipt(day,growth);
    CREATE TABLE IF NOT EXISTS sr_habit_growth_use(habit TEXT,output TEXT,proposal TEXT,
      PRIMARY KEY(habit,output));
    CREATE TABLE IF NOT EXISTS sr_habit_growth_feedback(growth TEXT,event INTEGER,polarity TEXT,
      PRIMARY KEY(growth,event));
    ''')


def _enabled(b):
    from . import store
    return store.settings(b)['personality_growth']


def _qualified(b):
    from . import voice
    return {r['id']: r for r in voice.qualified_habits(b)
            if r.get('status') == 'mature' and not r.get('stopped')
            and r.get('uses', 0) >= 3 and r.get('native_turns', 0) >= 2
            and r.get('revision') and r.get('source_proof')}


def _ids(value):
    if (not isinstance(value, list) or not 1 <= len(value) <= 3
            or any(not isinstance(x, str) or not x.strip() or len(x) > 120 for x in value)
            or len(set(value)) != len(value)):
        raise ValueError('one_to_three_unique_habit_ids_required')
    return sorted(value)


def _turn(proof):
    return proof.get('chat_id'), proof.get('turn_id')


def _fresh(b, habit):
    used = {r[0] for r in b.db.execute('SELECT output FROM sr_habit_growth_use WHERE habit=?',
                                     (habit['id'],))}
    available, seen = [], set()
    for proof in sorted(habit.get('usage_proof', []), key=lambda p: (
            p.get('occurred_at_ms', 0), str(p.get('chat_id')), str(p.get('turn_id')),
            p.get('seq', 0), str(p.get('output_id')))):
        oid = proof.get('output_id')
        if (oid and oid not in used and oid not in seen and proof.get('appropriate') is True
                and all(isinstance(x, str) and x for x in _turn(proof))):
            available.append(proof)
            seen.add(oid)
    if len(available) < 3 or len({_turn(p) for p in available}) < 2:
        return None
    selected = available[:3]
    if len({_turn(p) for p in selected}) < 2:
        selected[-1] = next(p for p in available[3:] if _turn(p) != _turn(selected[0]))
    # Bounded quotes preserve the verified lineage; they do not increase confidence.
    sources = sorted(habit['source_proof'], key=_json)[:3]
    profile = {k: habit.get(k) for k in ('id', 'kind', 'form', 'pattern', 'meaning',
        'mechanism', 'example', 'scenes', 'targets', 'intensity', 'avoid_contexts',
        'tone_limit', 'revision')}
    return dict(profile, uses=habit['uses'], native_turns=habit['native_turns'],
                source_proof=sources, usage_proof=selected, usage_revision=_hash(selected))


def work(b, q):
    """Return at most three evidence bundles for the existing feedback heartbeat."""
    if not _enabled(b):
        return dict(status='disabled', enabled=False, proposal_id=None, habits=[], existing_traits=[])
    limit = q.get('limit', 3)
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError('habit_growth_limit_one_to_three')
    wanted = set(_ids(q['habit_ids'])) if 'habit_ids' in q else None
    candidates = []
    for hid, habit in sorted(_qualified(b).items()):
        if wanted is not None and hid not in wanted:
            continue
        candidate = _fresh(b, habit)
        if candidate:
            candidates.append(candidate)
        if len(candidates) == limit:
            break
    if not candidates:
        return dict(status='idle', enabled=True, proposal_id=None, habits=[], existing_traits=[])
    payload = {'habits': candidates}
    pid = 'habit-proposal:' + _hash(payload)[:40]
    with b.db:
        b.db.execute('INSERT OR IGNORE INTO sr_habit_growth_proposal VALUES(?,?,?)',
                     (pid, _json(payload), time.time()))
    existing = [{k: r[k] for k in ('id', 'domain', 'trait', 'strength', 'status')}
                for r in rows(b)[:12]]
    return dict(status='review', enabled=True, proposal_id=pid, habits=candidates,
                existing_traits=existing, instructions=(
                    'The same host reply model may reflect on these actual habits and uses. '
                    'A repeated word does not establish a belief or a personality trait. '
                    'Choose a contextual preference or temperament only if it fits current self-understanding; '
                    'resonance=0 records no adoption. Reconsider an existing_id to reduce that same tendency. '
                    'Do not copy source identities, attack targets, permissions or invented experiences.'))


def spent(b, domain, day):
    """Habit pathway's absolute spend, also shared with the reading pathway."""
    return b.db.execute('''SELECT coalesce(sum(abs(r.delta)),0)
      FROM sr_habit_growth_receipt r JOIN sr_habit_growth g ON g.id=r.growth
      WHERE g.domain=? AND r.day=?''', (domain, day)).fetchone()[0]


def _live(b, snapshots, current, unconsumed=False):
    from . import voice
    for snapshot in snapshots:
        hid = snapshot['id']
        habit = current.get(hid)
        if not habit or snapshot['revision'] != habit['revision']:
            return False
        if (not snapshot['source_proof'] or
                any(not voice.verified_source(b, hid, p) for p in snapshot['source_proof'])):
            return False
        proofs = snapshot['usage_proof']
        if (len(proofs) < 3 or len({_turn(p) for p in proofs}) < 2 or
                any(not voice.verified_usage(b, hid, p) for p in proofs)):
            return False
        if unconsumed and any(b.db.execute('''SELECT 1 FROM sr_habit_growth_use
                WHERE habit=? AND output=?''', (hid, p['output_id'])).fetchone() for p in proofs):
            return False
    return bool(snapshots)


def integrate(b, q):
    """Validate one model-authored reflection and its immutable use receipts."""
    if not _enabled(b):
        return dict(status='disabled', applied=0, traits=rows(b))
    if q.get('proposal_id') is None:
        return dict(status='insufficient_evidence', applied=0, traits=rows(b))
    pid = text(q.get('proposal_id'), 120, True)
    ids = _ids(q.get('habit_ids'))
    domain = q.get('domain')
    if domain not in CAPS:
        raise ValueError('growth_domain_preference_or_temperament_required')
    trait = text(q.get('trait'), 120, True)
    interpretation = text(q.get('interpretation'), 240, True)
    example = text(q.get('example'), 120, True)
    resonance = q.get('resonance')
    if (isinstance(resonance, bool) or not isinstance(resonance, (int, float))
            or not math.isfinite(resonance) or not 0 <= resonance <= 1):
        raise ValueError('habit_growth_resonance_must_be_0_to_1')
    direction = q.get('direction')
    if direction not in ('adopt', 'reconsider'):
        raise ValueError('growth_direction_required')
    existing_id = q.get('existing_id')
    if existing_id is not None:
        existing_id = text(existing_id, 120, True)
    request = dict(habit_ids=ids, domain=domain, trait=trait, interpretation=interpretation,
                   example=example, resonance=resonance, direction=direction, existing_id=existing_id)
    fingerprint = _hash(request)
    now = time.time()
    day = datetime.fromtimestamp(now, timezone(timedelta(hours=8))).date().isoformat()
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        old_receipt = b.db.execute('SELECT * FROM sr_habit_growth_receipt WHERE proposal=?', (pid,)).fetchone()
        if old_receipt:
            if old_receipt['request_hash'] != fingerprint:
                raise ValueError('habit_growth_proposal_content_conflict')
            return dict(status='replayed', applied=0, replayed=True, traits=rows(b))
        proposal = b.db.execute('SELECT payload FROM sr_habit_growth_proposal WHERE id=?', (pid,)).fetchone()
        if not proposal:
            raise ValueError('real_habit_growth_proposal_required')
        offered = {h['id']: h for h in json.loads(proposal['payload'])['habits']}
        if any(hid not in offered for hid in ids):
            raise ValueError('habit_not_in_growth_proposal')
        snapshots = [offered[hid] for hid in ids]
        if not _live(b, snapshots, _qualified(b), unconsumed=True):
            raise ValueError('habit_growth_evidence_stale_or_already_reviewed')
        gid = existing_id or 'habit-trait:' + _hash([domain, trait.casefold()])[:24]
        old = b.db.execute('SELECT * FROM sr_habit_growth WHERE id=?', (gid,)).fetchone()
        if existing_id and (not old or old['domain'] != domain):
            raise ValueError('existing_habit_growth_domain_mismatch')
        if direction == 'reconsider' and not old:
            raise ValueError('reconsider_requires_existing_adopted_growth')
        strength = next((r['strength'] for r in rows(b) if r['id'] == gid), 0)
        if direction == 'reconsider' and not old['stopped'] and strength <= 0:
            raise ValueError('reconsider_requires_existing_adopted_growth')
        legacy_used = b.db.execute('''SELECT coalesce(sum(abs(e.delta)),0)
          FROM sr_growth_evidence e JOIN sr_growth g ON g.id=e.growth
          WHERE g.domain=? AND e.day=?''', (domain, day)).fetchone()[0]
        delta = min(CAPS[domain] * resonance,
                    max(0., DAILY[domain] - legacy_used - spent(b, domain, day)))
        if old and old['stopped']:
            delta = 0.
        if direction == 'reconsider':
            delta = -min(delta, strength)
        if delta and not old:
            b.db.execute('INSERT INTO sr_habit_growth VALUES(?,?,?,?,?,0,?,?)',
                         (gid, domain, trait, interpretation, example, now, now))
        elif delta:
            # Reconsideration changes the strength of this trait, not its identity.
            b.db.execute('''UPDATE sr_habit_growth SET interpretation=?,example=?,updated=?
              WHERE id=?''', (interpretation, example, now, gid))
        b.db.execute('INSERT INTO sr_habit_growth_receipt VALUES(?,?,?,?,?,?,?,?,?)',
                     (pid, fingerprint, gid if old or delta else None, _json(ids), delta,
                      day, direction, _json(request), now))
        for snapshot in snapshots:
            for proof in snapshot['usage_proof']:
                b.db.execute('INSERT INTO sr_habit_growth_use VALUES(?,?,?)',
                             (snapshot['id'], proof['output_id'], pid))
    return dict(status='saved' if delta else 'assessed', applied=int(bool(delta)), delta=round(delta, 6),
                proposal_id=pid, traits=rows(b), evidence='same_host_model_self_reflection_of_verified_uses')


def rows(b):
    """Panel history, with inactive evidence excluded from the present strength."""
    enabled = _enabled(b)
    current = _qualified(b) if enabled else {}
    records = b.db.execute('SELECT * FROM sr_habit_growth ORDER BY updated DESC,id LIMIT 60').fetchall()
    result = []
    for record in records:
        item = dict(record)
        total, source_events, outputs, turns, days, habits = 0., set(), set(), set(), set(), set()
        reviews, history, current_reflection = 0, [], False
        receipts = b.db.execute('''SELECT r.*,p.payload FROM sr_habit_growth_receipt r
          JOIN sr_habit_growth_proposal p ON p.id=r.proposal WHERE r.growth=?
          ORDER BY r.created DESC,r.proposal''', (item['id'],)).fetchall()
        for receipt in receipts:
            ids = json.loads(receipt['habit_ids'])
            snapshots = [h for h in json.loads(receipt['payload'])['habits'] if h['id'] in ids]
            live = enabled and not item['stopped'] and _live(b, snapshots, current)
            if len(history) < 8:
                history.append(dict(proposal_id=receipt['proposal'], delta=round(receipt['delta'], 6),
                    direction=receipt['direction'], day=receipt['day'], active=bool(live),
                    revision=receipt['request_hash'], habit_ids=ids,
                    source_proof=[p for h in snapshots for p in h['source_proof']],
                    usage_proof=[p for h in snapshots for p in h['usage_proof']]))
            if not live:
                continue
            if not current_reflection:
                reflection = json.loads(receipt['reflection'])
                item['interpretation'], item['example'] = reflection['interpretation'], reflection['example']
                current_reflection = True
            total += receipt['delta']
            if receipt['delta'] <= 0:
                continue
            reviews += 1
            days.add(receipt['day'])
            for snapshot in snapshots:
                habits.add(snapshot['id'])
                source_events.update(p['source_event'] for p in snapshot['source_proof'])
                outputs.update(p['output_id'] for p in snapshot['usage_proof'])
                turns.update(_turn(p) for p in snapshot['usage_proof'])
        item['strength'] = round(max(0., min(.75, total)), 6)
        item.update(uses=len(outputs), native_turns=len(turns), source_count=len(source_events),
                    days=len(days), reviews=reviews, history=history)
        item['status'] = ('stopped' if item['stopped'] else 'suspended' if not enabled else
            'integrated' if item['strength'] >= .12 and len(days) >= 2 and len(outputs) >= 8 else
            'emerging' if item['strength'] > 0 else 'inactive')
        item['evidence'] = dict(habit_ids=sorted(habits), source_events=sorted(source_events),
            output_ids=sorted(outputs), proposal_ids=[h['proposal_id'] for h in history if h['active']])
        result.append(item)
    return result


def context(b):
    enabled = _enabled(b)
    traits = [r for r in rows(b) if r['status'] in ('emerging', 'integrated')]
    traits.sort(key=lambda r: (r['status'] == 'integrated', r['strength'], r['updated']), reverse=True)
    projection = []
    for item in traits[:3]:
        references = {key: value[:3 if key != 'output_ids' else 6]
                      for key, value in item['evidence'].items()}
        projection.append(dict(id=item['id'], domain=item['domain'], trait=item['trait'],
            interpretation=item['interpretation'][:140], strength=item['strength'],
            status=item['status'], evidence=references))
    return dict(enabled=enabled, revision=_hash([enabled, projection]), traits=projection,
        authority=('These are model-reflected, contextual preferences and temperament grounded in actual uses, '
                   'not unquestioned beliefs inferred from repeated words. Combine them with the base SOUL '
                   'and present emotion as current personality; they may revise flexible old tendencies. '
                   'Keep established appearance, identity, factual history, owner instructions and permissions intact. '
                   'Use when relevant, without a forced catchphrase, constant attacks, copied source identities '
                   'or invented real-world experiences.'))


def feedback(b, q):
    event = owner_event(b, q)
    gid, polarity = q.get('growth_id'), q.get('polarity')
    if (polarity not in ('positive', 'negative', 'stop') or
            not b.db.execute('SELECT 1 FROM sr_habit_growth WHERE id=?', (gid,)).fetchone()):
        raise ValueError('invalid_habit_growth_feedback')
    with b.db:
        prior = b.db.execute('SELECT 1 FROM sr_habit_growth_feedback WHERE growth=? AND event=?',
                             (gid, event['id'])).fetchone()
        if prior:
            return dict(ok=True, replayed=True, traits=rows(b))
        b.db.execute('INSERT INTO sr_habit_growth_feedback VALUES(?,?,?)', (gid, event['id'], polarity))
        if polarity != 'positive':
            b.db.execute('UPDATE sr_habit_growth SET stopped=1,updated=? WHERE id=?', (time.time(), gid))
    return dict(ok=True, traits=rows(b), note='Feedback never fabricates source evidence or verified uses.')
