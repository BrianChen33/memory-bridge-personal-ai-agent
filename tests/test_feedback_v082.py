"""Single-pass isolated acceptance for late repair and heartbeat publication."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0,str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c, feedback, panel_refresh
from muse_ext.emotion_full48 import template


class Feedback(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='feedback-isolated-')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/'state'
        deploy.init(self.root);deploy.enable(self.root,list(deploy.DEFAULT_FEATURES))
        self.b=Brain(self.root);self.addCleanup(self.b.close)
        self.now=time.time()
        clock_patch=patch.object(c,'stamp',return_value=self.now)
        self.clock=clock_patch.start();self.addCleanup(clock_patch.stop)

    def event(self,key,age=1800,actor='user',source='main:sticker'):
        result=self.b.dispatch(dict(op='prepare',scope='owner-private',source=source,event_id=key,
            actor=actor,person_id='owner',text='An isolated original event '+key,occurred_at=self.now-age))
        return result['event']['id']

    def call(self,action,**kw):
        return self.b.dispatch(dict(op='companion_feedback',scope='owner-private',action=action,**kw))

    def test_repair_is_decayed_idempotent_and_cannot_replay_relationship_or_send(self):
        eid=self.event('late')
        self.call('scan');work=self.call('claim')
        self.assertEqual([e['source_event'] for e in work['events']],[eid])
        before=self.b.dispatch(dict(op='companion_context'))['companion']['energy']
        a=template();a['emotion_deltas']['愉快']=.02
        with self.assertRaisesRegex(ValueError,'no_relationship'):
            self.call('repair',source_event=eid,lease=work['lease'],assessment=dict(a,relationship={'trust_delta':1}))
        result=self.call('repair',source_event=eid,lease=work['lease'],assessment=a)
        self.assertEqual(result['status'],'repaired')
        effect=result['emotion']['effect']['full48']
        self.assertGreater(effect['applied']['愉快'],0)
        self.assertLess(effect['applied']['愉快'],effect['bounded']['愉快']*effect['gain'])
        self.assertEqual(result['send_actions'],[]);self.assertEqual(result['sticker_actions'],[])
        self.assertEqual(before,self.b.dispatch(dict(op='companion_context'))['companion']['energy'])
        again=self.call('repair',source_event=eid,lease=work['lease'],assessment=a)
        self.assertEqual(again['status'],'already_valid')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal WHERE event=?',(eid,)).fetchone()[0],1)

    def test_successful_life_and_self_outputs_never_enter_repair(self):
        life=c._life_event(self.b,'虚拟练习','completed','A specific virtual fixture result',occurred=self.now-600)
        eid=self.b.db.execute('SELECT source_event FROM ct_life WHERE id=?',(life,)).fetchone()[0]
        self.b.dispatch(dict(op='companion_life_assess',id=life,assessment=template()))
        own=self.event('outgoing',actor='assistant',source='main:proactive')
        feedback.note(self.b,own,dict(status='invalid',detail='fixture old envelope'))
        self.call('scan')
        self.assertEqual(self.call('claim')['events'],[])
        fixed=self.call('receipt',round_id='outgoing',output_event=own,source_events=[eid])
        self.assertEqual(fixed['mood_writes'],0)
        self.assertTrue(fixed['historical_failure_preserved'])
        self.assertEqual(self.call('status')['receipt_reconciliations'],1)

    def test_native_scan_preserves_original_time_grace_and_bounded_claim(self):
        incoming=[dict(source='main:sticker',event_id='native-'+str(i),actor='user',
                       text='Isolated native original '+str(i),occurred_at=self.now-300-i) for i in range(4)]
        scan=self.call('scan',native_events=incoming,coverage={'sample_size':4})
        self.assertEqual(scan['queued'],4)
        self.assertEqual(len(self.call('claim')['events']),2)
        self.assertEqual(self.call('scan',native_events=incoming)['queued'],0)
        young=self.event('young',age=20)
        self.call('scan')
        self.assertFalse(self.b.db.execute('SELECT 1 FROM ct_feedback WHERE event=?',(young,)).fetchone())
        self.clock.return_value=self.now+200
        self.call('scan')
        self.assertTrue(self.b.db.execute('SELECT 1 FROM ct_feedback WHERE event=?',(young,)).fetchone())
        with self.assertRaises(ValueError):
            self.call('scan',native_events=[dict(incoming[0],actor='assistant')])

    def test_heartbeat_replaces_delayed_refresh_without_notifications_or_duplicate_publication(self):
        target=Path(self.temp.name)/'library'/'panel.html'
        old=panel_refresh.record(self.root,'old-life-cycle','fixture-life-task')
        first=panel_refresh.heartbeat(self.root,target,'emotion-run-1','fixture-emotion-task')
        self.assertTrue(first['ok']);self.assertEqual(first['notifications'],0)
        original=target.read_bytes()
        again=panel_refresh.heartbeat(self.root,target,'emotion-run-1','fixture-emotion-task')
        self.assertTrue(again['replayed']);self.assertEqual(original,target.read_bytes())
        state=json.loads(panel_refresh.state_path(self.root).read_text(encoding='utf-8'))
        self.assertEqual(state['mode'],'emotion_heartbeat');self.assertEqual(state['cadence_seconds'],900)
        self.assertEqual(state['offset_after_event_seconds'],0)
        self.assertEqual(panel_refresh.record(self.root,'new-old-life','fixture-life-task')['skipped'],'retired_delayed_panel_rule')
        self.assertEqual(panel_refresh.publish(self.root,target,old['cycle'])['skipped'],'stale_or_missing_cycle')
        with self.assertRaisesRegex(ValueError,'retired'):
            panel_refresh.bind(self.root,'old-life-cycle','old-runonce')
        html=target.read_text(encoding='utf-8')
        self.assertIn('每 15 分钟',html);self.assertIn('情绪反馈与修正',html)
        self.assertNotIn('事件更新后 5 分钟',html)


if __name__=='__main__':unittest.main()
