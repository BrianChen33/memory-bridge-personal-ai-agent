"""Night accumulate + morning batch digest (real brain.py dispatch).

Temp root + monkeypatched proactive.beijing_now. No production fake now.
New spec: 01:00-07:00 allows life/news enqueue to pending (background_allowed),
but claim/authorize/finish (single + batch) are notify-gated and refuse.
"""
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest import mock
from contextlib import contextmanager

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import proactive
import brain as brain_mod

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


def dt(day, h, m):
    return datetime(2026, 11, day, h, m, tzinfo=BJ)


@contextmanager
def clock(day, h, m):
    # Quiet-hour gating and candidate expiry must use the same fixture clock.
    # Otherwise the fixed 2026-11 news expires as the real calendar advances.
    instant=dt(day,h,m)
    with mock.patch.object(proactive,'beijing_now',return_value=instant), \
            mock.patch('time.time',return_value=instant.timestamp()):
        yield


def make_brain():
    root = tempfile.mkdtemp()
    Path(root, 'proactive-policy.json').write_text(json.dumps(POLICY))
    from support import write_interests
    write_interests(root)
    b = brain_mod.Brain(root)
    b.dispatch({'op': 'configure', 'enabled': True, 'modules': {'life': True}})
    mid = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                      'text': 'test source', 'kind': 'fact',
                      'source': 'test', 'event_id': 'src1',
                      'evidence': 'observed'})['id']
    return b, root, mid


def life_q(mid, topic='t1', text='hello'):
    return {'op': 'life', 'scope': 'owner-private', 'text': text,
            'sources': [mid], 'topic': topic}


def news_q(mid, **kw):
    d = {'op': 'news', 'scope': 'owner-private',
         'subject': 'AI模型', 'event': '发布新版本', 'phase': 'v1',
         'title': '测试新闻标题', 'source_url': 'https://example.com/news/1',
         'publish_date': '2026-11-03', 'event_date': '2026-11-03',
         'relevance': 1.0, 'utility': 1.0, 'novelty': 1.0,
         'interest_id': 'ai-tools', 'reason': '测试原因',
         'sources': [mid]}
    d.update(kw)
    return d


def pendings(b):
    return b.dispatch({'op': 'candidates', 'scope': 'owner-private'})['candidates']


# --- proactive_check fields -------------------------------------------------

def test_check_fields_night():
    b, _, _ = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch({'op': 'proactive_check', 'scope': 'owner-private'})
            assert r['background_allowed'] is True, r
            assert r['can_notify'] is False, r
            assert r['quiet_hours'] is True, r
            assert r['proactive'] is False, r
    finally:
        b.close()


def test_check_fields_day():
    b, _, _ = make_brain()
    try:
        with clock(4, 8, 0):
            r = b.dispatch({'op': 'proactive_check', 'scope': 'owner-private'})
            assert r['background_allowed'] is True, r
            assert r['can_notify'] is True, r
            assert r['quiet_hours'] is False, r
            assert r['proactive'] is True, r
    finally:
        b.close()


def test_check_disabled():
    b, _, _ = make_brain()
    try:
        b.dispatch({'op': 'configure', 'enabled': False})
        with clock(4, 8, 0):
            r = b.dispatch({'op': 'proactive_check', 'scope': 'owner-private'})
            assert r['background_allowed'] is False, r
            assert r['can_notify'] is False, r
    finally:
        b.close()


# --- night enqueue ----------------------------------------------------------

def test_night_life_enqueue_ok():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch(life_q(mid))
            assert r.get('ok') is True and r.get('id'), r
            ps = [c for c in pendings(b) if c['status'] == 'pending']
            assert len(ps) == 1, ps
    finally:
        b.close()


def test_night_news_enqueue_ok():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch(news_q(mid))
            assert r.get('ok') and r.get('passes') is True, r
    finally:
        b.close()


def test_night_news_still_validates_score():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch(news_q(mid, relevance=0.5, utility=0.5, novelty=0.5))
            assert r.get('ok') and not r.get('passes'), r
    finally:
        b.close()


def test_disabled_still_refuses_enqueue():
    b, _, mid = make_brain()
    try:
        b.dispatch({'op': 'configure', 'enabled': False})
        with clock(4, 2, 0):
            r = b.dispatch(life_q(mid))
            assert r.get('disabled') is True, r
    finally:
        b.close()


# --- night notify refused ----------------------------------------------------

def test_night_single_claim_refused():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            b.dispatch(life_q(mid))
            r = b.dispatch({'op': 'claim', 'scope': 'owner-private'})
            assert r.get('quiet_hours') is True and r.get('candidate') is None, r
            ps = [c for c in pendings(b) if c['status'] == 'pending']
            assert len(ps) == 1, ps
    finally:
        b.close()


def test_night_digest_claim_refused():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            b.dispatch(life_q(mid))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('quiet_hours') is True and r.get('candidates') == [], r
    finally:
        b.close()


def test_night_digest_authorize_finish_refused():
    b, _, _ = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                            'lease': 'bogus', 'epoch': 1})
            assert r.get('quiet_hours') is True, r
            r = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                            'lease': 'bogus', 'epoch': 1, 'outcome': 'unknown'})
            assert r.get('quiet_hours') is True, r
    finally:
        b.close()


# --- morning batch digest -----------------------------------------------------

def test_day_digest_merges_no_double_claim():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            for t in ('t1', 't2', 't3'):
                b.dispatch(life_q(mid, topic=t))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('ok') and len(r['candidates']) == 3, r
            leases = {c['lease'] for c in r['candidates']}
            assert len(leases) == 1, r  # single global lease
            r2 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r2.get('busy') is True and r2.get('candidates') == [], r2
    finally:
        b.close()


def test_digest_cancels_bad_source():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(life_q(mid))
            # source memory forgotten -> stale
            import brain as _  # noqa
            b.db.execute("UPDATE memories SET status='forgotten' WHERE id=?", (mid,))
            b.db.commit()
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('ok') and r.get('candidates') == [], r
    finally:
        b.close()


def test_digest_cancels_removed_interest():
    b, root, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(news_q(mid))
            data = json.loads(Path(root, 'interests.json').read_text())
            data['interests'] = [i for i in data['interests'] if i['id'] != 'ai-tools']
            Path(root, 'interests.json').write_text(json.dumps(data))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('ok') and r.get('candidates') == [], r
    finally:
        b.close()


def test_digest_cancels_raised_threshold():
    b, root, mid = make_brain()
    try:
        with clock(4, 8, 0):
            # score = 60*1.0 + 25*0.6 + 15*0 = 75 > 70
            b.dispatch(news_q(mid, relevance=1.0, utility=0.6, novelty=0.0))
            pol = json.loads(Path(root, 'proactive-policy.json').read_text())
            pol['news_threshold'] = 80
            Path(root, 'proactive-policy.json').write_text(json.dumps(pol))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('ok') and r.get('candidates') == [], r
    finally:
        b.close()


def test_expired_news_not_pushed():
    b, _, mid = make_brain()
    try:
        with clock(4, 2, 0):
            r = b.dispatch(news_q(mid, publish_date='2026-11-03'))
            assert r.get('passes'), r
        # >72h later: mock both beijing_now (gate) and time.time (expiry math)
        with clock(8, 7, 0), \
                mock.patch('time.time', return_value=dt(8, 7, 0).timestamp()):
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r.get('ok') and r.get('candidates') == [], r
    finally:
        b.close()


def test_epoch_change_refuses_authorize_finish():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(life_q(mid))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            lease, epoch = r['lease'], r['epoch']
            b.dispatch({'op': 'configure', 'enabled': True,
                        'modules': {'life': True}})  # bumps epoch
            ra = b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch})
            assert ra.get('ok') is not True, ra
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch, 'outcome': 'unknown',
                             'expressed_ids': []})
            assert rf.get('ok') is not True, rf
    finally:
        b.close()


def test_cross_01_whole_batch_refused_no_partial():
    b, _, mid = make_brain()
    try:
        # Freeze both clocks: a real wall-clock claim can be later than the
        # mocked morning, making the lease appear fresh forever in this test.
        with clock(4, 0, 59), mock.patch('time.time', return_value=dt(4, 0, 59).timestamp()):
            b.dispatch(life_q(mid, topic='t1'))
            b.dispatch(life_q(mid, topic='t2'))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            lease, epoch = r['lease'], r['epoch']
            assert len(r['candidates']) == 2, r
        with clock(4, 1, 0), mock.patch('time.time', return_value=dt(4, 1, 0).timestamp()):
            cids = [c['id'] for c in r['candidates']]
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch, 'outcome': 'unknown',
                             'expressed_ids': cids})
            assert rf.get('quiet_hours') is True, rf
            rows = b.db.execute(
                "SELECT status FROM candidates WHERE lease=?", (lease,)).fetchall()
            assert all(x[0] == 'generating' for x in rows), rows  # none settled
        with clock(4, 7, 0), \
                mock.patch('time.time', return_value=dt(4, 7, 0).timestamp()):
            r2 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r2.get('ok') and len(r2['candidates']) == 2, r2  # reclaimed
    finally:
        b.close()


def test_digest_authorize_finish_happy_path():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(life_q(mid, topic='t1'))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            lease, epoch = r['lease'], r['epoch']
            ra = b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch})
            assert ra.get('ok') and ra.get('count') == 1, ra
            cid = r['candidates'][0]['id']
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch, 'outcome': 'unknown',
                             'expressed_ids': [cid]})
            assert rf.get('ok') and rf.get('expressed') == 1, rf
            rows = b.db.execute("SELECT status FROM candidates").fetchall()
            assert [x[0] for x in rows] == ['unknown'], rows
    finally:
        b.close()


# --- mood ---------------------------------------------------------------------

def test_mood_candidate_dedup():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(life_q(mid, topic='mood:joy', text='nice moment'))
            b.dispatch(life_q(mid, topic='mood:joy', text='nice moment'))
            ps = [c for c in pendings(b) if c['status'] == 'pending']
            assert len(ps) == 1, ps
    finally:
        b.close()


def test_mood_read_no_db_write():
    b, _, _ = make_brain()
    try:
        def dump():
            return (b.db.execute("SELECT scope,p,a,d,at FROM mood").fetchall(),
                    b.db.execute("SELECT scope,label,intensity,at FROM emotion").fetchall())
        before = dump()
        with clock(4, 8, 0):
            b.dispatch({'op': 'mood', 'scope': 'owner-private'})
            b.dispatch({'op': 'mood', 'scope': 'owner-private'})
        assert dump() == before
    finally:
        b.close()


# --- bounded claim ------------------------------------------------------------

def test_digest_bounded_two_rounds_no_loss_no_dup():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            for i in range(8):
                b.dispatch(life_q(mid, topic=f'bt{i}'))
            r1 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r1.get('ok') and len(r1['candidates']) == 6, r1
            assert r1.get('remaining') == 2, r1
            ids1 = [c['id'] for c in r1['candidates']]
            b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                        'lease': r1['lease'], 'epoch': r1['epoch']})
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': r1['lease'], 'epoch': r1['epoch'],
                             'outcome': 'unknown', 'expressed_ids': ids1})
            assert rf.get('expressed') == 6 and rf.get('released') == 0, rf
            r2 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert r2.get('ok') and len(r2['candidates']) == 2, r2
            ids2 = [c['id'] for c in r2['candidates']]
            assert not (set(ids1) & set(ids2)), 'duplicate claim'
            b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                        'lease': r2['lease'], 'epoch': r2['epoch']})
            rf2 = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                              'lease': r2['lease'], 'epoch': r2['epoch'],
                              'outcome': 'unknown', 'expressed_ids': ids2})
            assert rf2.get('expressed') == 2, rf2
            n = b.db.execute(
                "SELECT COUNT(*) FROM candidates WHERE status='unknown'").fetchone()[0]
            assert n == 8, n
    finally:
        b.close()


def test_digest_char_budget_splits_rounds():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            for i in range(4):
                b.dispatch(life_q(mid, topic=f'cb{i}', text='x' * 2400))
            r1 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            # 2400*3=7200 <= 8000, 4th would exceed -> 3 first
            assert len(r1['candidates']) == 3, r1
            ids1 = [c['id'] for c in r1['candidates']]
            b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                        'lease': r1['lease'], 'epoch': r1['epoch']})
            b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                        'lease': r1['lease'], 'epoch': r1['epoch'],
                        'outcome': 'unknown', 'expressed_ids': ids1})
            r2 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert len(r2['candidates']) == 1, r2
    finally:
        b.close()


def test_digest_finish_partial_release():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            for i in range(3):
                b.dispatch(life_q(mid, topic=f'pr{i}'))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert len(r['candidates']) == 3, r
            b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                        'lease': r['lease'], 'epoch': r['epoch']})
            # express only the first; other two must return to pending, not unknown
            first = r['candidates'][0]['id']
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': r['lease'], 'epoch': r['epoch'],
                             'outcome': 'unknown', 'expressed_ids': [first]})
            assert rf.get('expressed') == 1 and rf.get('released') == 2, rf
            sts = dict(b.db.execute(
                "SELECT id, status FROM candidates").fetchall())
            assert sts[first] == 'unknown', sts
            for c in r['candidates'][1:]:
                assert sts[c['id']] == 'pending', sts
            # next round can claim the released ones
            r2 = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert len(r2['candidates']) == 2, r2
    finally:
        b.close()


def test_digest_finish_rejects_unknown_ids():
    b, _, mid = make_brain()
    try:
        with clock(4, 8, 0):
            b.dispatch(life_q(mid, topic='fk1'))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                        'lease': r['lease'], 'epoch': r['epoch']})
            try:
                b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                            'lease': r['lease'], 'epoch': r['epoch'],
                            'outcome': 'unknown', 'expressed_ids': [999999]})
                raise SystemExit('should have raised')
            except ValueError as e:
                assert 'expressed_ids_not_claimed' in str(e), e
    finally:
        b.close()


def test_concurrent_claim_mutual_exclusion():
    import threading
    import brain as brain_mod
    b, root, mid = make_brain()
    try:
        with clock(4, 8, 0):
            for i in range(4):
                b.dispatch(life_q(mid, topic=f'cc{i}'))
        b.close()
        barrier = threading.Barrier(2)
        results = {}

        def worker(name):
            bb = brain_mod.Brain(root)
            try:
                with clock(4, 8, 0):
                    barrier.wait(timeout=10)
                    r = bb.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
                    results[name] = r
            finally:
                bb.close()

        ts = [threading.Thread(target=worker, args=(f'w{i}',)) for i in range(2)]
        for t in ts:
            t.start()
        for t in ts:
            t.join(timeout=30)
        assert len(results) == 2, results
        got = [r for r in results.values()
               if r.get('ok') and r.get('candidates')]
        assert len(got) == 1, results  # exactly one winner
        winner_ids = {c['id'] for c in got[0]['candidates']}
        assert len(winner_ids) == 4, results
        loser = [r for r in results.values() if r is not got[0]][0]
        assert loser.get('busy') is True or loser.get('candidates') == [], loser
    finally:
        pass


# --- policy validation ----------------------------------------------------------

def _bad_policy(**kw):
    p = dict(POLICY)
    p.update(kw)
    return p


def test_policy_empty_object_fail_closed():
    b, root, mid = make_brain()
    try:
        Path(root, 'proactive-policy.json').write_text(json.dumps({}))
        with clock(4, 2, 0):
            r = b.dispatch(life_q(mid))
            assert r.get('reason') == 'policy_invalid', r
            r = b.dispatch({'op': 'proactive_check', 'scope': 'owner-private'})
            assert r['background_allowed'] is False, r
            assert r['can_notify'] is False, r
    finally:
        b.close()


def test_policy_bad_quiet_time_fail_closed():
    b, root, mid = make_brain()
    try:
        Path(root, 'proactive-policy.json').write_text(
            json.dumps(_bad_policy(quiet_start='25:00')))
        with clock(4, 8, 0):
            r = b.dispatch(life_q(mid))
            assert r.get('reason') == 'policy_invalid', r
    finally:
        b.close()


def test_policy_bad_types_fail_closed():
    b, root, mid = make_brain()
    try:
        for bad in ({'news_threshold': 'high'},
                    {'news_weights': {'relevance': 60, 'utility': 25}},
                    {'inferred_relevance_penalty': 2},
                    {'news_expiry_hours': 0},
                    {'quiet_end': '7:00'}):
            Path(root, 'proactive-policy.json').write_text(
                json.dumps(_bad_policy(**bad)))
            with clock(4, 8, 0):
                r = b.dispatch(life_q(mid, topic='pv'))
                assert r.get('reason') == 'policy_invalid', (bad, r)
                r = b.dispatch({'op': 'claim', 'scope': 'owner-private'})
                assert r.get('reason') == 'policy_invalid', (bad, r)
    finally:
        b.close()


def test_policy_list_shape_fail_closed():
    b, root, mid = make_brain()
    try:
        Path(root, 'proactive-policy.json').write_text(json.dumps([]))
        with clock(4, 8, 0):
            r = b.dispatch({'op': 'proactive_check', 'scope': 'owner-private'})
            assert r['background_allowed'] is False, r
    finally:
        b.close()


# --- authorize->finish 间隙复检 ---------------------------------------------------

def test_authorize_then_forget_source_finish_refused():
    b, _, _ = make_brain()
    try:
        mid1 = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                           'text': 's1', 'kind': 'fact', 'source': 't',
                           'event_id': 'e1', 'evidence': 'observed'})['id']
        mid2 = b.dispatch({'op': 'remember', 'scope': 'owner-private',
                           'text': 's2', 'kind': 'fact', 'source': 't',
                           'event_id': 'e2', 'evidence': 'observed'})['id']
        with clock(4, 8, 0):
            b.dispatch(life_q(mid1, topic='rs1'))
            b.dispatch(life_q(mid2, topic='rs2'))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert len(r['candidates']) == 2, r
            lease, epoch = r['lease'], r['epoch']
            ra = b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch})
            assert ra.get('ok'), ra
            # authorize 成功后 forget 其中一条的来源
            b.db.execute("UPDATE memories SET status='forgotten' WHERE id=?", (mid1,))
            b.db.commit()
            src_of = {c['id']: json.loads(c['sources']) for c in r['candidates']}
            bad = [cid for cid, s in src_of.items() if mid1 in s][0]
            good = [cid for cid, s in src_of.items() if mid2 in s][0]
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch, 'outcome': 'unknown',
                             'expressed_ids': [bad, good]})
            assert rf.get('ok') is not True, rf
            sts = dict(b.db.execute("SELECT id, status FROM candidates").fetchall())
            assert 'unknown' not in sts.values(), sts
            assert sts[bad] == 'cancelled', sts
            assert sts[good] == 'pending', sts
    finally:
        b.close()


def test_authorize_then_threshold_raised_finish_refused():
    b, root, mid = make_brain()
    try:
        with clock(4, 8, 0):
            # score = 60*1.0 + 25*0.6 + 15*0 = 75 > 70
            b.dispatch(news_q(mid, relevance=1.0, utility=0.6, novelty=0.0))
            r = b.dispatch({'op': 'digest_claim', 'scope': 'owner-private'})
            assert len(r['candidates']) == 1, r
            lease, epoch = r['lease'], r['epoch']
            ra = b.dispatch({'op': 'digest_authorize', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch})
            assert ra.get('ok'), ra
            # authorize 成功后调高阈值
            pol = json.loads(Path(root, 'proactive-policy.json').read_text())
            pol['news_threshold'] = 80
            Path(root, 'proactive-policy.json').write_text(json.dumps(pol))
            cid = r['candidates'][0]['id']
            rf = b.dispatch({'op': 'digest_finish', 'scope': 'owner-private',
                             'lease': lease, 'epoch': epoch, 'outcome': 'unknown',
                             'expressed_ids': [cid]})
            assert rf.get('ok') is not True, rf
            sts = dict(b.db.execute("SELECT id, status FROM candidates").fetchall())
            assert 'unknown' not in sts.values(), sts
            assert sts[cid] == 'cancelled', sts
    finally:
        b.close()
