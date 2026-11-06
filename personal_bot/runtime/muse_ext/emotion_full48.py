"""Complete model appraisals and event receipts; no inference or model call."""
import copy
import json
import math

from muse_ext.emotion_catalog import LABELS, GROUPS

FORMAT = 'full48-v1'
COMPACT_FORMAT = 'compact48-v1'
INPUT_FORMATS = (FORMAT, COMPACT_FORMAT)
REFERENCE_GAIN = 1.5
# Replaces the previous guidance at the same prepare point, not another model pass.
APPRAISAL_GUIDANCE = (
    'Same model, one pass. Appraise events against persona, needs, energy and expectations, not the reply the user wants. '
    'Cooperation alone is not joy; do not mirror user affect. Use returned48 template; unchanged=0, neutral/mixed valid. '
    'No default joy/curiosity, rotation, quotas or random moods. '
    'Comfort eases relevant feelings; preserve other mood. Let reaction and residual mood shape wording, including dissent without lost affection. '
    'Raw deltas; gain once.')
# Fixed pre-gain budgets: changing the user's gain still changes the reaction.
BUDGETS = {
    'ordinary': dict(component=.03/REFERENCE_GAIN, total=.06/REFERENCE_GAIN, pad=.03/REFERENCE_GAIN),
    'salient': dict(component=.2/REFERENCE_GAIN, total=.4/REFERENCE_GAIN, pad=.2/REFERENCE_GAIN),
}


def initialize(b):
    b.db.execute('CREATE TABLE IF NOT EXISTS ct_emotion_full48('
                 'event INTEGER PRIMARY KEY,scope TEXT NOT NULL,payload TEXT NOT NULL,at REAL NOT NULL)')


def template():
    return dict(version=2, format=FORMAT, impact='ordinary', delta=dict(p=0, a=0, d=0),
                emotion_deltas=dict.fromkeys(LABELS, 0),
                appraisal=dict(kind='other', target='self', agency='none', certainty=.5,
                               feeling='', action='neutral'))


def compact_template():
    """Same48 vocabulary; omit zero entries on input, never on stored receipts."""
    value=template()
    value.update(format=COMPACT_FORMAT,emotion_deltas={})
    return value


def normalize(raw):
    """Validate the complete vector before deriving compatibility fields."""
    clean = copy.deepcopy(raw)
    if clean.get('format') not in INPUT_FORMATS:
        raise ValueError('format:expected_full48-v1_or_compact48-v1')
    values = clean.get('emotion_deltas')
    if clean.get('format') == COMPACT_FORMAT:
        if not isinstance(values,dict) or not set(values).issubset(LABELS):
            raise ValueError('emotion_deltas:only_canonical_48_labels_allowed')
        values={label:values.get(label,0) for label in LABELS}
        clean.update(format=FORMAT,emotion_deltas=values)
    if not isinstance(values, dict) or set(values) != set(LABELS):
        raise ValueError('emotion_deltas:exactly_all_48_canonical_labels_required')
    if clean.get('impact') not in BUDGETS:
        raise ValueError('impact:expected_ordinary_or_salient')
    pad = clean.get('delta')
    if not isinstance(pad, dict) or set(pad) != {'p', 'a', 'd'}:
        raise ValueError('delta:expected_p_a_d_numbers')
    appraisal = clean.get('appraisal')
    if not isinstance(appraisal, dict) or set(appraisal) != {'kind', 'target', 'agency', 'certainty', 'feeling', 'action'}:
        raise ValueError('appraisal:exact_kind_target_agency_certainty_feeling_action_required')
    for path, entries, cap in [('emotion_deltas', values, .45), ('delta', pad, .35)]:
        for key, value in entries.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value)>cap:
                raise ValueError(path+':finite_bounded_numbers_required')
    nonzero = [dict(label=k, delta=values[k]) for k in LABELS if values[k] != 0]
    nonzero.sort(key=lambda x: -abs(x['delta']))
    changed = bool(nonzero or any(pad.values()))
    if 'changed' in clean and (type(clean['changed']) is not bool or clean['changed'] != changed):
        raise ValueError('changed:must_match_actual_nonzero_vector')
    expected = dict(label=nonzero[0]['label'] if nonzero else None,
                    intensity_delta=nonzero[0]['delta'] if nonzero else 0,
                    emotions=nonzero[1:])
    for key, value in expected.items():
        if key in clean and clean[key] != value:
            raise ValueError('full48:do_not_mix_sparse_label_intensity_or_emotions_fields')
    clean.update(expected, changed=changed)
    return clean


def schema():
    return dict(format=FORMAT, labels_required=48, template=template(),
                input_formats=list(INPUT_FORMATS),compact_template=compact_template(),
                reference_gain=REFERENCE_GAIN, raw_budgets=copy.deepcopy(BUDGETS),
                guidance=APPRAISAL_GUIDANCE)


def bound(raw):
    values = raw['emotion_deltas']
    policy = BUDGETS[raw['impact']]
    maximum = max(abs(x) for x in values.values())
    total = sum(abs(x) for x in values.values())
    scale = min(1, policy['component']/maximum if maximum else 1, policy['total']/total if total else 1)
    pad_max = max(abs(x) for x in raw['delta'].values())
    pad_scale = min(1, policy['pad']/pad_max if pad_max else 1)
    return dict(labels={k: v*scale for k, v in values.items()},
                pad={k: v*pad_scale for k, v in raw['delta'].items()},
                budget=dict(impact=raw['impact'], label_scale=scale, pad_scale=pad_scale,
                            raw_limits=policy, reference_gain=REFERENCE_GAIN))


def frame(b, scope, now):
    values = dict.fromkeys(LABELS, 0.0)
    recorded = []
    for row in b.db.execute('SELECT e.label,e.intensity,e.at,c.half FROM emotion e LEFT JOIN ct_label c '
                            'ON c.scope=e.scope AND c.label=e.label WHERE e.scope=?', (scope,)):
        if row['label'] not in values:
            continue
        half = row['half'] if row['half'] is not None else .75
        values[row['label']] = row['intensity']*.5**(max(0, now-row['at'])/(half*3600))
        recorded.append(row['label'])
    return dict(values=values, recorded_labels=recorded, at=now,
                origin='decayed_state; absent_labels_start_at_implicit_zero')


def groups(applied):
    result = []
    for name, labels in GROUPS.items():
        label = max(labels, key=lambda k: abs(applied.get(k, 0)))
        delta = applied.get(label, 0)
        result.append(dict(group=name, label=label if delta else None, delta=delta, changed=bool(delta)))
    return result


def save(b, event, scope, raw, bounded, before, applied, gain, now):
    payload = dict(format=FORMAT, source_event=event, impact=raw['impact'], gain=gain,
                   raw=dict(raw['emotion_deltas']), bounded=dict(bounded['labels']),
                   applied=dict(applied), before=before,
                   after={k: round(before[k]+applied[k], 8) for k in LABELS},
                   budget=bounded['budget'], group_changes=groups(applied))
    b.db.execute('INSERT INTO ct_emotion_full48 VALUES(?,?,?,?)',
                 (event, scope, json.dumps(payload, ensure_ascii=False, allow_nan=False), now))
    return payload


def receipt(b, event):
    row = b.db.execute('SELECT payload FROM ct_emotion_full48 WHERE event=?', (event,)).fetchone()
    return json.loads(row[0]) if row else None


def latest(b, scope):
    row = b.db.execute('SELECT a.event FROM ct_appraisal a JOIN source_events e ON e.id=a.event '
                       "WHERE e.scope=? AND e.status='active' ORDER BY a.at DESC LIMIT 1", (scope,)).fetchone()
    return receipt(b, row[0]) if row else None
