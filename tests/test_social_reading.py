"""One final isolated acceptance; no browser, network or production queues."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain

PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'social-reading'


class SocialReading(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='social-reading-isolated-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        self.b = Brain(self.root)
        self.addCleanup(self.b.close)
        self.manage('install', source_dir=str(PLUGIN))
        self.manage('enable')
        self.seq = 0

    def manage(self, action, **values):
        return self.b.dispatch(dict(op='plugin_manage', scope='owner-private', plugin='social-reading', action=action, **values))

    def call(self, action, **values):
        return self.b.dispatch(dict(op='plugin_call', scope='owner-private', plugin='social-reading', action=action, **values))

    def owner(self, message):
        self.seq += 1
        return self.b.dispatch(dict(op='capture', scope='owner-private', source='fixture:social-owner',
                                    event_id='owner-' + str(self.seq), actor='user', text=message))['event']['id']

    def allow(self, name='合成论坛'):
        event = self.owner('允许阅读 ' + name)
        sid = self.call('source_add', input=name, owner_event=event, authorized=True)['source']['id']
        source = self.call('status')['sources'][-1]
        self.call('source_verify', source_id=sid, status='verified', url=source['url'],
                  observed_name=name + '吧', title=name + '吧-百度贴吧', receipt='fixture:verification')
        return sid

    def packet(self, sid, tid=100, **changes):
        source = next(s for s in self.call('status')['sources'] if s['id'] == sid)
        p = dict(schema='social-observation-v1', provider='tieba', status='ok',
                 forum_url=source['url'], url='https://tieba.baidu.com/p/' + str(tid),
                 title='Synthetic isolated thread', tool='browser.browse', receipt='fixture:native-' + str(tid),
                 coverage=dict(pages_seen=[1], total_pages=1, ended=True, all_visible_floors=True),
                 floors=[dict(pid='floor-' + str(tid), floor=1, author='SyntheticAuthor', is_op=True,
                              text='先停一下。然后突然换个角度。', replies=[dict(author='SyntheticReply', text='这个转折很有趣。')],
                              images=[dict(url='https://tiebapic.baidu.com/fixture.jpg', quality='thumb', observation='url_only')])])
        p.update(changes)
        return p

    def observe(self, sid, tid=100, **changes):
        self.seq += 1
        job = self.call('plan', manual=True, source_id=sid, job_id='fixture-job-' + str(self.seq))
        packet = self.packet(sid, tid, **changes)
        return self.call('observe', lease_id=job['lease_id'], observation=packet), job, packet

    def test_optional_install_source_onboarding_and_failed_verification(self):
        self.assertTrue(self.call('onboarding')['required'])
        self.assertEqual(self.call('plan', manual=True)['action'], 'awaiting_sources')
        event = self.owner('允许 合成论坛')
        sid = self.call('source_add', input='合成论坛', owner_event=event, authorized=True)['source']['id']
        self.assertEqual(self.call('plan', manual=True)['action'], 'awaiting_verification')
        with self.assertRaisesRegex(ValueError, 'not_verified'):
            self.call('source_verify', source_id=sid, status='verified', url='https://tieba.baidu.com/f?kw=合成论坛',
                      observed_name='别的论坛', title='百度安全验证', receipt='fixture:blocked')
        self.call('source_verify', source_id=sid, status='blocked', title='百度安全验证', receipt='fixture:blocked')
        self.assertEqual(self.call('status')['sources'][0]['status'], 'blocked')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_document').fetchone()[0], 0)

    def test_official_url_authorization_and_scope_gates(self):
        event = self.owner('允许 https://tieba.baidu.com.evil.example/f?kw=x')
        with self.assertRaisesRegex(ValueError, 'official_https'):
            self.call('source_add', input='https://tieba.baidu.com.evil.example/f?kw=x', owner_event=event, authorized=True)
        with self.assertRaisesRegex(ValueError, 'authorization_source'):
            self.call('source_add', input='x')
        with self.assertRaisesRegex(ValueError, 'owner_admin_only'):
            self.b.dispatch(dict(op='plugin_call', scope='qq:group:fixture', plugin='social-reading', action='status'))
        with self.assertRaisesRegex(ValueError, 'planned_not_implemented'):
            self.call('source_add', provider='bilibili', input='x')

    def test_actual_observation_partial_coverage_replay_and_no_automatic_emotion(self):
        sid = self.allow()
        result, job, packet = self.observe(sid, coverage=dict(pages_seen=[1], total_pages=30, ended=False, all_visible_floors=True))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['emotion_template']['emotion_deltas']), 48)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0], 0)
        before = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        self.assertTrue(self.call('observe', lease_id=job['lease_id'], observation=packet)['replayed'])
        self.assertEqual(before, self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])
        changed = copy.deepcopy(packet)
        changed['floors'][0]['text'] = 'A different input'
        with self.assertRaisesRegex(ValueError, 'content_conflict'):
            self.call('observe', lease_id=job['lease_id'], observation=changed)
        read = self.call('read', document_id=result['document_id'])
        self.assertEqual(read['floors'][0]['images'][0]['observation'], 'url_only')
        self.assertFalse(read['floors'][0]['images'][0]['downloaded'])
        again, _, _ = self.observe(sid, coverage=dict(pages_seen=[1], total_pages=30, ended=False, all_visible_floors=True))
        self.assertTrue(again['replayed'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_document').fetchone()[0], 1)

    def test_source_revocation_and_wrong_forum_stop_pending_work(self):
        sid = self.allow()
        job = self.call('plan', manual=True, source_id=sid, job_id='fixture:revocation')
        packet = self.packet(sid)
        packet['forum_url'] = 'https://tieba.baidu.com/f?kw=别的论坛'
        with self.assertRaisesRegex(ValueError, 'forum_not_allowed'):
            self.call('observe', lease_id=job['lease_id'], observation=packet)
        event = self.owner('停止阅读这个论坛')
        self.call('source_revoke', source_id=sid, owner_event=event, authorized=True)
        with self.assertRaisesRegex(ValueError, 'lease'):
            self.call('observe', lease_id=job['lease_id'], observation=self.packet(sid))

    def test_evidence_accumulation_forms_voice_and_owner_feedback_stops_it(self):
        sid = self.allow()
        candidate = dict(pattern='短暂停顿后，换一个意外但有关联的角度。', mechanism='先接当前话，再用共同点完成跳转。',
                         example='等会儿。这个转弯，我好像在哪见过。', evidence_quote='先停一下。然后突然换个角度。')
        for tid in (201, 202, 203):
            result, _, _ = self.observe(sid, tid)
            reflection = self.call('reflect', document_id=result['document_id'], summary='合成的阅读反思。', style_candidates=[candidate])
        habit = reflection['habits'][0]
        self.assertEqual(habit['exposures'], 3)
        self.assertEqual(habit['status'], 'trial')
        self.assertTrue(self.call('reflect', document_id=result['document_id'], summary='合成的阅读反思。', style_candidates=[candidate])['replayed'])
        prepared = self.b.dispatch(dict(op='prepare', scope='owner-private', actor='user', source='fixture:social-owner',
                                        event_id='voice-fixture', text='一条普通合成来信'))
        self.assertEqual(prepared['expression_context']['learned_voice']['social-reading'][0]['id'], habit['id'])
        for i in range(2):
            e = self.owner('这个说法很好 ' + str(i))
            self.call('habit_feedback', habit_id=habit['id'], owner_event=e, authorized=True, polarity='positive')
        self.assertEqual(self.call('status')['habits'][0]['status'], 'mature')
        e = self.owner('别再学这种说法')
        self.call('habit_feedback', habit_id=habit['id'], owner_event=e, authorized=True, polarity='stop')
        from muse_ext.plugins import context
        self.assertEqual(context(self.b, {'scope': 'owner-private'})['social-reading']['voice_overlay'], [])
        self.assertEqual(context(self.b, {'scope': 'qq:group:fixture'}), {})

    def test_broken_plugin_does_not_break_core_prepare_or_panel(self):
        path = self.root / 'extensions/social-reading/reader.py'
        path.write_text('damaged fixture', encoding='utf-8')
        result = self.b.dispatch(dict(op='prepare', scope='owner-private', actor='user', source='fixture:social-owner',
                                      event_id='broken-fixture', text='普通合成来信'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['plugin_context']['social-reading']['status'], 'unavailable')
        result = self.b.dispatch({'op': 'companion_panel'})
        html = Path(result['path']).read_text(encoding='utf-8')
        self.assertIn('data-detail="plugins"', html)
        self.assertNotIn('data-detail="updates" aria-label=', html)
        data = json.loads(html.split('id="snapshot">')[1].split('</script>')[0])
        self.assertEqual(data['plugins']['items'][0]['status'], 'unavailable')

    def test_model_interest_gate_and_paused_plugin_cannot_leave_shareable_events(self):
        sid = self.allow()
        result, _, _ = self.observe(sid)
        from muse_ext.emotion_full48 import template
        assessment = template()
        assessment['share'] = True
        self.assertEqual(self.call('pending')['documents'][0]['document_id'], result['document_id'])
        applied = self.call('appraise', document_id=result['document_id'], interest_score=90, emotion_assessment=assessment)
        self.assertTrue(applied['pipeline_ok'])
        self.assertEqual(self.call('pending')['documents'], [])
        self.assertTrue(applied['share_eligible'])
        self.assertEqual(self.b.db.execute('SELECT share FROM ct_life WHERE source_event=?', (result['source_event'],)).fetchone()[0], 'pending')
        self.manage('disable')
        with patch('muse_ext.companion.quiet', return_value=False):
            claimed = self.b.dispatch(dict(op='companion_share', scope='owner-private', action='claim'))
        self.assertEqual(claimed['events'], [])

    def test_bad_manifest_and_lease_serialization(self):
        bad = Path(self.temp.name) / 'bad-plugin'
        bad.mkdir()
        m = json.loads((PLUGIN / 'manifest.json').read_text(encoding='utf-8'))
        m['files'] = {'../outside.py': '0' * 64, '__init__.py': '0' * 64}
        (bad / 'manifest.json').write_text(json.dumps(m), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unsafe_plugin_path'):
            self.manage('install', source_dir=str(bad))
        sid = self.allow()
        first = self.call('plan', manual=True, source_id=sid, job_id='fixture:serial')
        self.assertEqual(first['action'], 'browse')
        self.assertEqual(self.call('plan', manual=True, source_id=sid, job_id='fixture:serial')['action'], 'busy')

    def test_nullable_fields_and_exact_url_keywords(self):
        links = ['https://tieba.baidu.com/f?kw=fixture', 'https://tieba.baidu.com/f?kw=fixture%E5%90%A7']
        event = self.owner('允许 ' + ' '.join(links))
        one = self.call('source_add', input=links[0], owner_event=event, authorized=True)['source']['id']
        two = self.call('source_add', input=links[1], owner_event=event, authorized=True)['source']['id']
        self.assertNotEqual(one, two)
        with self.assertRaisesRegex(ValueError, 'not_verified'):
            self.call('source_verify', source_id=one, status='verified', url=links[1], observed_name='fixture吧',
                      title='fixture吧', receipt='fixture:wrong-keyword')
        self.call('source_verify', source_id=one, status='verified', url=links[0], observed_name='fixture吧',
                  title='fixture吧', receipt='fixture:verified')
        packet = self.packet(one)
        packet['floors'][0].update(pid=None, author=None, posted_at=None)
        packet['floors'][0]['replies'][0]['author'] = None
        job = self.call('plan', manual=True, source_id=one, job_id='fixture:nullable')
        result = self.call('observe', lease_id=job['lease_id'], observation=packet)
        self.assertTrue(result['ok'])
        floor = self.call('read', document_id=result['document_id'])['floors'][0]
        self.assertIsNone(floor['pid'])
        self.assertIsNone(floor['author'])

    def test_coverage_metadata_does_not_duplicate_events_and_retry_repairs_registration(self):
        sid = self.allow()
        first, _, _ = self.observe(sid, 801, coverage=dict(pages_seen=[1], total_pages=None, ended=False, all_visible_floors=False))
        before = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        again, _, _ = self.observe(sid, 801)
        self.assertEqual(first['document_id'], again['document_id'])
        self.assertEqual(first['source_event'], again['source_event'])
        self.assertEqual(again['status'], 'complete')
        self.assertEqual(before, self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])
        job = self.call('plan', manual=True, source_id=sid, job_id='fixture:interruption')
        packet = self.packet(sid, 802)
        original = self.b.dispatch
        def interrupted(request):
            if request.get('op') == 'companion_observe':
                raise RuntimeError('isolated simulated interruption')
            return original(request)
        with patch.object(self.b, 'dispatch', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'interruption'):
                self.call('observe', lease_id=job['lease_id'], observation=packet)
        doc = self.b.db.execute('SELECT * FROM sr_document WHERE url=?', ('https://tieba.baidu.com/p/802',)).fetchone()
        self.assertIsNone(self.b.db.execute('SELECT id FROM ct_life WHERE source_event=?', (doc['event'],)).fetchone())
        repaired = self.call('observe', lease_id=job['lease_id'], observation=packet)
        self.assertTrue(repaired['replayed'])
        self.assertIsNotNone(self.b.db.execute('SELECT id FROM ct_life WHERE source_event=?', (doc['event'],)).fetchone())

    def growth_candidate(self, **changes):
        value = dict(domain='temperament', trait='更愿意主动提出有趣的不同看法',
                     interpretation='这种转折让我觉得表达不同想法也可以轻松，不必一直附和。',
                     example='我倒有个歪一点的想法。', evidence_quote='先停一下。然后突然换个角度。',
                     resonance=1, direction='adopt')
        value.update(changes)
        return value

    def enable_growth(self):
        event = self.owner('允许阅读影响你的偏好和性格')
        self.call('configure', owner_event=event, authorized=True, patch={'personality_growth': True})

    def reflect_growth(self, document, **changes):
        return self.call('reflect', document_id=document, summary='合成反思：想逐渐形成自己的表达与性情。',
                         growth_candidates=[self.growth_candidate(**changes)])['growth']

    def test_growth_requires_opt_in_and_observed_model_evidence(self):
        sid = self.allow()
        result, _, _ = self.observe(sid, 901)
        self.assertEqual(self.reflect_growth(result['document_id'])['status'], 'disabled')
        self.assertEqual(self.call('status')['personality_growth'], [])
        self.enable_growth()
        with self.assertRaisesRegex(ValueError, 'growth_evidence'):
            self.reflect_growth(result['document_id'], evidence_quote='这句从未读到过')
        with self.assertRaisesRegex(ValueError, 'growth_resonance'):
            self.reflect_growth(result['document_id'], resonance=float('nan'))
        applied = self.reflect_growth(result['document_id'])
        self.assertEqual(applied['applied'], 1)
        self.assertEqual(self.reflect_growth(result['document_id'])['status'], 'replayed')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0], 0)

    def test_growth_composes_current_persona_and_matures_over_independent_days(self):
        sid = self.allow()
        self.enable_growth()
        from muse_ext.plugins import load
        module = load(self.b, 'social-reading')
        for i in range(8):
            result, _, _ = self.observe(sid, 920 + i)
            with patch.object(module.growth.time, 'time', return_value=1793900000 + i*86400):
                applied = self.reflect_growth(result['document_id'])
        trait = applied['traits'][0]
        self.assertEqual(trait['status'], 'integrated')
        self.assertEqual(trait['supports'], 8)
        self.assertAlmostEqual(trait['strength'], .16)
        prepared = self.b.dispatch(dict(op='prepare', scope='owner-private', actor='user', source='fixture:social-owner',
                                       event_id='grown-persona-fixture', text='一条普通合成消息'))
        overlay = prepared['current_persona']['growth_overlay']['social-reading']
        self.assertEqual(overlay['traits'][0]['id'], trait['id'])
        self.assertIn('revise flexible old personality', overlay['authority'])
        self.assertEqual(self.b.dispatch(dict(op='prepare',scope='qq:group:fixture',actor='user',
            source='fixture:group',event_id='no-private-growth',text='普通合成消息'))['current_persona']['growth_overlay'], {})

    def test_growth_daily_budget_same_thread_reuse_and_inactive_sources(self):
        sid = self.allow()
        self.enable_growth()
        from muse_ext.plugins import load
        module = load(self.b, 'social-reading')
        for i in range(8):
            result, _, _ = self.observe(sid, 940 + i)
            with patch.object(module.growth.time,'time',return_value=1793900000):
                applied = self.reflect_growth(result['document_id'])
        self.assertAlmostEqual(applied['traits'][0]['strength'], .06)
        self.assertLessEqual(applied['traits'][0]['supports'], 3)
        modified, _, _ = self.observe(sid, 940, title='同帖变更的合成标题')
        with patch.object(module.growth.time,'time',return_value=1793900000+86400):
            again = self.reflect_growth(modified['document_id'])
        self.assertAlmostEqual(again['traits'][0]['strength'], .06)
        with self.b.db:
            self.b.db.execute("UPDATE source_events SET status='retired' WHERE actor='article'")
        self.assertEqual(module.growth.context(self.b)['traits'], [])

    def test_growth_can_reconsider_and_owner_stop_never_reactivates(self):
        sid = self.allow()
        self.enable_growth()
        for tid in (960,961):
            result, _, _ = self.observe(sid, tid)
            applied = self.reflect_growth(result['document_id'])
        trait = applied['traits'][0]
        result, _, _ = self.observe(sid, 962)
        reconsidered = self.reflect_growth(result['document_id'], existing_id=trait['id'], direction='reconsider')
        self.assertAlmostEqual(reconsidered['traits'][0]['strength'], .02)
        event = self.owner('不要再形成这种性格')
        self.call('growth_feedback', growth_id=trait['id'], owner_event=event, authorized=True, polarity='stop')
        result, _, _ = self.observe(sid, 963)
        stopped = self.reflect_growth(result['document_id'], existing_id=trait['id'])
        self.assertEqual(stopped['traits'][0]['status'], 'stopped')
        self.assertEqual(stopped['applied'], 0)
        event = self.owner('暂停人格成长')
        self.call('configure',owner_event=event,authorized=True,patch={'personality_growth':False})
        self.assertFalse(self.call('status')['settings']['personality_growth'])

    def test_phone_life_40_60_selection_and_editable_ratio(self):
        from muse_ext import companion as c, life_routine
        from datetime import datetime
        noon = datetime(2026,11,6,12,tzinfo=c.TZ).timestamp()
        self.assertEqual(life_routine.settings(self.b)['phone_probability'], .6)
        self.assertEqual(life_routine.settings(self.b)['chores_probability'], .4)
        with patch.object(c,'stamp',return_value=noon):
            c._set(self.b,'dream_day','2026-11-06')
            for roll, expected in ((.59,True),(.61,False)):
                c._set(self.b,'life',dict(activity=None,next_at=0));self.b.db.commit()
                with patch.object(c.RNG,'random',return_value=roll):
                    tick = self.b.dispatch(dict(op='companion_tick'))
                self.assertEqual(c._get(self.b,'life')['activity']['name']=='刷手机', expected)
        changed = self.b.dispatch(dict(op='companion_life_config',patch={'phone_probability':.75}))
        self.assertEqual(changed['settings']['chores_probability'], .25)
        with self.assertRaisesRegex(ValueError,'0_to_1'):
            self.b.dispatch(dict(op='companion_life_config',patch={'phone_probability':1.2}))
        with self.assertRaisesRegex(ValueError,'owner_scope'):
            self.b.dispatch(dict(op='companion_life_config',scope='qq:group:fixture',patch={'phone_probability':.5}))

    def test_phone_intent_dispatches_real_reader_once_and_never_fakes_content(self):
        import time
        from muse_ext import companion as c, life_routine
        request = life_routine.start(self.b,time.time(),1200);self.b.db.commit()
        unavailable = self.call('plan',life_intent=request['id'])
        self.assertEqual(unavailable['action'],'awaiting_sources')
        self.assertEqual(self.b.dispatch(dict(op='companion_phone'))['request']['status'],'unavailable')
        self.assertNotIn('实际读到',life_routine.outcome(self.b,request['id']))
        sid = self.allow()
        request = life_routine.start(self.b,time.time(),1200);self.b.db.commit()
        job = self.call('plan',life_intent=request['id'],job_id='cannot-bypass-stable-life-id')
        self.assertEqual(job['job_id'],'life-phone:'+request['id'])
        self.assertFalse(self.b.dispatch(dict(op='companion_phone'))['actionable'])
        with self.assertRaisesRegex(ValueError,'active_pending_phone'):
            self.call('plan',life_intent=request['id'])
        result = self.call('observe',lease_id=job['lease_id'],observation=self.packet(sid,980))
        self.assertEqual(result['phone']['status'],'read')
        self.assertEqual(self.b.dispatch(dict(op='companion_phone'))['request']['document_id'], result['document_id'])
        self.assertIn('真实阅读',life_routine.outcome(self.b,request['id']))

    def test_single_post_budget_is_shared_across_traits_and_edited_versions(self):
        sid = self.allow()
        self.enable_growth()
        result,_,_ = self.observe(sid,990)
        one = self.growth_candidate(trait='一个合成的性情变化')
        two = self.growth_candidate(trait='另一个合成的性情变化')
        self.call('reflect',document_id=result['document_id'],summary='合成反思',growth_candidates=[one,two])
        total = self.b.db.execute('SELECT sum(abs(delta)) FROM sr_growth_evidence').fetchone()[0]
        self.assertAlmostEqual(total,.02)
        modified,_,_ = self.observe(sid,990,title='同帖修订的合成标题')
        self.reflect_growth(modified['document_id'],trait='同帖修订再学第三个性情')
        self.assertAlmostEqual(self.b.db.execute('SELECT sum(abs(delta)) FROM sr_growth_evidence').fetchone()[0],.02)

    def test_phone_intent_is_rechecked_inside_lease_claim(self):
        import time
        from muse_ext import life_routine
        from muse_ext.plugins import load
        self.allow()
        request=life_routine.start(self.b,time.time(),1200);self.b.db.commit()
        module=load(self.b,'social-reading')
        original=module.reader._plan
        def other_consumer_finished(b,q):
            life_routine.mark(b,request['id'],'read',document_id='fixture:interleaved-consumer')
            return original(b,q)
        with patch.object(module.reader,'_plan',side_effect=other_consumer_finished):
            with self.assertRaisesRegex(ValueError,'active_pending_phone'):
                self.call('plan',life_intent=request['id'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_lease').fetchone()[0],0)

    def test_owner_can_change_large_reading_budget_without_editing_sealed_code(self):
        event=self.owner('把这次阅读预算改长一些')
        result=self.call('configure',owner_event=event,authorized=True,patch={'max_pages':50,'budget_seconds':600})
        self.enable_growth()
        self.assertEqual(self.call('status')['settings']['max_pages'],50)
        self.assertEqual(self.call('status')['settings']['budget_seconds'],600)


if __name__ == '__main__':
    unittest.main()
