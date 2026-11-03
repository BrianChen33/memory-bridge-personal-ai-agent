"""Proactive gate + news scoring for muse-brain.

Quiet-hours gate: deterministic Beijing time check, actual system clock only.
Production code NEVER accepts a caller-supplied `now` for the gate.
Tests use a temporary root and monkeypatch `beijing_now`.
"""
import json
import re
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path

POLICY_FILE = 'proactive-policy.json'


def _beijing_tz():
    # Asia/Shanghai = UTC+8, no DST. Avoid zoneinfo dependency.
    return timezone(timedelta(hours=8))


def beijing_now():
    """Actual system time in Beijing. Monkeypatch this in tests only."""
    return datetime.now(tz=_beijing_tz())


def load_policy(root):
    p = Path(root) / POLICY_FILE
    return json.loads(p.read_text(encoding='utf-8'))


def _parse_hhmm(s):
    h, m = s.split(':')
    return int(h), int(m)


def is_quiet_time(dt, policy):
    """True when dt falls in [quiet_start, quiet_end)."""
    sh, sm = _parse_hhmm(policy['quiet_start'])
    eh, em = _parse_hhmm(policy['quiet_end'])
    t = (dt.hour, dt.minute)
    return (sh, sm) <= t < (eh, em)


def validate_policy(policy):
    """Raise ValueError if the policy is not effective (fail closed).
    Checks: object shape, required fields, quiet HH:MM legality, finite
    scoring params. A policy that merely parses (e.g. {} or []) is NOT
    accepted. Quiet hours themselves still allow background work; this
    only rejects broken configuration."""
    import math
    if not isinstance(policy, dict):
        raise ValueError('policy_not_object')

    def _hhmm(key):
        v = policy.get(key)
        if not isinstance(v, str) or not re.fullmatch(r'\d{2}:\d{2}', v):
            raise ValueError('policy_bad_' + key)
        hh, mm = int(v[:2]), int(v[3:])
        if not (0 <= hh < 24 and 0 <= mm < 60):
            raise ValueError('policy_bad_' + key)

    def _num(name, low=None, high=None, positive=False):
        v = policy.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError('policy_bad_' + name)
        f = float(v)
        if not math.isfinite(f):
            raise ValueError('policy_bad_' + name)
        if positive and f <= 0:
            raise ValueError('policy_bad_' + name)
        if low is not None and f < low:
            raise ValueError('policy_bad_' + name)
        if high is not None and f > high:
            raise ValueError('policy_bad_' + name)
        return f

    _hhmm('quiet_start')
    _hhmm('quiet_end')
    _num('news_threshold')
    w = policy.get('news_weights')
    if not isinstance(w, dict):
        raise ValueError('policy_bad_news_weights')
    for k in ('relevance', 'utility', 'novelty'):
        v = w.get(k)
        if isinstance(v, bool) or not isinstance(v, (int, float)) \
                or not math.isfinite(float(v)) or float(v) < 0:
            raise ValueError('policy_bad_news_weights_' + k)
    _num('inferred_relevance_penalty', low=0, high=1)
    # news_expiry_hours: code defaults to 72 when absent; validate only if present.
    if 'news_expiry_hours' in policy and policy['news_expiry_hours'] is not None:
        _num('news_expiry_hours', positive=True)
    return True


def proactive_allowed(root):
    """Gate for proactive life/news. Returns (allowed, reason)."""
    policy = load_policy(root)
    validate_policy(policy)
    now = beijing_now()
    if is_quiet_time(now, policy):
        return False, 'quiet_hours'
    return True, 'ok'


# ---------------------------------------------------------------------------
# News interest scoring (explainable, not probabilistic)
# ---------------------------------------------------------------------------

def normalize_url(url):
    """Normalize URL for dedup: lowercase host, strip tracking params, drop fragment."""
    try:
        u = urllib.parse.urlparse(url.strip())
        host = u.netloc.lower()
        if host.startswith('www.'):
            host = host[4:]
        q = urllib.parse.parse_qsl(u.query, keep_blank_values=True)
        drop = {'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
                'fbclid', 'gclid', 'spm', 'from', 'ref'}
        q = sorted((k, v) for k, v in q if k.lower() not in drop)
        path = u.path.rstrip('/') or '/'
        return urllib.parse.urlunparse((u.scheme.lower(), host, path, '', urllib.parse.urlencode(q), ''))
    except Exception:
        return url.strip().lower()


def story_key(subject, event, phase):
    """Stable dedup key: subject + event + phase. Same story across outlets/links
    must not re-push; a genuinely new development uses a new phase key."""
    norm = lambda s: re.sub(r'\s+', ' ', (s or '').strip().lower())
    return '|'.join([norm(subject), norm(event), norm(phase)])


def score_news(item, interests, policy):
    """item: {relevance, utility, novelty} each 0..1 as judged by model semantics.
    interests: list of {topic, basis} where basis is 'confirmed' or 'inferred'.
    Returns (score_0_100, breakdown, reasons)."""
    w = policy['news_weights']
    rel = max(0.0, min(1.0, float(item.get('relevance', 0))))
    util = max(0.0, min(1.0, float(item.get('utility', 0))))
    nov = max(0.0, min(1.0, float(item.get('novelty', 0))))
    # Inferred interests reduce the relevance component (0.65: 0.5 maxes at 70, never passes strict >70).
    basis = (item.get('basis') or 'confirmed').lower()
    if basis == 'inferred':
        rel = rel * float(policy.get('inferred_relevance_penalty', 0.65))
    # Validate bounds (code-side check, model supplies semantics).
    score = rel * w['relevance'] + util * w['utility'] + nov * w['novelty']
    score = round(score, 1)
    breakdown = {
        'relevance': round(rel * w['relevance'], 1),
        'utility': round(util * w['utility'], 1),
        'novelty': round(nov * w['novelty'], 1),
    }
    passes = score > float(policy['news_threshold'])  # strict >
    return score, breakdown, passes
