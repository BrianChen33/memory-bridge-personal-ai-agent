"""Source-bound, once-per-turn sticker decisions. No network or media sender.

The trusted host resolves intent from the actual message and supplies receipts.
This module cannot authenticate a platform sender or prove client visibility.
"""
import hashlib
import json
import math
import secrets
import time
from pathlib import Path

from brain import config_guard
from .stickers_policy import DEFAULT_POLICY
from .emotion import LABELS


def number(value, low, high):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def intensity(mood):
    if (not isinstance(mood, dict) or mood.get('ok') is not True
            or mood.get('disabled') is True
            or any(not number(mood.get(k), -1, 1) for k in ('p', 'a', 'd'))):
        return None
    labels = mood.get('labels', [])
    if not isinstance(labels, list):
        return None
    label_i = max((r['intensity']/.6 for r in labels
                   if isinstance(r, dict) and r.get('label') in LABELS
                   and number(r.get('intensity'), .01, .6)
                   and r['intensity'] > .01), default=0)
    return min(1., max(math.sqrt(sum(mood[k]**2 for k in ('p', 'a', 'd'))/3), label_i))


def _json_file(path, limit=1024*1024):
    path = Path(path)
    if path.is_symlink() or path.stat().st_size > limit:
        raise ValueError('invalid_sticker_file')
    return json.loads(path.read_text(encoding='utf-8'))


def policy(root):
    p = _json_file(root/'sticker-policy.json')
    if (not isinstance(p, dict) or type(p.get('version')) is not int or p['version'] != 1
            or type(p.get('enabled')) is not bool
            or type(p.get('share_owner_mood')) is not bool
            or not number(p.get('base_probability'), 0, 1)
            or not number(p.get('max_probability'), p['base_probability'], 1)):
        raise ValueError('invalid_sticker_policy')
    return p


def _initialize(db):
    db.execute('''CREATE TABLE IF NOT EXISTS sticker_turns(
      event_id INTEGER PRIMARY KEY, scope TEXT NOT NULL, epoch INTEGER NOT NULL,
      decision_json TEXT NOT NULL, selection_json TEXT, delivery TEXT,
      text_receipts_json TEXT, receipt_id TEXT, handed_at REAL)''')
    db.commit()


def _event(brain, q):
    source, eid, actor = q.get('source'), q.get('event_id'), q.get('actor', 'user')
    if not isinstance(source, str) or not isinstance(eid, str):
        raise ValueError('sticker_source_metadata_required')
    row = brain.db.execute('''SELECT * FROM source_events WHERE scope=?
        AND source=? AND event_id=? AND actor=? AND status='active' ''',
        (q['scope'], source, eid, actor)).fetchone()
    if not row:
        raise ValueError('active_sticker_source_required')
    return row


def _catalog(brain):
    doc = _json_file(brain.root/'sticker-catalog.json')
    if (not isinstance(doc, dict) or type(doc.get('version')) is not int or doc['version'] != 1
            or not isinstance(doc.get('items'), list) or len(doc['items']) > 1000):
        raise ValueError('invalid_sticker_catalog')
    registry = _json_file(brain.root/'backup-sources.json').get('sources', [])
    registered = {r.get('name'): r for r in registry if isinstance(r, dict)}
    result, errors, seen = [], [], set()
    for entry in doc['items']:
        try:
            if not isinstance(entry, dict):
                raise ValueError('invalid_entry')
            sid, rel = entry.get('id'), entry.get('path')
            if not isinstance(sid, str) or not sid or len(sid) > 128 or sid in seen:
                raise ValueError('invalid_or_duplicate_id')
            seen.add(sid)
            if not isinstance(rel, str) or '\\' in rel:
                raise ValueError('invalid_path')
            path = brain.root/rel
            if (not path.resolve().is_relative_to(brain.root/'media/stickers')
                    or any(p.is_symlink() for p in (path, *path.parents))):
                raise ValueError('unsafe_media_path')
            if path.suffix.lower().lstrip('.') != entry.get('format'):
                raise ValueError('format_mismatch')
            if (entry.get('reviewed') is not True or not isinstance(entry.get('license'), str)
                    or not entry['license'].strip()):
                raise ValueError('license_review_required')
            for key in ('emotion', 'tags', 'use'):
                if (not isinstance(entry.get(key), list) or len(entry[key]) > 32
                        or any(not isinstance(x, str) or len(x) > 100 for x in entry[key])):
                    raise ValueError('invalid_media_tags')
            if path.stat().st_size > 8*1024*1024:
                raise ValueError('media_too_large')
            raw = path.read_bytes()
            fmt = entry['format']
            signatures = {'png': raw.startswith(b'\x89PNG\r\n\x1a\n'),
                          'jpg': raw.startswith(b'\xff\xd8\xff'),
                          'jpeg': raw.startswith(b'\xff\xd8\xff'),
                          'gif': raw.startswith((b'GIF87a', b'GIF89a')),
                          'webp': raw.startswith(b'RIFF') and raw[8:12] == b'WEBP'}
            if not signatures.get(fmt) or hashlib.sha256(raw).hexdigest() != entry.get('sha256'):
                raise ValueError('media_hash_or_signature_mismatch')
            registered_entry = registered.get('project/'+rel)
            if (not registered_entry or registered_entry.get('required') is not True
                    or Path(registered_entry.get('path', '')).resolve() != path.resolve()):
                raise ValueError('media_backup_registration_required')
            result.append(dict(entry, absolute_path=str(path.resolve())))
        except (ValueError, OSError, TypeError) as exc:
            errors.append(dict(index=len(result)+len(errors), reason=str(exc)[:100]))
    return result, errors


def _result(row, replayed=False):
    return dict(ok=True, **json.loads(row['decision_json']), replayed=replayed,
                send_once=False,
                selection=json.loads(row['selection_json']) if row['selection_json'] else None,
                delivery=row['delivery'])


def dispatch(brain, q):
    action = q.get('action')
    if action not in ('decide', 'candidates', 'select', 'handoff', 'receipt', 'status'):
        raise ValueError('invalid_sticker_action')
    if action == 'decide' and q.get('control') is True:
        return dict(ok=True, status='control_skipped', should_send=False, u=None)
    # Same lock order as configure/digest paths. A pause cannot race a handoff.
    with config_guard(brain.root):
        cfg = brain.config()
        p = policy(brain.root) if action not in ('status', 'receipt') else None
        if action not in ('status', 'receipt') and (cfg.get('enabled') is not True or p['enabled'] is not True):
            return dict(ok=False, status='disabled', should_send=False)
        _initialize(brain.db)
        event = _event(brain, q)
        with brain.db:
            brain.db.execute('BEGIN IMMEDIATE')
            row = brain.db.execute('SELECT * FROM sticker_turns WHERE event_id=?', (event['id'],)).fetchone()
            if action == 'decide':
                if row:
                    return _result(row, True)
                assessed = brain.db.execute('SELECT 1 FROM assessment_log WHERE event_id=?',
                                            (event['id'],)).fetchone()
                explicitly_off = (cfg.get('modules', {}).get('mood') is False
                                  or cfg.get('features', {}).get('emotion_events') is False)
                if not assessed and not explicitly_off:
                    return dict(ok=False, status='assessment_required', should_send=False)
                intent = q.get('intent', {'mode': 'auto'})
                if not isinstance(intent, dict) or intent.get('mode') not in ('direct', 'skip', 'auto'):
                    raise ValueError('invalid_sticker_intent')
                mode = intent['mode']
                if mode != 'auto':
                    evidence = intent.get('evidence')
                    if (event['actor'] != 'user' or not isinstance(evidence, str)
                            or not evidence.strip() or evidence not in event['text']):
                        raise ValueError('explicit_intent_needs_actual_user_quote')
                local = brain.dispatch(dict(op='mood', scope=q['scope']))
                values = [intensity(local)]
                if p['share_owner_mood'] and q['scope'] != 'owner-private':
                    values.append(intensity(brain.dispatch(dict(op='mood', scope='owner-private'))))
                available = [v for v in values if v is not None]
                level = max(available, default=0.)
                probability = p['base_probability']+(p['max_probability']-p['base_probability'])*level
                draw = secrets.SystemRandom().random() if mode == 'auto' else None
                hit = mode == 'direct' or (mode == 'auto' and draw < probability)
                decision = dict(status='decided', mode=mode, probability=probability,
                                u=draw, should_send=hit, intensity=level,
                                mood_status='available' if available else 'unavailable',
                                policy_sha256=hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest(),
                                at=time.time())
                brain.db.execute('INSERT INTO sticker_turns(event_id,scope,epoch,decision_json) VALUES(?,?,?,?)',
                                 (event['id'], q['scope'], cfg['epoch'], json.dumps(decision)))
                return dict(ok=True, **decision, replayed=False, send_once=False)
            if not row:
                return dict(ok=False, status='decision_required')
            if action == 'status':
                return _result(row)
            if action == 'receipt':
                outcome, receipt = q.get('outcome'), q.get('receipt_id')
                if outcome not in ('accepted', 'visible', 'failed') or not isinstance(receipt, str) or not 0 < len(receipt) <= 256:
                    raise ValueError('actual_media_receipt_required')
                if row['delivery'] == outcome and row['receipt_id'] == receipt:
                    return dict(ok=True, status=outcome, replayed=True)
                if row['delivery'] not in ('unknown', 'accepted'):
                    return dict(ok=False, status='terminal_or_no_handoff')
                brain.db.execute('UPDATE sticker_turns SET delivery=?,receipt_id=? WHERE event_id=?',
                                 (outcome, receipt, event['id']))
                return dict(ok=True, status=outcome)
            if row['epoch'] != cfg['epoch']:
                return dict(ok=False, status='stale_epoch')
            if not json.loads(row['decision_json'])['should_send']:
                return dict(ok=True, status='not_selected', should_send=False)
            if row['delivery'] is not None:
                return dict(ok=False, status='already_handed_off', delivery=row['delivery'], retry=False)
            entries, errors = _catalog(brain)
            if action == 'candidates':
                tags = q.get('tags', [])
                if not isinstance(tags, list) or len(tags) > 32 or any(not isinstance(t, str) for t in tags):
                    raise ValueError('invalid_candidate_tags')
                # Ranking only; never a second lottery or a minimum-match gate.
                wanted = set(tags)
                entries.sort(key=lambda e: (-len(wanted.intersection(e['tags']+e['emotion']+e['use'])), e['id']))
                return dict(ok=bool(entries), status='candidates' if entries else 'no_available_media',
                            candidates=entries[:12], catalog_errors=errors)
            chosen = json.loads(row['selection_json']) if row['selection_json'] else None
            if action == 'select':
                sid = q.get('sticker_id')
                if chosen:
                    return dict(ok=chosen['id'] == sid, status='selected' if chosen['id'] == sid else 'selection_conflict',
                                selection=chosen, replayed=True)
                selected = next((e for e in entries if e['id'] == sid), None)
                if selected is None:
                    return dict(ok=False, status='no_available_media', catalog_errors=errors)
                chosen = {k: selected[k] for k in ('id', 'path', 'format', 'sha256')}
                brain.db.execute('UPDATE sticker_turns SET selection_json=? WHERE event_id=?',
                                 (json.dumps(chosen), event['id']))
                return dict(ok=True, status='selected', selection=chosen)
            # handoff: persist unknown before returning one permission to send.
            if chosen is None:
                return dict(ok=False, status='selection_required')
            current = next((e for e in entries if all(e.get(k) == v for k, v in chosen.items())), None)
            if current is None:
                return dict(ok=False, status='selected_media_unavailable', catalog_errors=errors)
            receipts = q.get('text_receipts')
            if (q.get('texts_complete') is not True or not isinstance(receipts, list) or not receipts
                    or len(receipts) > 100 or any(not isinstance(r, str) or not 0 < len(r) <= 256 for r in receipts)):
                return dict(ok=False, status='all_text_receipts_required')
            if event['actor'] != 'user':
                gate = brain._proactive_gate_in_lock()
                if gate:
                    return gate
            brain.db.execute('UPDATE sticker_turns SET delivery=?,text_receipts_json=?,handed_at=? WHERE event_id=?',
                             ('unknown', json.dumps(receipts), time.time(), event['id']))
            return dict(ok=True, status='unknown', send_once=True,
                        media_path=current['absolute_path'], sha256=current['sha256'],
                        meaning='host_must_send_once_not_a_delivery_receipt')
