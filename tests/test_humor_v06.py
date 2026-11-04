"""One isolated acceptance for evolving humor, source boundaries and signed gain."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

from personal_bot import deploy, vault
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c, humor, meme_store as memes, meme_sync


class HumorV06(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='humor-v06-isolated-')
        self.base=Path(self.temp.name); self.root=self.base/'state'
        deploy.init(self.root); deploy.enable(self.root,list(deploy.DEFAULT_FEATURES)); self.b=Brain(self.root)

    def tearDown(self):
        self.b.close(); self.temp.cleanup()

    def config(self, **values):
        return self.b.dispatch(dict(op='companion_expression_config',scope='owner-private',patch=values))

    def event(self, eid='one', **kwargs):
        q=dict(op='prepare',scope='owner-private',source='fixture:isolated',event_id=eid,
               actor='user',person_id='owner',text='一个普通的测试来信')
        q.update(kwargs); return self.b.dispatch(q)

    def assessment(self, amount=.3, **extra):
        a=dict(version=2,changed=True,label='难过',delta=dict(p=-.2,a=.1,d=0),intensity_delta=amount)
        a.update(extra); return a

    def learn(self, event, **extra):
        q=dict(op='meme_learn',scope='owner-private',source_event=event['event']['id'],title='地质五分钟',
               meaning='用很长的时间来吐槽拖延',mechanism='跨尺度反差',basis='observed',confidence=.9,
               bridges=[dict(**{'from':'五分钟','to':'地质年代','why':'反差夸张'})])
        q.update(extra); return self.b.dispatch(q)

    def public(self, slug='test-meme', title='地质五分钟'):
        return dict(slug=slug,title=title,summary='公开的简短解释',aliases=[],keywords=[],tags=[],updated_at='2026-11-04T00:00:00Z')

    def put_public(self, **extra):
        item=self.public(); item.update(extra)
        with self.b.db: memes.put_public(self.b,item)
        return item

    def test_defaults_atomic_readback_validation_and_owner_scope(self):
        self.assertEqual(humor.settings(self.b)['values']['banter_level'],50)
        before=humor.settings(self.b)
        with self.assertRaises(ValueError): self.config(emotion_gain=True)
        with self.assertRaises(ValueError): self.config(banter_level=50.2)
        self.assertEqual(before,humor.settings(self.b))
        changed=self.config(banter_level=90,emotion_gain=2)
        self.assertFalse(changed['values']['banter_enabled'])
        refused=self.b.dispatch(dict(op='companion_expression_config',patch=dict(banter_level=1),expected_revision=before['revision']))
        self.assertFalse(refused['ok']); self.assertEqual(humor.settings(self.b)['values']['banter_level'],90)
        with self.assertRaises(ValueError): self.b.dispatch(dict(op='companion_expression_config',scope='qq:group:fixture',patch=dict(banter_enabled=True)))
        self.b.close(); self.b=Brain(self.root)
        self.assertEqual(humor.settings(self.b)['values']['emotion_gain'],2)

    def test_signed_gain_clipping_and_retry_keeps_original_multiplier(self):
        self.config(emotion_gain=2)
        a=self.assessment(emotions=[dict(label='委屈',delta=.15)],relationship=dict(trust_delta=2))
        with patch.object(c,'stamp',return_value=1000):
            result=self.event(emotion_assessment=a)
            self.assertEqual(result['mood']['p'],-.4)
            self.assertEqual(result['mood']['labels'][0]['intensity'],.6)
            self.assertEqual(result['companion']['relationship']['trust'],52)
            effect=result['emotion_effect']; self.assertEqual(effect['raw_labels'][0]['delta'],.3)
            self.assertEqual(effect['applied_labels'][0]['delta'],.6)
            self.config(emotion_gain=3)
            retry=self.event(emotion_assessment=a)
            self.assertEqual(retry['emotion']['status'],'replayed')
            self.assertEqual(retry['emotion_effect']['gain'],2)
            self.assertEqual(retry['reaction']['emotions'][0]['delta'],.6)
            self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_emotion_effect').fetchone()[0],1)

    def test_comfort_scales_and_zero_does_not_refresh_existing_mood(self):
        self.config(emotion_gain=2)
        with patch.object(c,'stamp',return_value=1000):
            self.event('sad',emotion_assessment=self.assessment())
            comfort=self.assessment(-.2,delta=dict(p=.1,a=-.1,d=0))
            eased=self.event('comfort',emotion_assessment=comfort)
            self.assertAlmostEqual(eased['mood']['labels'][0]['intensity'],.2)
            self.assertEqual(eased['emotion_effect']['applied_labels'][0]['delta'],-.4)
            old=dict(self.b.db.execute("SELECT * FROM mood WHERE scope='owner-private'").fetchone())
            self.config(emotion_gain=0)
            zero=self.event('zero',emotion_assessment=self.assessment())
            self.assertEqual(zero['emotion']['status'],'unchanged'); self.assertFalse(zero['reaction']['changed'])
            self.assertEqual(old,dict(self.b.db.execute("SELECT * FROM mood WHERE scope='owner-private'").fetchone()))
        with patch.object(c,'stamp',return_value=1000+8*3600):
            self.assertAlmostEqual(c.mood(self.b,'owner-private')['p'],old['p']*.5,places=4)

    def test_final_state_limit_is_distinct_from_raw_validation(self):
        with patch.object(c,'stamp',return_value=1000):
            self.event('initial',emotion_assessment=self.assessment(.2))
            self.config(emotion_gain=2)
            result=self.event('saturate',emotion_assessment=self.assessment(.3))
            self.assertEqual(result['emotion_effect']['applied_labels'][0]['delta'],.4)
            invalid=self.event('invalid',emotion_assessment=self.assessment(.46))
            self.assertEqual(invalid['emotion']['status'],'invalid')

    def test_counterattack_independent_and_quotation_not_hostility(self):
        self.config(banter_level=0,banter_enabled=False)
        raw=dict(incoming='attack',severity=.9,directed_at_self=True,requested_roast=False)
        result=self.event('attack',humor_assessment=raw)['expression_context']
        self.assertTrue(result['counterattack_allowed']); self.assertGreater(result['effective_banter_level'],70)
        self.assertIn('损长相、怎么损怎么来',result['band'])
        raw['incoming']='quoted'
        quoted=self.event('quote',humor_assessment=raw)['expression_context']
        self.assertFalse(quoted['counterattack_allowed']); self.assertFalse(quoted['directed_banter_allowed'])
        self.config(counterattack_enabled=False)
        raw['incoming']='attack'
        self.assertFalse(self.event('off',humor_assessment=raw)['expression_context']['counterattack_allowed'])

    def test_person_can_stop_without_mutating_global_settings(self):
        self.config(banter_enabled=True)
        event=self.event()
        self.b.dispatch(dict(op='meme_preference',scope='owner-private',source_event=event['event']['id'],muted_until=253402300799))
        self.assertTrue(humor.settings(self.b)['values']['banter_enabled'])
        self.assertFalse(self.event('after')['expression_context']['directed_banter_allowed'])

    def test_scoped_learning_independent_evidence_correction_and_forgetting(self):
        e1=self.event(); first=self.learn(e1)
        self.assertEqual(first['status'],'candidate'); self.assertTrue(self.learn(e1)['replayed'])
        self.assertFalse(self.learn(e1,meaning='同一事件不同内容')['ok'])
        e2=self.event('two'); learned=self.learn(e2)
        self.assertEqual(learned['status'],'active'); self.assertEqual(learned['evidence_count'],2)
        query=dict(op='meme_search',scope='owner-private',text='地质五分钟')
        self.assertEqual(len(self.b.dispatch(query)['items']),1)
        self.assertEqual(self.b.dispatch(dict(query,scope='qq:group:fixture'))['items'],[])
        e3=self.event('explain'); self.learn(e3,basis='explained',meaning='用户纠正后的具体语境')
        self.assertIn('纠正',self.b.dispatch(query)['items'][0]['meaning'])
        self.b.db.execute("UPDATE source_events SET status='forgotten'"); self.b.db.commit()
        self.assertEqual(self.b.dispatch(query)['items'],[])

    def test_public_update_keeps_local_explanation_and_scope_feedback(self):
        self.put_public()
        event=self.event(); self.learn(event,basis='explained')
        self.put_public(summary='网站更新后的定义')
        query=dict(op='meme_search',scope='owner-private',text='地质五分钟')
        self.assertEqual(self.b.dispatch(query)['items'][0]['origin'],'private')
        feedback_event=self.event('feedback')
        self.b.dispatch(dict(op='meme_feedback',scope='owner-private',source_event=feedback_event['event']['id'],id='public:test-meme',outcome='disliked'))
        self.assertTrue(self.b.dispatch(dict(query,scope='qq:group:fixture'))['items'])
        row=self.b.db.execute('SELECT id FROM ct_meme_private').fetchone()
        self.b.dispatch(dict(op='meme_feedback',scope='owner-private',source_event=feedback_event['event']['id'],id=row[0],outcome='misused'))
        self.assertEqual(self.b.dispatch(query)['items'],[])

    def test_prepare_optional_updates_and_stable_association_patterns(self):
        update=dict(title='反向闹钟',meaning='用反转表达赖床',mechanism='反转',basis='explained',confidence=.9,
                    bridges=[dict(**{'from':'起床','to':'反向闹钟','why':'把功能倒过来'})])
        result=self.event(meme_updates=[update],humor_assessment=dict(incoming='playful'))
        self.assertEqual(result['humor_updates']['learning'][0]['status'],'active')
        patterns=result['expression_context']['association_patterns']; self.assertEqual(len(patterns),1)
        self.assertEqual(patterns,self.event()['expression_context']['association_patterns'])
        bad=self.event('bad',meme_updates=[dict(title=3)],humor_assessment=dict(incoming='unknown'))
        self.assertTrue(bad['ok']); self.assertEqual(bad['humor_updates']['learning'][0]['status'],'invalid')
        outgoing=self.event('outgoing',actor='assistant',meme_updates=[update])
        self.assertEqual(outgoing['humor_updates']['learning'][0]['status'],'invalid')

    def test_disabled_auto_lookup_does_not_disable_explicit_search(self):
        self.put_public(); self.config(auto_memes=False)
        self.assertEqual(self.event(text='地质五分钟')['expression_context']['candidates'],[])
        self.assertTrue(self.b.dispatch(dict(op='meme_search',scope='owner-private',text='地质五分钟'))['items'])

    def test_api_wrapped_detail_and_retryable_pending_queue(self):
        item=self.public()
        page=dict(schema_version=1,items=[item],has_more=False)
        detail=dict(schema_version=1,item=dict(item,content_html='<p>实际正文</p><script>do_not_run()</script>'))
        with patch.object(meme_sync,'get_json',side_effect=[page,ValueError('public_api_server_error')]),patch.object(meme_sync.time,'sleep'):
            first=meme_sync.sync(self.b)
        self.assertEqual(first['status'],'partial'); self.assertIsNone(first['last_success_at'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_meme_pending').fetchone()[0],1)
        with patch.object(meme_sync,'get_json',side_effect=[page,detail]),patch.object(meme_sync.time,'sleep'):
            second=meme_sync.sync(self.b)
        self.assertEqual(second['status'],'complete')
        body=json.loads(self.b.db.execute('SELECT payload FROM ct_meme_public').fetchone()[0])['other']
        self.assertIn('实际正文',body); self.assertNotIn('do_not_run',body)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_meme_pending').fetchone()[0],0)

    def test_partial_paging_resumes_and_full_absence_requires_404(self):
        item=self.put_public()
        with patch.object(meme_sync,'get_json',return_value=dict(schema_version=1,items=[item],has_more=True)),patch.object(meme_sync.time,'sleep'):
            first=meme_sync.sync(self.b,max_pages=1,max_details=0)
        self.assertEqual(first['offset'],30); self.assertEqual(first['status'],'partial')
        with patch.object(meme_sync,'get_json',return_value=dict(schema_version=1,items=[],has_more=False)) as get:
            meme_sync.sync(self.b,max_details=0)
            self.assertIn('offset=30',get.call_args.args[0])
        with patch.object(meme_sync,'get_json',return_value=dict(schema_version=1,items=[],has_more=False)):
            scan=meme_sync.sync(self.b,mode='full',max_details=0)
        self.assertEqual(scan['status'],'partial')
        self.assertEqual(self.b.db.execute('SELECT available FROM ct_meme_public').fetchone()[0],1)
        with patch.object(meme_sync,'get_json',side_effect=[dict(schema_version=1,items=[],has_more=False),ValueError('public_api_http_404')]):
            meme_sync.sync(self.b)
        self.assertEqual(self.b.db.execute('SELECT available FROM ct_meme_public').fetchone()[0],0)

    def test_sync_disabled_and_malformed_response_preserve_good_corpus(self):
        self.put_public(); self.config(meme_sync_enabled=False)
        with patch.object(meme_sync,'get_json') as get:
            self.assertEqual(meme_sync.sync(self.b)['status'],'disabled_by_config'); get.assert_not_called()
        self.config(meme_sync_enabled=True)
        with patch.object(meme_sync,'get_json',return_value=dict(items='invalid')):
            result=meme_sync.sync(self.b)
        self.assertFalse(result['ok']); self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_meme_public').fetchone()[0],1)
        self.assertIsNone(result.get('last_success_at'))

    def test_panel_and_native_backup_preserve_real_settings_and_learning(self):
        self.config(emotion_gain=1.5)
        self.learn(self.event(),basis='explained')
        panel=self.b.dispatch(dict(op='companion_panel'))
        html=Path(panel['path']).read_text(encoding='utf-8')
        data=json.loads(html.split('id="snapshot">')[1].split('</script>')[0])
        self.assertEqual(data['expression_settings']['values']['banter_level'],50)
        self.assertEqual(data['expression_settings']['values']['emotion_gain'],1.5)
        self.assertEqual(data['meme_knowledge']['private_counts']['active'],1)
        self.assertIn("connect-src 'none'",html)
        self.assertIn('情绪影响值',html); self.assertIn('自动思考梗',html)
        out=self.base/'snapshot'; vault.export_snapshot(self.root,out,'a'*40,bootstrap=True)
        with closing(sqlite3.connect(out/'brain.sqlite')) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM ct_meme_private').fetchone()[0],1)

    def test_timezone_required_and_text_cleaning(self):
        with self.assertRaises(ValueError): meme_sync.timestamp('2026-11-05T07:00:00')
        self.assertEqual(meme_sync.timestamp('2026-11-05T07:00:00+08:00'),meme_sync.timestamp('2026-11-04T23:00:00Z'))
        self.assertEqual(meme_sync.plain('<p>第一段 &amp; 正文</p><style>hidden</style>'),'第一段 & 正文')

    def test_withdrawn_correction_cannot_borrow_old_meaning_evidence(self):
        original=self.event('original'); self.learn(original,basis='explained',meaning='解释A')
        corrected=self.event('corrected'); self.learn(corrected,basis='explained',meaning='解释B')
        query=dict(op='meme_search',scope='owner-private',text='地质五分钟')
        self.assertEqual(self.b.dispatch(query)['items'][0]['meaning'],'解释B')
        self.b.db.execute("UPDATE source_events SET status='forgotten' WHERE id=?",(corrected['event']['id'],));self.b.db.commit()
        self.assertEqual(self.b.dispatch(query)['items'],[])

    def test_old_preference_retry_cannot_undo_new_stop(self):
        first=self.event('resume',occurred_at=100)
        resume=dict(op='meme_preference',scope='owner-private',source_event=first['event']['id'],muted_until=0)
        self.b.dispatch(resume)
        second=self.event('stop',occurred_at=200)
        self.b.dispatch(dict(resume,source_event=second['event']['id'],muted_until=253402300799))
        self.assertTrue(self.b.dispatch(resume)['replayed'])
        self.assertEqual(self.b.db.execute('SELECT muted_until FROM ct_humor_preference').fetchone()[0],253402300799)

    def test_style_disable_also_blocks_prepare_humor_side_effects(self):
        self.b.dispatch(dict(op='configure',modules=dict(style=False)))
        result=self.event(meme_updates=[dict(title='不能学习',meaning='不应写入',basis='explained',confidence=.9)])
        self.assertTrue(result['expression_context']['disabled'])
        self.assertTrue(result['humor_updates']['disabled'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_meme_private').fetchone()[0],0)


if __name__=='__main__': unittest.main()
