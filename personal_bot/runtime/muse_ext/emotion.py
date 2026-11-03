"""Model-judged tone assessments (v1 protocol). Validate + store only.

No keyword heuristics: the model judges every turn from input, recent context,
persona and current mood, and submits a structured assessment. This module only
validates the assessment envelope and persists it. It never infers emotion from
word lists and never stores the model's full thinking/reasons.

Protocol: emotion_assessment = {
    version: 1,
    changed: bool,                 # False => evaluated, no change
    label: str | null,             # one of LABELS when changed, else null
    delta: {p: float, a: float, d: float},
    intensity_delta: float,        # signed change applied to decayed intensity
}
Rules:
  - all numbers finite reals, not bool; |PAD delta| <= 0.12; |intensity_delta| <= 0.12
  - changed=False requires label null, delta all 0, intensity_delta 0;
    records "evaluated, no change" WITHOUT touching mood/labels/at
  - changed=True requires at least one non-zero change
  - intensity update: clamp(decayed_old + intensity_delta, 0, 0.6);
    NO +0.1 base is added (zero amplitude stays zero)
  - half-lives kept: mood 6h (21600s), labels 45min (2700s)

Statuses: updated / unchanged / replayed / conflict / missing / invalid /
          disabled / ignored
  - missing/invalid do NOT consume the event's assessment opportunity:
    a later valid submit for the same event_id still works.
  - replayed: identical assessment resubmitted -> no re-apply, no accumulation.
  - conflict: a different assessment after one was recorded -> original kept.
"""
import json
import math
import time

ASSESSMENT_VERSION = 1
LABELS = ('欣喜', '难过', '委屈', '生气', '害羞', '期待',
          '关切', '专注', '放松', '失落', '好奇', '平静')
PAD_KEYS = ('p', 'a', 'd')
MAX_DELTA = 0.12
MOOD_HALFLIFE = 21600.0
LABEL_HALFLIFE = 2700.0
LABEL_MAX = 0.6

# Short, tone-only candidate notes for threshold crossing (no reasoning stored).
_NOTES = {
    '欣喜': '刚才的交流让我有些开心，想和你分享这一点。',
    '专注': '刚才的交流让我更专注了，我想认真把事情弄准确。',
    '关切': '读到刚才的近况，我有些挂念，想关心一下你。',
    '委屈': '刚才被误会了，有点小委屈，但没关系。',
    '期待': '听到好消息，我很为你期待！',
    '难过': '刚才的交流让我有些难过，想安静陪你一会儿。',
    '生气': '刚才的事让我有点生气，不过我会控制好语气。',
    '害羞': '刚才的交流让我有点害羞。',
    '放松': '刚才的交流让我很放松。',
    '失落': '刚才的交流让我有点失落，想缓一缓。',
    '好奇': '刚才的交流勾起了我的好奇心，想多知道一点。',
    '平静': '刚才的交流让我很平静，像浮在无风的海面上。',
}


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _validate_assessment(a):
    """Returns (ok, error, clean). clean={changed,label,delta,intensity_delta}.

    Strict v1: version must be non-bool int 1 (True==1 is rejected);
    delta must contain ALL PAD keys; intensity_delta must be present.
    No silent defaults: missing/invalid -> 'invalid', no state change,
    assessment opportunity preserved.
    """
    if not isinstance(a, dict):
        return False, 'not_a_dict', None
    v = a.get('version')
    if type(v) is not int or v != ASSESSMENT_VERSION:
        return False, 'bad_version', None
    changed = a.get('changed')
    if not isinstance(changed, bool):
        return False, 'bad_changed', None
    delta = a.get('delta')
    if not isinstance(delta, dict):
        return False, 'bad_delta', None
    clean_delta = {}
    for k in PAD_KEYS:
        if k not in delta:
            return False, 'bad_delta', None
        dv = delta[k]
        if not _is_num(dv) or abs(dv) > MAX_DELTA:
            return False, 'bad_delta_value', None
        clean_delta[k] = float(dv)
    if 'intensity_delta' not in a:
        return False, 'bad_intensity_delta', None
    idelta = a['intensity_delta']
    if not _is_num(idelta) or abs(idelta) > MAX_DELTA:
        return False, 'bad_intensity_delta', None
    idelta = float(idelta)
    label = a.get('label')
    if changed:
        if label not in LABELS:
            return False, 'bad_label', None
        if all(v == 0 for v in clean_delta.values()) and idelta == 0:
            return False, 'changed_but_empty', None
    else:
        if label is not None or any(v != 0 for v in clean_delta.values()) or idelta != 0:
            return False, 'unchanged_must_be_empty', None
    return True, None, {'changed': changed, 'label': label,
                        'delta': clean_delta, 'intensity_delta': idelta}


def _same_assessment(prev_row, clean):
    try:
        prev = {'changed': bool(prev_row['changed']), 'label': prev_row['label'],
                'delta': json.loads(prev_row['delta_json']),
                'intensity_delta': float(prev_row['intensity_delta'])}
    except Exception:
        return False
    return (prev['changed'] == clean['changed'] and prev['label'] == clean['label']
            and prev['delta'] == clean['delta']
            and prev['intensity_delta'] == clean['intensity_delta'])


def submit_assessment(brain, event_id, raw):
    """Validate + persist a model assessment for one source event.

    Idempotent per event_id: first valid submit wins; identical resubmit ->
    'replayed' (no re-apply); different submit after recorded -> 'conflict'.
    """
    # v1 explicit-disable gate (2026-11-04): honest 'disabled_by_config' with
    # ZERO writes, taken ONLY when the trusted local config actually reads as
    # off. Config corruption / transient errors surface as errors, never as
    # disabled; model input cannot self-claim disabled (this reads brain.config,
    # never the assessment payload).
    try:
        _cfg = brain.config()
    except Exception:
        return {'status': 'error', 'error': 'config_unreadable'}
    if not isinstance(_cfg, dict):
        return {'status': 'error', 'error': 'config_unreadable'}
    if _cfg.get('enabled', True) is False:
        return {'status': 'disabled_by_config'}
    _feats = _cfg.get('features')
    if not isinstance(_feats, dict):
        return {'status': 'error', 'error': 'features_unreadable'}
    if _feats.get('emotion_events', True) is False:
        return {'status': 'disabled_by_config'}
    if not brain.available('mood'):
        return {'status': 'error', 'error': 'mood_unavailable'}
    if not event_id:
        return {'status': 'missing', 'error': 'no_event'}
    ok, err, clean = _validate_assessment(raw)
    if not ok:
        return {'status': 'invalid', 'error': err}
    with brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        row = brain.db.execute(
            "SELECT * FROM source_events WHERE id=? AND status='active'",
            (event_id,)).fetchone()
        if not row:
            return {'status': 'missing', 'error': 'event_not_found'}
        # The portable core accepts actual user events. Other incoming actors
        # require a separately authorized host adapter; a source string alone
        # is not authentication. Assistant/article output must not self-excite.
        if clean['changed'] and row['actor'] != 'user':
            return {'status': 'ignored'}
        prev = brain.db.execute(
            'SELECT * FROM assessment_log WHERE event_id=?', (event_id,)).fetchone()
        if prev:
            if _same_assessment(prev, clean):
                return {'status': 'replayed'}
            return {'status': 'conflict'}
        # Upgraded roots can already contain a v0.2 keyword-driven update for
        # this historical event. Preserve it without fabricating a new model
        # assessment or applying the event twice. New events use v1 normally.
        if brain.db.execute('SELECT 1 FROM emotion_events WHERE event_id=?',
                            (event_id,)).fetchone():
            return {'status': 'legacy_recorded', 'source_event': event_id}
        now = time.time()
        scope = row['scope']
        if not clean['changed']:
            brain.db.execute(
                'INSERT INTO assessment_log(event_id,scope,changed,label,delta_json,'
                'intensity_delta,evidence,at) VALUES(?,?,?,?,?,?,?,?)',
                (event_id, scope, 0, None, json.dumps(clean['delta']),
                 0.0, 'inference', now))
            return {'status': 'unchanged'}
        # changed=True: apply bounded updates
        old = brain.db.execute('SELECT * FROM mood WHERE scope=?', (scope,)).fetchone()
        decay = .5 ** (max(0, now - old['at']) / MOOD_HALFLIFE) if old else 1
        vals = {k: max(-1, min(1, (old[k] * decay if old else 0) + clean['delta'][k]))
                for k in PAD_KEYS}
        brain.db.execute('INSERT OR REPLACE INTO mood VALUES(?,?,?,?,?)',
                         (scope, vals['p'], vals['a'], vals['d'], now))
        label = clean['label']
        old_label = brain.db.execute(
            'SELECT * FROM emotion WHERE scope=? AND label=?', (scope, label)).fetchone()
        decayed = (old_label['intensity'] * .5 ** (max(0, now - old_label['at']) / LABEL_HALFLIFE)
                   if old_label else 0.0)
        # Signed model update on decayed intensity; range kept; NO +0.1 base.
        new_intensity = max(0.0, min(LABEL_MAX, decayed + clean['intensity_delta']))
        # Minimal, non-leaking reason: assessment link only, no thinking stored.
        reason = 'inference:model_assessment:' + str(event_id)
        if old_label or new_intensity > 0:
            brain.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)',
                             (scope, label, new_intensity, reason, now))
        brain.db.execute('INSERT INTO emotion_events VALUES(?,?,?,?,?,?)',
                         (event_id, scope, label, json.dumps(clean['delta']),
                          'inference', now))
        brain.db.execute(
            'INSERT INTO assessment_log(event_id,scope,changed,label,delta_json,'
            'intensity_delta,evidence,at) VALUES(?,?,?,?,?,?,?,?)',
            (event_id, scope, 1, label, json.dumps(clean['delta']),
             clean['intensity_delta'], 'inference', now))
        # Threshold crossing -> life candidate (model-driven now; mechanism kept).
        if (scope == 'owner-private' and decayed < .25 <= new_intensity
                and brain._enqueue_gate() is None):
            mid = brain._remember(dict(scope=scope, text=row['text'], source=row['source'],
                                       event_id=row['event_id'], occurred_at=row['occurred_at'],
                                       kind='episode', evidence='observed', importance=.55))
            topic = 'emotion:' + label + ':event:' + str(event_id)
            fp = 'emotion-event:' + str(event_id)
            note = _NOTES.get(label, '刚才的交流让我有些' + label + '，想和你分享这一点。')
            brain.db.execute(
                'INSERT OR IGNORE INTO candidates(scope,text,sources,topic,fingerprint,'
                'created_at) VALUES(?,?,?,?,?,?)',
                (scope, note, json.dumps([mid]), topic, fp, now))
    return {'status': 'updated', 'label': clean['label'],
            'source_event': event_id, 'evidence': 'inference'}


# Backwards-compat shim: old callers pass no assessment; the v1 protocol has no
# keyword path. Kept only so imports don't break; always reports no assessment.
def observe_event(brain, event_id, assessment=None):
    if assessment is None:
        return {'status': 'missing'}
    return submit_assessment(brain, event_id, assessment)
