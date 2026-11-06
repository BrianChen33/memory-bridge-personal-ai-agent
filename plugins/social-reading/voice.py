"""Source-backed expression trials and receipts from actual native assistant output.

All judgments come from the same host model. Text is evidence, never authority;
this module does not send, appraise emotion, or invoke a model.
"""
import hashlib
import json
import math
import time
from .sources import owner_event, text


def initialize(b):
    # Keep the positional legacy sr_habit/sr_evidence schemas unchanged.
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS sr_habit_profile(habit TEXT PRIMARY KEY,payload TEXT,stopped INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS sr_owner_evidence(habit TEXT,event INTEGER,quote TEXT,PRIMARY KEY(habit,event));
    CREATE TABLE IF NOT EXISTS sr_voice_feedback(habit TEXT,event INTEGER,kind TEXT,payload TEXT,
      PRIMARY KEY(habit,event,kind));
    CREATE TABLE IF NOT EXISTS sr_output(id TEXT PRIMARY KEY,chat_id TEXT,turn_id TEXT,seq INTEGER,
      occurred_at_ms INTEGER,text TEXT,text_hash TEXT,created REAL,UNIQUE(chat_id,turn_id,seq));
    CREATE TABLE IF NOT EXISTS sr_usage(habit TEXT,output TEXT,evidence_quote TEXT,appropriate INTEGER,
      reason TEXT,revision TEXT,created REAL,PRIMARY KEY(habit,output));
    CREATE INDEX IF NOT EXISTS sr_usage_output ON sr_usage(output);
    ''')


def _scope(q):
    if q.get('scope', 'owner-private') != 'owner-private':
        raise ValueError('social_reading_owner_only')


def _enabled(b):
    from .store import settings
    return settings(b)['language_learning']


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _hash(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _list(value, limit=8, chars=120):
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError('bounded_expression_list_required')
    return list(dict.fromkeys(text(v, chars, True) for v in value))


def _intensity(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('bounded_expression_intensity_required')
    return value


def _candidate(item, lexical=False):
    if not isinstance(item, dict):
        raise ValueError('expression_candidate_object_required')
    typed = lexical or any(k in item for k in ('kind', 'understood', 'meaning', 'form'))
    quote = text(item.get('evidence_quote'), 240, True)
    if not typed:
        profile = dict(kind='legacy', form=text(item.get('pattern'), 140, True),
                       meaning=text(item.get('mechanism'), 240, True),
                       example=text(item.get('example'), 160, True))
    else:
        kind = item.get('kind', 'lexical' if lexical else 'mechanism')
        if kind not in ('lexical', 'phrase', 'mechanism') or type(item.get('understood')) is not bool:
            raise ValueError('typed_expression_kind_and_understanding_required')
        profile = dict(kind=kind, form=text(item.get('form', item.get('pattern')), 140, True),
                       meaning=text(item.get('meaning', item.get('mechanism')), 400, True),
                       variants=_list(item.get('variants', []), chars=140),
                       triggers=_list(item.get('triggers', [])), scenes=_list(item.get('scenes', [])),
                       targets=_list(item.get('targets', []), chars=80),
                       intensity=_intensity(item.get('intensity', 50)), understood=item['understood'],
                       reason=text(item.get('reason', ''), 400, not item['understood']),
                       avoid_contexts=_list(item.get('avoid_contexts', [])),
                       tone_limit=text(item.get('tone_limit', ''), 160))
        profile['example'] = text(item.get('example', profile['form']), 160, True)
        mode=item.get('usage_mode','expressive')
        if mode not in ('expressive','reference_only'):
            raise ValueError('expression_usage_mode_required')
        profile['usage_mode']=mode
        if kind in ('lexical', 'phrase') and not any(v in quote for v in [profile['form']] + profile['variants']):
            raise ValueError('actual_expression_not_in_source_quote')
    hid = item.get('existing_id') or item.get('habit_id')
    if hid is not None:
        hid = text(hid, 80, True)
    else:
        key = profile['form'].casefold()
        hid = _hash(key if profile['kind'] == 'legacy' else profile['kind'] + ':' + key)[:24]
    return hid, profile, quote


def _profile(b, habit):
    row = b.db.execute('SELECT * FROM sr_habit_profile WHERE habit=?', (habit['id'],)).fetchone()
    profile = json.loads(row['payload']) if row else dict(kind='legacy', form=habit['pattern'],
                meaning=habit['mechanism'], example=habit['example'], understood=None)
    stopped = bool(row and row['stopped']) or bool(b.db.execute(
        "SELECT 1 FROM sr_feedback WHERE habit=? AND polarity='stop'", (habit['id'],)).fetchone())
    return dict(profile, stopped=stopped)


def _revision(profile):
    return _hash(_json(profile))


def _save_profile(b, hid, profile, stopped=False):
    payload = dict(profile)
    payload.pop('stopped', None)
    b.db.execute('INSERT OR REPLACE INTO sr_habit_profile VALUES(?,?,?)', (hid, _json(payload), int(stopped)))


def _document(b, did):
    doc = b.db.execute('''SELECT d.* FROM sr_document d
      JOIN source_events e ON e.id=d.event AND e.actor='article' AND e.scope='owner-private' AND e.status='active'
      JOIN sr_source s ON s.id=d.source WHERE d.id=?''', (did,)).fetchone()
    if not doc:
        raise ValueError('active_real_observed_document_required')
    return doc


def _source_proof(b, hid):
    habit=b.db.execute('SELECT * FROM sr_habit WHERE id=?',(hid,)).fetchone()
    profile=_profile(b,habit) if habit else None
    matches=lambda quote:bool(profile and (profile['kind'] not in ('lexical','phrase') or _matches(profile,quote)))
    docs = b.db.execute('''SELECT d.id document_id,d.url,d.event source_event,d.quote_id,
      d.quote actual_quote,e.quote evidence_quote FROM sr_evidence e JOIN sr_document d ON d.id=e.document
      JOIN source_events se ON se.id=d.event AND se.status='active' AND se.actor='article' AND se.scope='owner-private'
      JOIN sr_source s ON s.id=d.source
      WHERE e.habit=? ORDER BY d.created DESC LIMIT 8''', (hid,)).fetchall()
    result = [dict(document_id=r['document_id'], url=r['url'], source_event=r['source_event'],
                   quote_id=r['quote_id'], evidence_quote=r['evidence_quote'], owner_event=None)
              for r in docs if r['evidence_quote'] and r['evidence_quote'] in r['actual_quote'] and matches(r['evidence_quote'])]
    owners = b.db.execute('''SELECT e.event,e.quote,s.text FROM sr_owner_evidence e JOIN source_events s
      ON s.id=e.event AND s.actor='user' AND s.scope='owner-private' AND s.status='active'
      WHERE e.habit=? ORDER BY e.event DESC LIMIT 8''', (hid,)).fetchall()
    return [dict(document_id=None, url='owner-event:' + str(r['event']), source_event=r['event'],
                 quote_id=None, evidence_quote=r['quote'], owner_event=r['event'])
            for r in owners if r['quote'] and r['quote'] in r['text'] and matches(r['quote'])] + result


def _related_rejections(b, hid, proposed):
    names = {v.casefold() for v in [proposed['form']] + proposed.get('variants', [])}
    rejected, stopped = False, False
    for habit in b.db.execute("SELECT * FROM sr_habit WHERE status='rejected' AND id<>?", (hid,)):
        profile = _profile(b, habit)
        aliases = {v.casefold() for v in [profile['form']] + profile.get('variants', [])}
        if names & aliases:
            rejected, stopped = True, stopped or profile['stopped']
    return rejected, stopped


def _apply(b, hid, proposed, review=False, owner=False):
    old = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()
    now = time.time()
    if not old:
        b.db.execute("INSERT INTO sr_habit VALUES(?,?,?,?,'candidate',0,0,?)",
                     (hid, proposed['form'], proposed['meaning'], proposed['example'], now))
        old = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()
    previous = _profile(b, old)
    related_rejected, related_stopped = _related_rejections(b, hid, proposed)
    previous['stopped'] = previous['stopped'] or related_stopped
    if proposed['kind'] != 'legacy':
        if previous['kind'] != 'legacy' and previous.get('understood') and not (review or owner):
            proposed = dict(previous)
        elif not owner:
            for field in previous.get('owner_fields', []):
                proposed[field] = previous[field]
            if previous.get('owner_fields'):
                proposed['owner_fields'] = previous['owner_fields']
        _save_profile(b, hid, proposed, previous['stopped'])
        changed = _revision(dict(proposed, stopped=previous['stopped'])) != _revision(previous)
        status = ('rejected' if old['status'] == 'rejected' or related_rejected or previous['stopped'] else
                  'mature' if old['status'] == 'mature' and not changed else
                  'reference' if proposed.get('usage_mode')=='reference_only' and proposed['understood'] else
                  'trial' if proposed['understood'] else 'candidate')
        b.db.execute('UPDATE sr_habit SET pattern=?,mechanism=?,example=?,status=?,updated=? WHERE id=?',
                     (proposed['form'], proposed['meaning'], proposed['example'], status, now, hid))
    elif related_rejected or previous['stopped']:
        _save_profile(b, hid, proposed, previous['stopped'])
        b.db.execute("UPDATE sr_habit SET status='rejected',updated=? WHERE id=?", (now, hid))
    elif previous['kind'] == 'legacy' and old['status'] != 'rejected':
        count = b.db.execute('SELECT count(*) FROM sr_evidence WHERE habit=?', (hid,)).fetchone()[0]
        status = 'mature' if count >= 8 or (count >= 3 and old['positive'] >= 2) else 'trial' if count >= 3 else 'candidate'
        b.db.execute('UPDATE sr_habit SET status=?,updated=? WHERE id=?', (status, now, hid))


def learn(b, doc, lexical_candidates=None, style_candidates=None):
    lexical_candidates = [] if lexical_candidates is None else lexical_candidates
    style_candidates = [] if style_candidates is None else style_candidates
    if not isinstance(lexical_candidates, list) or len(lexical_candidates) > 8:
        raise ValueError('at_most_eight_lexical_candidates')
    if not isinstance(style_candidates, list) or len(style_candidates) > 3:
        raise ValueError('at_most_three_style_candidates')
    if not _enabled(b):
        return dict(ok=True, status='disabled', learned=0, habits=rows(b))
    doc = _document(b, doc['id'])
    checked = [_candidate(c, lexical=True) for c in lexical_candidates] + [_candidate(c) for c in style_candidates]
    for hid, proposed, quote in checked:
        if quote not in doc['quote']:
            raise ValueError('expression_evidence_not_in_observed_text')
        old=b.db.execute('SELECT * FROM sr_habit WHERE id=?',(hid,)).fetchone()
        if old:
            current=_profile(b,old)
            if current['kind'] in ('lexical','phrase') and not _matches(current,quote):
                raise ValueError('existing_expression_source_mismatch')
    for item in lexical_candidates + style_candidates:
        if item.get('existing_id') and not b.db.execute('SELECT 1 FROM sr_habit WHERE id=?', (item['existing_id'],)).fetchone():
            raise ValueError('existing_habit_not_found')
    with b.db:
        for hid, profile, quote in checked:
            b.db.execute('INSERT OR IGNORE INTO sr_evidence VALUES(?,?,?,?)', (hid, doc['url'], doc['id'], quote))
            _apply(b, hid, profile)
    return dict(ok=True, learned=len(checked), habits=rows(b))


def review(b, q):
    _scope(q)
    if not _enabled(b):
        return dict(ok=True, status='disabled', candidates=[])
    reviews = q.get('reviews')
    if reviews is None:
        candidates = [r for r in rows(b) if r['status'] == 'candidate' and r['source_proof']][:3]
        return dict(ok=True, candidates=candidates, authority='Same host model reviews actual archived quotes; no automatic promotion.')
    if not isinstance(reviews, list) or len(reviews) > 8:
        raise ValueError('at_most_eight_expression_reviews')
    checked = []
    for item in reviews:
        hid, profile, quote = _candidate(item)
        if profile['kind'] == 'legacy' or not b.db.execute('SELECT 1 FROM sr_habit WHERE id=?', (hid,)).fetchone():
            raise ValueError('existing_typed_habit_review_required')
        proofs = _source_proof(b, hid)
        if not any(quote in p['evidence_quote'] and
                   (not item.get('document_id') or item['document_id'] == p['document_id']) and
                   (not item.get('owner_event') or item['owner_event'] == p['owner_event']) for p in proofs):
            raise ValueError('review_requires_archived_habit_evidence')
        checked.append((hid, profile))
    with b.db:
        for hid, profile in checked:
            _apply(b, hid, profile, review=True)
    return dict(ok=True, reviewed=len(checked), habits=rows(b))


def teach(b, q):
    _scope(q)
    event = owner_event(b, q)
    if not _enabled(b):
        return dict(ok=True, status='disabled', learned=0, habits=rows(b))
    lexical, styles = q.get('lexical_candidates', []), q.get('style_candidates', [])
    if not isinstance(lexical, list) or len(lexical) > 8 or not isinstance(styles, list) or len(styles) > 3:
        raise ValueError('bounded_owner_teaching_required')
    checked = [_candidate(c, lexical=True) for c in lexical] + [_candidate(c) for c in styles]
    for _, profile, quote in checked:
        if profile['kind'] == 'legacy' or quote not in event['text']:
            raise ValueError('typed_teaching_requires_actual_owner_quote')
    replayed = 0
    with b.db:
        for hid, profile, quote in checked:
            payload = _json(dict(profile=profile, evidence_quote=quote))
            prior = b.db.execute("SELECT payload FROM sr_voice_feedback WHERE habit=? AND event=? AND kind='teach'",
                                 (hid, event['id'])).fetchone()
            if prior:
                if prior['payload'] != payload:
                    raise ValueError('owner_teaching_receipt_conflict')
                replayed += 1
                continue
            b.db.execute("INSERT INTO sr_voice_feedback VALUES(?,?,'teach',?)", (hid, event['id'], payload))
            b.db.execute('INSERT OR IGNORE INTO sr_owner_evidence VALUES(?,?,?)', (hid, event['id'], quote))
            profile['owner_fields'] = [k for k in profile if k != 'example']
            _apply(b, hid, profile, owner=True)
    return dict(ok=True, learned=len(checked) - replayed, replayed=bool(checked) and replayed == len(checked), habits=rows(b))


def feedback(b, q):
    _scope(q)
    event = owner_event(b, q)
    hid, kind = q.get('habit_id'), q.get('kind')
    habit = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()
    if not habit or kind not in ('meaning', 'context', 'tone', 'stop'):
        raise ValueError('typed_habit_feedback_required')
    if b.db.execute('SELECT 1 FROM sr_voice_feedback WHERE habit=? AND event=? AND kind=?', (hid, event['id'], kind)).fetchone():
        return dict(ok=True, replayed=True)
    profile = _profile(b, habit)
    correction = q.get('correction', {})
    if not isinstance(correction, dict):
        raise ValueError('expression_correction_object_required')
    allowed = dict(meaning={'meaning', 'understood', 'reason', 'form', 'variants', 'example'},
                   context={'triggers', 'scenes', 'targets', 'avoid_contexts'}, tone={'intensity', 'tone_limit'}, stop=set())[kind]
    if set(correction) - allowed or (kind != 'stop' and not correction):
        raise ValueError('correction_fields_do_not_match_feedback_kind')
    quote = text(q.get('evidence_quote', event['text'][:240]), 240, True)
    if quote not in event['text']:
        raise ValueError('feedback_quote_not_in_owner_message')
    updated = dict(profile)
    for key, value in correction.items():
        if key in ('variants', 'triggers', 'scenes', 'targets', 'avoid_contexts'):
            updated[key] = _list(value)
        elif key == 'intensity':
            updated[key] = _intensity(value)
        elif key == 'understood':
            if type(value) is not bool:
                raise ValueError('boolean_understanding_required')
            updated[key] = value
        else:
            updated[key] = text(value, 400 if key in ('meaning', 'reason') else 160, True)
    if kind == 'meaning':
        if 'meaning' not in correction:
            raise ValueError('corrected_meaning_required')
        updated['understood'] = correction.get('understood', True)
        if updated['kind'] == 'legacy':
            updated.update(kind='mechanism', variants=[], triggers=[], scenes=[], targets=[], intensity=50,
                           avoid_contexts=[], tone_limit='', reason=correction.get('reason', 'Owner meaning correction'))
        if 'form' in correction and updated['kind'] in ('lexical', 'phrase') and not _matches(updated, quote):
            raise ValueError('corrected_form_not_in_owner_quote')
    updated['owner_fields'] = sorted(set(profile.get('owner_fields', [])) | set(correction))
    _, related_stopped = _related_rejections(b, hid, updated)
    updated['stopped'] = profile['stopped'] or related_stopped or kind == 'stop'
    status = ('rejected' if updated['stopped'] or (habit['status'] == 'rejected' and kind != 'meaning') else
              habit['status'] if updated['kind'] == 'legacy' and kind in ('context', 'tone') else
              'trial' if updated.get('understood') else 'candidate')
    with b.db:
        b.db.execute('INSERT INTO sr_voice_feedback VALUES(?,?,?,?)', (hid, event['id'], kind, _json(dict(correction=correction, evidence_quote=quote))))
        _save_profile(b, hid, updated, updated['stopped'])
        b.db.execute('UPDATE sr_habit SET pattern=?,mechanism=?,example=?,status=?,updated=? WHERE id=?',
                     (updated['form'], updated['meaning'], updated['example'], status, time.time(), hid))
        if kind == 'meaning':
            b.db.execute('INSERT OR IGNORE INTO sr_owner_evidence VALUES(?,?,?)', (hid, event['id'], quote))
    return dict(ok=True, habit=_enrich(b, b.db.execute('SELECT * FROM sr_habit WHERE id=?', (hid,)).fetchone()))


def _output_id(chat, turn, seq):
    return 'native:' + _hash(_json([chat, turn, seq]))[:32]


def _output(row):
    return dict(output_id=row['id'], chat_id=row['chat_id'], turn_id=row['turn_id'], seq=row['seq'],
                occurred_at_ms=row['occurred_at_ms'], text=row['text'], text_hash=row['text_hash'])


def observe_outputs(b, outputs):
    """Only the bound native adapter supplies these receipts; never capture emotion."""
    if not _enabled(b):
        return dict(ok=True, status='disabled', outputs=[])
    if not isinstance(outputs, list) or len(outputs) > 20:
        raise ValueError('at_most_twenty_actual_native_outputs')
    checked = []
    for item in outputs:
        if not isinstance(item, dict):
            raise ValueError('actual_native_output_object_required')
        chat, turn = text(item.get('chat_id'), 200, True), text(item.get('turn_id'), 200, True)
        seq, occurred = item.get('seq'), item.get('occurred_at_ms')
        if type(seq) is not int or seq < 0 or type(occurred) is not int or occurred <= 0:
            raise ValueError('stable_native_output_metadata_required')
        body = item.get('text')
        text(body, 12000, True)  # Preserve original spacing in both hash and stored output.
        oid, digest = _output_id(chat, turn, seq), _hash(body)
        if item.get('output_id', oid) != oid or item.get('text_hash', digest) != digest:
            raise ValueError('native_output_identity_or_hash_mismatch')
        checked.append((oid, chat, turn, seq, occurred, body, digest))
    result = []
    with b.db:
        for values in checked:
            old = b.db.execute('SELECT * FROM sr_output WHERE id=?', (values[0],)).fetchone()
            if old and (old['text_hash'] != values[6] or old['occurred_at_ms'] != values[4] or old['text'] != values[5]):
                raise ValueError('native_output_receipt_conflict')
            b.db.execute('INSERT OR IGNORE INTO sr_output VALUES(?,?,?,?,?,?,?,?)', (*values, time.time()))
            saved=_output(b.db.execute('SELECT * FROM sr_output WHERE id=?', (values[0],)).fetchone())
            result.append({k:v for k,v in saved.items() if k!='text'})
    return dict(ok=True, outputs=result)


def _matches(profile, body):
    return any(v in body for v in [profile['form']] + profile.get('variants', []))


def _administrative(body):
    return body.lstrip().startswith(('［Codex调试］', '[Codex调试]'))


def _valid_receipt(row, profile):
    return bool(row and row['text_hash'] == _hash(row['text']) and
                row['id'] == _output_id(row['chat_id'], row['turn_id'], row['seq']) and
                not _administrative(row['text']) and
                row['evidence_quote'] in row['text'] and
                (profile['kind'] not in ('lexical', 'phrase') or _matches(profile, row['evidence_quote'])))


def _usage_proof(b, hid, profile):
    sql = '''SELECT o.*,u.evidence_quote,u.reason FROM sr_usage u JOIN sr_output o ON o.id=u.output
      WHERE u.habit=? AND u.appropriate=1 AND u.revision=?'''
    args = (hid, _revision(profile))
    found = list(b.db.execute(sql + ' ORDER BY o.occurred_at_ms DESC,o.seq DESC LIMIT 20', args))
    if found:
        first = found[0]
        other = b.db.execute(sql + ' AND (o.chat_id<>? OR o.turn_id<>?) ORDER BY o.occurred_at_ms DESC LIMIT 1',
                             (*args, first['chat_id'], first['turn_id'])).fetchone()
        if other and all(r['id'] != other['id'] for r in found):
            found = found[:19] + [other]
    return [dict(output_id=r['id'], chat_id=r['chat_id'], turn_id=r['turn_id'], seq=r['seq'],
                 occurred_at_ms=r['occurred_at_ms'], text_hash=r['text_hash'], evidence_quote=r['evidence_quote'],
                 appropriate=True) for r in found if _valid_receipt(r, profile)]


def _enrich(b, habit):
    item = dict(habit)
    item.setdefault('exposures', b.db.execute('SELECT count(*) FROM sr_evidence WHERE habit=?', (habit['id'],)).fetchone()[0])
    profile = _profile(b, habit)
    related_rejected, related_stopped = _related_rejections(b, habit['id'], profile)
    profile['stopped'] = profile['stopped'] or related_stopped
    if related_rejected or profile['stopped']:
        item['status'] = 'rejected'
    elif profile.get('usage_mode')=='reference_only':
        item['status']='reference'
    proof = _usage_proof(b, habit['id'], profile)
    counts = b.db.execute('''SELECT count(*),count(DISTINCT o.chat_id || char(0) || o.turn_id)
      FROM sr_usage u JOIN sr_output o ON o.id=u.output WHERE u.habit=? AND u.appropriate=1 AND u.revision=?''',
                         (habit['id'], _revision(profile))).fetchone()
    lineage = _source_proof(b, habit['id'])
    feedback_rows = [dict(r) for r in b.db.execute('''SELECT event owner_event,kind,payload FROM sr_voice_feedback
      WHERE habit=? ORDER BY event DESC LIMIT 3''', (habit['id'],))]
    correction_count = b.db.execute("SELECT count(*) FROM sr_voice_feedback WHERE habit=? AND kind IN ('meaning','context','tone')",
                                    (habit['id'],)).fetchone()[0]
    item.update(profile, revision=_revision(profile), uses=counts[0], native_turns=counts[1],
                last_used=max((p['occurred_at_ms'] / 1000 for p in proof), default=None),
                correction_count=correction_count, feedback=feedback_rows,
                source_proof=lineage, source_lineage=lineage, usage_proof=proof, usage_revision=_hash(_json(proof)))
    return item


def rows(b):
    return [_enrich(b, r) for r in b.db.execute('SELECT * FROM sr_habit ORDER BY updated DESC LIMIT 40')]


def _relevance(item, q):
    parts = [q.get(k, '') for k in ('text', 'current_text', 'scene', 'context') if isinstance(q.get(k, ''), str)]
    context = ' '.join(parts).casefold()[:8000]
    if any(v.casefold() in context for v in item.get('avoid_contexts', [])):
        return -1
    score = 6 if _matches(item, ' '.join(parts)) else 0
    score += sum(2 for v in item.get('scenes', []) + item.get('triggers', []) if v.casefold() in context)
    return score


def voice(b, q=None):
    q = {} if q is None else q
    _scope(q)
    if not _enabled(b):
        return []
    eligible = [r for r in rows(b) if r['status'] in ('trial', 'mature') and not r['stopped'] and r['source_proof']
                and r.get('usage_mode')!='reference_only']
    # Untyped legacy mechanisms keep their previous broad-context behavior until reviewed.
    ranked = [(r, _relevance(r, q)) for r in eligible]
    ranked = [(r, score) for r, score in ranked if score >= 0]
    seed=str(q.get('event_id',q.get('text','')))
    ranked.sort(key=lambda pair: (pair[1], pair[0]['status'] == 'mature',-pair[0]['uses'],
                                 _hash(seed+pair[0]['id'])), reverse=True)
    fresh = [r for r, _ in ranked if r['status'] == 'trial'][:2]
    chosen = fresh + [r for r, _ in ranked if r['id'] not in {v['id'] for v in fresh}][:6 - len(fresh)]
    return [dict(id=r['id'], hint=r['form'], form=r['form'], kind=r['kind'], meaning=r['meaning'],
                 example=r['example'], variants=r.get('variants', []), scenes=r.get('scenes', []),
                 triggers=r.get('triggers', []), targets=r.get('targets', []), intensity=r.get('intensity'),
                 avoid_contexts=r.get('avoid_contexts', []), tone_limit=r.get('tone_limit', ''), status=r['status'],
                 uses=r['uses'], strength=round(min(.7, .15 + .05 * r['uses']), 2)) for r in chosen]


def usage_work(b, q):
    _scope(q)
    if not _enabled(b):
        return dict(ok=True, outputs=[])
    eligible = [r for r in rows(b) if r['status'] in ('trial', 'mature') and not r['stopped'] and r['source_proof']]
    result = []
    for output in b.db.execute('SELECT * FROM sr_output ORDER BY occurred_at_ms DESC,seq DESC LIMIT 20'):
        if _administrative(output['text']):
            continue
        possible = [r for r in eligible if (r['kind'] not in ('lexical', 'phrase') or _matches(r, output['text']))
                    and not b.db.execute('SELECT 1 FROM sr_usage WHERE habit=? AND output=?', (r['id'], output['id'])).fetchone()][:6]
        if possible:
            result.append(dict(_output(output), habit_ids=[r['id'] for r in possible],
                               possible_habits=[dict(id=r['id'], kind=r['kind'], form=r['form'], meaning=r['meaning'],
                                 scenes=r.get('scenes', []), targets=r.get('targets', []), intensity=r.get('intensity'),
                                 avoid_contexts=r.get('avoid_contexts', []), tone_limit=r.get('tone_limit', '')) for r in possible]))
        if len(result) == 3:
            break
    return dict(ok=True, outputs=result, authority='Same host model judges actual output context and tone. '
                'Administrative reports, definitions and quoted source text are not casual adoption. Silence is not positive feedback.')


def record_use(b, q):
    _scope(q)
    if not _enabled(b):
        return dict(ok=True, status='disabled')
    habit = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (q.get('habit_id'),)).fetchone()
    output = b.db.execute('SELECT * FROM sr_output WHERE id=?', (q.get('output_id'),)).fetchone()
    if not habit or not output or type(q.get('appropriate')) is not bool:
        raise ValueError('actual_output_habit_and_boolean_judgment_required')
    profile = _profile(b, habit)
    related_rejected, related_stopped = _related_rejections(b, habit['id'], profile)
    profile['stopped'] = profile['stopped'] or related_stopped
    quote, reason = text(q.get('evidence_quote'), 240, True), text(q.get('reason', ''), 400)
    receipt = dict(output, evidence_quote=quote)
    if not _valid_receipt(receipt, profile):
        raise ValueError('usage_requires_exact_actual_expression_quote')
    old = b.db.execute('SELECT * FROM sr_usage WHERE habit=? AND output=?', (habit['id'], output['id'])).fetchone()
    values = (quote, int(q['appropriate']), reason, _revision(profile))
    if old:
        if (old['evidence_quote'], old['appropriate'], old['reason'], old['revision']) != values:
            raise ValueError('actual_usage_judgment_conflict')
        return dict(ok=True, replayed=True)
    if (related_rejected or profile['stopped'] or profile.get('usage_mode')=='reference_only' or
            habit['status'] not in ('trial', 'mature') or not _source_proof(b, habit['id'])):
        raise ValueError('active_trial_habit_required')
    with b.db:
        b.db.execute('INSERT INTO sr_usage VALUES(?,?,?,?,?,?,?)', (habit['id'], output['id'], *values, time.time()))
        current = _enrich(b, habit)
        if profile['kind'] != 'legacy' and current['uses'] >= 3 and current['native_turns'] >= 2:
            b.db.execute("UPDATE sr_habit SET status='mature',updated=? WHERE id=?", (time.time(), habit['id']))
    return dict(ok=True, habit=_enrich(b, b.db.execute('SELECT * FROM sr_habit WHERE id=?', (habit['id'],)).fetchone()))


def qualified_habits(b):
    if not _enabled(b):
        return []
    mature = [_enrich(b, r) for r in b.db.execute("SELECT * FROM sr_habit WHERE status='mature' ORDER BY updated DESC")]
    return [r for r in mature if r['status'] == 'mature' and not r['stopped'] and r['source_proof'] and
            r['uses'] >= 3 and r['native_turns'] >= 2 and len(r['usage_proof']) >= 3 and
            len({(p['chat_id'], p['turn_id']) for p in r['usage_proof']}) >= 2]


def verified_usage(b, habit_id, proof):
    """Validate historical proof even after it leaves a bounded work projection."""
    if not isinstance(proof, dict):
        return False
    habit = b.db.execute('SELECT * FROM sr_habit WHERE id=?', (habit_id,)).fetchone()
    if not habit:
        return False
    profile = _profile(b, habit)
    if profile['stopped'] or _related_rejections(b, habit_id, profile)[0]:
        return False
    row = b.db.execute('''SELECT o.*,u.evidence_quote,u.revision,u.appropriate FROM sr_usage u
      JOIN sr_output o ON o.id=u.output WHERE u.habit=? AND u.output=?''', (habit_id, proof.get('output_id'))).fetchone()
    if not row or not row['appropriate'] or row['revision'] != _revision(profile) or not _valid_receipt(row, profile):
        return False
    actual = dict(output_id=row['id'], chat_id=row['chat_id'], turn_id=row['turn_id'], seq=row['seq'],
                  occurred_at_ms=row['occurred_at_ms'], text_hash=row['text_hash'], evidence_quote=row['evidence_quote'], appropriate=True)
    return all(proof.get(k) == value for k, value in actual.items())


def verified_source(b, habit_id, proof):
    """Validate an archived lineage reference outside the bounded recent list."""
    if not isinstance(proof, dict):
        return False
    habit=b.db.execute('SELECT * FROM sr_habit WHERE id=?',(habit_id,)).fetchone()
    if not habit:return False
    profile=_profile(b,habit)
    if profile['kind'] in ('lexical','phrase') and not _matches(profile,proof.get('evidence_quote','')):
        return False
    if proof.get('owner_event') is not None:
        row = b.db.execute('''SELECT oe.event,oe.quote,e.text FROM sr_owner_evidence oe JOIN source_events e
          ON e.id=oe.event AND e.status='active' AND e.actor='user' AND e.scope='owner-private'
          WHERE oe.habit=? AND oe.event=?''', (habit_id, proof['owner_event'])).fetchone()
        if not row or not row['quote'] or row['quote'] not in row['text']:
            return False
        actual = dict(document_id=None, url='owner-event:' + str(row['event']), source_event=row['event'],
                      quote_id=None, evidence_quote=row['quote'], owner_event=row['event'])
    else:
        row = b.db.execute('''SELECT d.id,d.url,d.event,d.quote_id,d.quote actual_quote,e.quote FROM sr_evidence e
          JOIN sr_document d ON d.id=e.document JOIN source_events se ON se.id=d.event
          AND se.status='active' AND se.actor='article' AND se.scope='owner-private'
          WHERE e.habit=? AND e.document=? AND e.url=?''',
                           (habit_id, proof.get('document_id'), proof.get('url'))).fetchone()
        if not row or not row['quote'] or row['quote'] not in row['actual_quote']:
            return False
        actual = dict(document_id=row['id'], url=row['url'], source_event=row['event'],
                      quote_id=row['quote_id'], evidence_quote=row['quote'], owner_event=None)
    return all(proof.get(k) == value for k, value in actual.items())
