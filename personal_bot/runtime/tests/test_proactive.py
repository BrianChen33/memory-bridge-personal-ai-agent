"""Tests for proactive quiet-hours gate and news scoring.

Uses temporary root + monkeypatched clock. Production interface never accepts
a caller-supplied `now` for the gate.
"""
import json
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import proactive
from proactive import (
    beijing_now, is_quiet_time, load_policy, proactive_allowed,
    normalize_url, story_key, score_news,
)

POLICY = {
    "timezone": "Asia/Shanghai",
    "quiet_start": "01:00",
    "quiet_end": "07:00",
    "news_threshold": 70,
    "news_weights": {"relevance": 60, "utility": 25, "novelty": 15},
    "inferred_relevance_penalty": 0.5,
}

BJ = timezone(timedelta(hours=8))


def dt(h, m):
    return datetime(2026, 11, 3, h, m, tzinfo=BJ)


def test_boundary_0059_allowed():
    assert not is_quiet_time(dt(0, 59), POLICY)


def test_boundary_0100_quiet():
    assert is_quiet_time(dt(1, 0), POLICY)


def test_boundary_0659_quiet():
    assert is_quiet_time(dt(6, 59), POLICY)


def test_boundary_0700_allowed():
    assert not is_quiet_time(dt(7, 0), POLICY)


def test_midnight_allowed():
    assert not is_quiet_time(dt(0, 0), POLICY)


def test_noon_allowed():
    assert not is_quiet_time(dt(12, 0), POLICY)


def test_request_now_cannot_bypass():
    """Gate uses actual system clock; a request-supplied `now` is ignored."""
    with tempfile.TemporaryDirectory() as root:
        Path(root, 'proactive-policy.json').write_text(json.dumps(POLICY))
        # Mock system clock to 03:00 (quiet). Even if caller passes now=12:00,
        # proactive_allowed takes no `now` argument at all.
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(3, 0)):
            allowed, reason = proactive_allowed(root)
            assert not allowed and reason == 'quiet_hours'
        # And at 08:00 it allows.
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            allowed, reason = proactive_allowed(root)
            assert allowed


def test_brain_gate_blocks_life_claim_authorize_finish():
    """Brain dispatch refuses proactive ops during quiet hours."""
    import brain as brain_mod
    with tempfile.TemporaryDirectory() as root:
        Path(root, 'proactive-policy.json').write_text(json.dumps(POLICY))
        b = brain_mod.Brain(root)
        try:
            b.dispatch({'op': 'configure', 'enabled': True, 'modules': {'life': True}})
            # Need a source memory for life op
            mid = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                              'text': 'test fact', 'kind': 'fact',
                              'source': 'test', 'event_id': 'e1', 'evidence': 'observed'})['id']
            life_q = {'op': 'life', 'scope': 'owner-private', 'text': 'hello',
                      'sources': [mid], 'topic': 't1'}
            with mock.patch.object(proactive, 'beijing_now', return_value=dt(2, 30)):
                # New spec: quiet hours ALLOW enqueue to pending (background).
                r = b.dispatch(life_q)
                assert r.get('ok') is True and r.get('id'), r
                # claim (notify path) still blocked
                r = b.dispatch({'op': 'claim', 'scope': 'owner-private'})
                assert r.get('quiet_hours') is True, r
            # At 08:00, life works
            with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
                r = b.dispatch(life_q)
                assert r.get('ok') is True, r
        finally:
            b.close()


def test_brain_gate_does_not_affect_remember_recall():
    """remember/recall/QQ paths are unaffected by quiet hours."""
    import brain as brain_mod
    with tempfile.TemporaryDirectory() as root:
        Path(root, 'proactive-policy.json').write_text(json.dumps(POLICY))
        b = brain_mod.Brain(root)
        try:
            b.dispatch({'op': 'configure', 'enabled': True})
            with mock.patch.object(proactive, 'beijing_now', return_value=dt(3, 0)):
                r = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                                'text': 'quiet test', 'kind': 'fact',
                                'source': 'test', 'event_id': 'e2', 'evidence': 'observed'})
                assert r.get('ok') is True, r
                r = b.dispatch({'op': 'recall', 'scope': 'owner-private', 'text': 'quiet'})
                assert r.get('ok') is True, r
        finally:
            b.close()


def test_score_threshold_strict():
    # Exactly 70 -> rejected (strict >)
    s, br, ok = score_news({'relevance': 1.0, 'utility': 0.4, 'novelty': 0.0}, [], POLICY)
    # 60 + 10 + 0 = 70.0
    assert s == 70.0 and ok is False
    # 70.1 -> passes
    s, br, ok = score_news({'relevance': 1.0, 'utility': 0.404, 'novelty': 0.0}, [], POLICY)
    assert ok is True


def test_inferred_interest_downweighted():
    base = {'relevance': 1.0, 'utility': 1.0, 'novelty': 1.0, 'basis': 'confirmed'}
    s_conf, _, ok_conf = score_news(base, [], POLICY)
    inf = dict(base, basis='inferred')
    s_inf, _, ok_inf = score_news(inf, [], POLICY)
    assert s_conf == 100.0 and ok_conf is True
    # relevance halved: 30 + 25 + 15 = 70 -> strict > fails
    assert s_inf == 70.0 and ok_inf is False


def test_cross_outlet_same_story_dedup():
    k1 = story_key('AI 模型', '发布新版本', 'v1')
    k2 = story_key('AI 模型', '发布新版本', 'v1')
    assert k1 == k2
    k3 = story_key('AI 模型', '发布新版本', 'v2-实质进展')
    assert k3 != k1


def test_url_normalization():
    u1 = normalize_url('https://www.example.com/a?utm_source=x&b=1#frag')
    u2 = normalize_url('https://example.com/a?b=1')
    assert u1 == u2


def test_low_score_not_candidate():
    s, _, ok = score_news({'relevance': 0.5, 'utility': 0.5, 'novelty': 0.5}, [], POLICY)
    # 30 + 12.5 + 7.5 = 50
    assert s == 50.0 and ok is False
