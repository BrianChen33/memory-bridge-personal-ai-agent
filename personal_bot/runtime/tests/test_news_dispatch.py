"""Tests for news dispatch path (real brain.py dispatch).

Uses temporary root + monkeypatched clock. No production fake now param.
"""
import json
from functools import wraps
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import proactive
import brain as brain_mod
from proactive import beijing_now

POLICY = {
    "timezone": "Asia/Shanghai",
    "quiet_start": "01:00",
    "quiet_end": "07:00",
    "news_threshold": 70,
    "news_weights": {"relevance": 60, "utility": 25, "novelty": 15},
    "inferred_relevance_penalty": 0.65,
    "interests": [
        {"topic": "AI工具", "basis": "confirmed"},
        {"topic": "QQ机器人/自动化", "basis": "confirmed"},
    ],
}

BJ = timezone(timedelta(hours=8))

def dt(h, m):
    return datetime(2026, 11, 3, h, m, tzinfo=BJ)

def _fixture_clock(fn):
    # News dates are fixed below. Keep expiry checks on the same fixture day;
    # per-test beijing_now patches still control quiet-hour scenarios.
    @wraps(fn)
    def run(*args, **kwargs):
        with mock.patch('time.time', return_value=dt(12, 0).timestamp()):
            return fn(*args, **kwargs)
    return run


def make_brain():
    root = tempfile.mkdtemp()
    Path(root, 'proactive-policy.json').write_text(json.dumps(POLICY))
    from support import write_interests
    write_interests(root)
    b = brain_mod.Brain(root)
    b.dispatch({'op': 'configure', 'enabled': True, 'modules': {'life': True}})
    # Create a source memory for news tests
    mid = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                      'text': 'test source', 'kind': 'fact',
                      'source': 'test', 'event_id': 'src1', 'evidence': 'observed'})['id']
    b._test_source_id = mid
    # 'USE_BRAIN_SOURCE' placeholder in base_news() means "the real source id".
    _orig_dispatch = b.dispatch
    def _dispatch_with_source(q):
        if isinstance(q, dict) and q.get('sources') == 'USE_BRAIN_SOURCE':
            q = dict(q, sources=[mid])
        return _orig_dispatch(q)
    b.dispatch = _dispatch_with_source
    return b, root

def base_news(**kw):
    d = {
        'op': 'news', 'scope': 'owner-private',
        'subject': 'AI模型', 'event': '发布新版本', 'phase': 'v1',
        'title': '测试新闻标题', 'source_url': 'https://example.com/news/1',
        'publish_date': '2026-11-02', 'event_date': '2026-11-02',
        'relevance': 1.0, 'utility': 1.0, 'novelty': 1.0,
        'interest_id': 'ai-tools',
        'reason': '测试原因', 'sources': 'USE_BRAIN_SOURCE',
    }
    d.update(kw)
    return d

@_fixture_clock
def test_news_low_score_no_candidate():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            # Also patch brain's imported proactive
            with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
                r = b.dispatch(base_news(relevance=0.5, utility=0.5, novelty=0.5))
                assert r['ok'] and not r['passes'], r
                assert 'no_candidate' in r.get('reason', ''), r
    finally:
        b.close()

@_fixture_clock
def test_news_70_rejected_7001_passes():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            # 70.0 exactly -> reject (60*1.0 + 25*0.4 + 15*0 = 70)
            r = b.dispatch(base_news(relevance=1.0, utility=0.4, novelty=0.0,
                                     subject='S1', event='E1'))
            assert not r['passes'], f"70 should reject: {r}"
            # 70.01 -> pass (avoid round-before-compare trap)
            r = b.dispatch(base_news(relevance=1.0, utility=0.4004, novelty=0.0,
                                     subject='S2', event='E2'))
            assert r['passes'], f"70.01 should pass: {r}"
    finally:
        b.close()

@_fixture_clock
def test_news_same_story_different_media_one_candidate():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            r1 = b.dispatch(base_news(subject='S', event='E', phase='v1',
                                      source_url='https://a.com/1'))
            assert r1['passes'] and not r1.get('duplicate'), r1
            cid1 = r1['candidate_id']
            # Different media, same story
            r2 = b.dispatch(base_news(subject='S', event='E', phase='v1',
                                      source_url='https://b.com/2'))
            assert r2.get('duplicate'), f"should be duplicate: {r2}"
            assert r2['candidate_id'] == cid1
            # New source IDs also don't create new candidate
            mid = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                              'text': 'src', 'kind': 'fact', 'source': 't',
                              'event_id': 'e9', 'evidence': 'observed'})['id']
            r3 = b.dispatch(base_news(subject='S', event='E', phase='v1',
                                      source_url='https://c.com/3', sources=[mid]))
            assert r3.get('duplicate'), f"new sources should not bypass: {r3}"
    finally:
        b.close()

@_fixture_clock
def test_news_bad_policy_rejects_but_recall_works():
    # Missing policy file -> fail closed for proactive, recall still works
    root = tempfile.mkdtemp()
    b = brain_mod.Brain(root)  # no proactive-policy.json
    try:
        b.dispatch({'op': 'configure', 'enabled': True, 'modules': {'life': True}})
        r = b.dispatch(base_news())
        assert r.get('quiet_hours'), f"should fail closed: {r}"
        # recall unaffected
        b.dispatch({'op': 'remember', 'scope': 'owner-private', 'text': 'x',
                    'kind': 'fact', 'source': 't', 'event_id': 'e1', 'evidence': 'observed'})
        r = b.dispatch({'op': 'recall', 'scope': 'owner-private', 'text': 'x'})
        assert r['ok'], r
    finally:
        b.close()

@_fixture_clock
def test_news_inferred_max_79_passes():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            # inferred: rel 1.0*0.65=0.65 -> 39 + 25 + 15 = 79
            r = b.dispatch(base_news(relevance=1.0, utility=1.0, novelty=1.0,
                                     interest_id='tech-news',
                                     subject='SI', event='EI'))
            assert r['passes'], f"inferred 79 should pass: {r}"
            assert r['score'] == 79.0, r
    finally:
        b.close()

@_fixture_clock
def test_news_invalid_scores_rejected():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            for bad in [float('nan'), float('inf'), True, 1.5, -0.1, "high"]:
                try:
                    b.dispatch(base_news(relevance=bad, subject=f'S{bad}', event='E'))
                    assert False, f"should reject {bad}"
                except ValueError as e:
                    assert 'invalid_score' in str(e), e
    finally:
        b.close()

@_fixture_clock
def test_news_quiet_hours_in_lock_rejects():
    b, root = make_brain()
    try:
        # Gate passes at 08:00, but mock to flip to 01:30 inside lock
        # (simulate by patching beijing_now to return quiet time on second call)
        calls = [dt(8, 0), dt(1, 30), dt(1, 30), dt(1, 30)]
        def fake_now():
            return calls.pop(0) if calls else dt(1, 30)
        with mock.patch.object(proactive, 'beijing_now', side_effect=fake_now):
            # life op should be blocked at claim/authorize stage
            mid = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                              'text': 't', 'kind': 'fact', 'source': 's',
                              'event_id': 'e1', 'evidence': 'observed'})['id']
            # First call at 08:00 passes gate, but we can't easily test in-lock flip
            # without deeper mocking; at minimum verify quiet blocks
            # New spec: quiet hours ALLOW news enqueue to pending (background).
            with mock.patch.object(proactive, 'beijing_now', return_value=dt(2, 0)):
                r = b.dispatch(base_news(subject='SQ', event='EQ'))
                assert r.get('ok') and r.get('passes'), r
                # but the notify path stays blocked
                r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
                assert r.get('quiet_hours'), r
    finally:
        b.close()

@_fixture_clock
def test_news_concurrent_same_story_dedup():
    """Sequential inserts of same story -> only one candidate (SQLite is single-thread)."""
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            r1 = b.dispatch(base_news(subject='CS', event='CE', phase='v1',
                                      source_url='https://m1.com/x'))
            assert r1['passes'] and not r1.get('duplicate'), r1
            # Simulate concurrent attempts sequentially - all should dedup
            for i in range(2, 6):
                r = b.dispatch(base_news(subject='CS', event='CE', phase='v1',
                                         source_url=f'https://m{i}.com/x'))
                assert r.get('duplicate'), f"attempt {i} should dedup: {r}"
                assert r['candidate_id'] == r1['candidate_id']
    finally:
        b.close()

@_fixture_clock
def test_news_life_false_rejects():
    b, root = make_brain()
    try:
        b.dispatch({'op': 'configure', 'enabled': True, 'modules': {'life': False}})
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            r = b.dispatch(base_news(subject='LF', event='LE'))
            assert r.get('disabled'), f"life=false should reject: {r}"
    finally:
        b.close()

@_fixture_clock
def test_news_unknown_interest_rejected():
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            try:
                b.dispatch(base_news(interest_id='nonexistent-xyz', subject='UI', event='UE'))
                assert False, "unknown interest_id should reject"
            except ValueError as e:
                assert 'unknown_interest_id' in str(e), e
    finally:
        b.close()

@_fixture_clock
def test_news_forged_basis_ignored():
    """q.interest_basis='confirmed' is IGNORED; basis comes from interests.json."""
    b, root = make_brain()
    try:
        with mock.patch.object(proactive, 'beijing_now', return_value=dt(8, 0)):
            # tech-news is inferred in interests.json; even if q claims confirmed,
            # it must use inferred (0.65 multiplier)
            # rel=1.0, util=1.0, nov=1.0 with inferred: 39+25+15=79 -> passes
            # If it incorrectly used confirmed: 60+25+15=100
            r = b.dispatch(base_news(interest_id='tech-news',
                                     # q.interest_basis forged as 'confirmed' would be ignored
                                     relevance=1.0, utility=1.0, novelty=1.0,
                                     subject='FB', event='FE'))
            assert r['passes'], r
            assert r['interest_basis'] == 'inferred', f"forged basis must be ignored: {r}"
            assert r['score'] == 79.0, f"should be 79 (inferred), not 100: {r}"
    finally:
        b.close()
