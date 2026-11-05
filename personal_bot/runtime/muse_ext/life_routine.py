"""Configurable life categories and honest phone-reading intents; no browser IO."""
import math
import uuid


def settings(b):
    from muse_ext.companion import _get
    probability = _get(b, 'life_routine', {}).get('phone_probability', .6)
    return dict(phone_probability=probability, chores_probability=round(1-probability, 6),
                meaning='probability at each new autonomous activity selection, not per heartbeat or time quota')


def configure(b, q):
    from muse_ext.companion import _set
    patch = q.get('patch')
    if not isinstance(patch, dict) or set(patch) != {'phone_probability'}:
        raise ValueError('life_phone_probability_patch_required')
    value = patch['phone_probability']
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('life_phone_probability_0_to_1_required')
    with b.db:
        _set(b, 'life_routine', {'phone_probability': value})
    return dict(ok=True, settings=settings(b))


def pending(b):
    from muse_ext.companion import _get, stamp
    request = _get(b, 'phone_intent', {})
    return dict(ok=True, request=request or None,
                actionable=bool(request.get('status') == 'pending' and request.get('deadline', 0) > stamp()),
                policy='Use one stable life-phone:<id> job; only enabled, owner-approved platform adapters. '
                       'No successful observation means no claim of reading, watching or learning.')


def start(b, now, duration):
    from muse_ext.companion import _set
    request = dict(id=uuid.uuid4().hex, status='pending', created_at=now, deadline=now+duration,
                   activity='刷手机', provider=None)
    _set(b, 'phone_intent', request)
    return request


def require(b, intent):
    request = pending(b)
    if not request['actionable'] or request['request']['id'] != intent:
        raise ValueError('active_pending_phone_intent_required')
    return request['request']


def mark(b, intent, status, **values):
    from muse_ext.companion import _get, _set
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        request = _get(b, 'phone_intent', {})
        if request.get('id') != intent:
            return dict(status='stale_phone_intent')
        if request.get('status') in ('read', 'blocked', 'unavailable', 'expired'):
            return dict(status=request['status'], replayed=True)
        request.update(status=status, **values)
        _set(b, 'phone_intent', request)
    return dict(status=status, id=intent)


def outcome(b, intent):
    from muse_ext.companion import _get
    request = _get(b, 'phone_intent', {})
    if request.get('id') != intent:
        return '放下手机了。这一轮没有可核验的读取结果。'
    if request.get('status') == 'read':
        return '放下手机了。这轮实际读到的内容、感受与想法，以独立登记的真实阅读及反思为准。'
    if request.get('status') == 'blocked':
        return '想刷一会儿手机，但页面被验证或登录拦住了，没有把帖子读下来。'
    if request.get('status') in ('pending', 'claimed'):
        final = mark(b, intent, 'expired', reason='session_finished_without_confirmed_observation')
        if final['status'] == 'read':
            return '放下手机了。这轮实际读到的内容与感受，以独立登记的真实阅读及反思为准。'
    return '放下手机了。这轮没有成功读取新的内容，不编造刷到了什么。'
