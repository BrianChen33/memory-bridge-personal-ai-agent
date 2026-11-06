"""Final isolated queue lifecycle checks. All browser/scheduler evidence is synthetic."""
import copy
import time
import unittest
import test_social_reading as fixture
from muse_ext.emotion_full48 import template


class ReadingQueue(fixture.SocialReading):
    def queued(self, sid=None, tid=801):
        sid=sid or self.allow()
        event=self.owner('合成请求：阅读这篇帖子')
        request=self.call('queue_enqueue',manual=True,owner_event=event,authorized=True,source_id=sid,
            target_url='https://tieba.baidu.com/p/'+str(tid))['request']
        work=self.call('queue_work',worker_id='fixture:worker')
        self.assertEqual(work['action'],'browse',work)
        rid=request['id']
        self.call('queue_bind_browser',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:browser')
        return sid,rid,work,event

    def stage(self,sid,rid,work,**changes):
        packet=self.packet(sid,801,**changes)
        at=time.time()
        result=self.call('queue_stage',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:browser',
            completed_at=at,observation=packet)
        return result,packet,at

    def finalize(self,did):
        return self.call('finalize_reading',document_id=did,summary='合成阅读反思',style_candidates=[],
            lexical_candidates=[],growth_candidates=[],interest_score=50,emotion_assessment=template())

    def test_queue_stage_release_ingest_and_finalize_are_idempotent(self):
        sid,rid,work,event=self.queued()
        replay=self.call('queue_enqueue',manual=True,owner_event=event,authorized=True,source_id=sid,target_url='https://tieba.baidu.com/p/801')
        self.assertEqual(replay['request']['id'],rid)
        result,packet,at=self.stage(sid,rid,work)
        self.assertTrue(result['browsing_released'])
        self.assertEqual(self.b.db.execute("SELECT count(*) FROM sr_lease WHERE status='claimed'").fetchone()[0],0)
        self.assertEqual(self.call('queue_work',worker_id='fixture:worker')['action'],'ingest')
        result=self.call('queue_ingest',request_id=rid)
        did=result['document_id']
        self.assertTrue(self.call('queue_ingest',request_id=rid)['replayed'])
        self.assertFalse(self.call('queue_finish',request_id=rid)['complete'])
        self.assertTrue(self.finalize(did)['complete'])
        self.assertEqual(self.call('queue_finish',request_id=rid)['request']['status'],'done')
        self.assertTrue(self.call('queue_finish',request_id=rid)['replayed'])
        replay=self.call('queue_stage',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:browser',completed_at=at,observation=packet)
        self.assertTrue(replay['replayed'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0],1)

    def test_queue_overdue_browser_reconciles_without_rebrowsing_and_late_result_is_kept(self):
        sid,rid,work,_=self.queued()
        self.b.db.execute('UPDATE sr_lease SET deadline=? WHERE id=?',(time.time()-1,work['lease_id']))
        self.b.db.commit()
        again=self.call('queue_work',worker_id='fixture:other')
        self.assertEqual(again['action'],'reconcile')
        self.assertEqual(self.call('plan',manual=True,source_id=sid,job_id='fixture:legacy')['action'],'busy')
        self.assertTrue(self.stage(sid,rid,work)[0]['late'])
        self.assertIn('document_id',self.call('queue_ingest',request_id=rid))
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_lease').fetchone()[0],1)

    def test_queue_wrong_task_changed_packet_and_legacy_consumption_are_rejected(self):
        sid,rid,work,_=self.queued()
        with self.assertRaisesRegex(ValueError,'binding'):
            self.call('queue_stage',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:wrong',completed_at=time.time(),observation=self.packet(sid,801))
        with self.assertRaisesRegex(ValueError,'bound_stage'):
            self.call('observe',lease_id=work['lease_id'],observation=self.packet(sid,801))
        result,packet,at=self.stage(sid,rid,work)
        packet=copy.deepcopy(packet);packet['floors'][0]['text']='Different synthetic reading'
        with self.assertRaisesRegex(ValueError,'conflict'):
            self.call('queue_stage',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:browser',completed_at=at,observation=packet)

    def test_queue_cancelled_or_revoked_observed_document_cannot_finalize(self):
        sid,rid,work,_=self.queued()
        self.stage(sid,rid,work)
        did=self.call('queue_ingest',request_id=rid)['document_id']
        event=self.owner('取消这个合成阅读请求')
        self.call('queue_cancel',request_id=rid,owner_event=event,authorized=True)
        with self.assertRaisesRegex(ValueError,'not_accepting_finalization'):self.finalize(did)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM sr_reflection').fetchone()[0],0)
        sid,rid,work,_=self.queued(sid=sid)
        self.stage(sid,rid,work)
        did=self.call('queue_ingest',request_id=rid)['document_id']
        event=self.owner('撤销这个合成来源许可')
        self.call('source_revoke',source_id=sid,owner_event=event,authorized=True)
        with self.assertRaisesRegex(ValueError,'not_allowed'):self.finalize(did)
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0],0)

    def test_queue_result_delayed_over_an_hour_keeps_real_original_time(self):
        sid,rid,work,_=self.queued()
        old=time.time()-4000
        self.b.db.execute('UPDATE sr_lease SET created=?,deadline=? WHERE id=?',(old-100,old+10,work['lease_id']));self.b.db.commit()
        self.call('queue_stage',request_id=rid,lease_id=work['lease_id'],browser_task_id='fixture:browser',completed_at=old,observation=self.packet(sid,801))
        result=self.call('queue_ingest',request_id=rid)
        event=self.b.db.execute('SELECT occurred_at FROM source_events WHERE id=?',(result['source_event'],)).fetchone()
        self.assertEqual(event['occurred_at'],old)

    def test_queue_cancel_needs_real_browser_stop_and_revocation_blocks_ingest(self):
        sid,rid,work,_=self.queued()
        event=self.owner('取消合成阅读')
        self.assertEqual(self.call('queue_cancel',request_id=rid,owner_event=event,authorized=True)['action'],'stop_bound_browser')
        self.assertEqual(self.call('queue_cancel',request_id=rid,owner_event=event,authorized=True)['action'],'stop_bound_browser')
        self.assertEqual(self.call('queue_work',worker_id='fixture:other')['action'],'reconcile')
        self.assertEqual(self.b.db.execute("SELECT count(*) FROM sr_lease WHERE status='claimed'").fetchone()[0],1)
        self.assertEqual(self.call('queue_release',request_id=rid,reason='cancelled')['action'],'confirm_browser_stop')
        self.call('queue_release',request_id=rid,reason='cancelled',browser_task_id='fixture:browser',browser_stopped=True,stop_receipt='fixture:stop')
        self.assertEqual(self.call('queue_status')['requests'][0]['status'],'cancelled')
        sid,rid,work,_=self.queued(sid=sid)
        self.stage(sid,rid,work)
        event=self.owner('停止允许此来源')
        self.call('source_revoke',source_id=sid,owner_event=event,authorized=True)
        with self.assertRaises(ValueError):self.call('queue_ingest',request_id=rid)

    def test_queue_actual_future_handoff_is_not_an_unbound_plan(self):
        _,rid,_,_=self.queued()
        plan=self.call('queue_handoff',request_id=rid)['schedule']
        self.assertGreater(plan['scheduled_for'],time.time())
        self.assertFalse(plan['bound'])
        with self.assertRaisesRegex(ValueError,'readback'):
            self.call('queue_handoff',request_id=rid,native_task_id='fixture:task',scheduled_for=time.time()-1)
        saved=self.call('queue_handoff',request_id=rid,native_task_id='fixture:task',scheduled_for=plan['scheduled_for'])
        self.assertTrue(saved['schedule']['bound'])
        self.assertTrue(self.call('queue_handoff',request_id=rid)['replayed'])
        with self.assertRaisesRegex(ValueError,'conflict'):
            self.call('queue_handoff',request_id=rid,native_task_id='fixture:other',scheduled_for=plan['scheduled_for'])

    def test_queue_owner_can_resume_paused_auto_work_without_enabling_auto_browse(self):
        sid,rid,work,_=self.queued()
        self.call('queue_release',request_id=rid,reason='fixture pause',browser_task_id='fixture:browser',browser_stopped=True,stop_receipt='fixture:stop')
        self.b.db.execute('UPDATE sr_read_queue SET manual=0 WHERE id=?',(rid,));self.b.db.commit()
        event=self.owner('关闭自动阅读，但手动恢复这个请求')
        self.call('configure',owner_event=event,authorized=True,patch=dict(auto_browse=False))
        result=self.call('queue_resume',request_id=rid,owner_event=event,authorized=True)
        self.assertEqual(result['request']['status'],'queued')
        self.assertEqual(result['request']['manual'],1)

    def test_queue_continuation_uses_observed_cursor_without_replaying_finished_emotion(self):
        sid,rid,work,_=self.queued()
        self.stage(sid,rid,work,coverage=dict(pages_seen=[1],total_pages=5,ended=False,all_visible_floors=True,next_url='https://tieba.baidu.com/p/801?pn=2'))
        result=self.call('queue_ingest',request_id=rid)
        self.finalize(result['document_id'])
        saved=self.call('queue_finish',request_id=rid,continue_reading=True)
        self.assertEqual(saved['request']['cursor']['coverage']['next_url'],'https://tieba.baidu.com/p/801?pn=2')
        self.b.db.execute('UPDATE sr_read_queue SET next_at=0 WHERE id=?',(rid,));self.b.db.commit()
        next_batch=self.call('queue_work',worker_id='fixture:next')
        self.assertEqual(next_batch['resume']['coverage']['next_url'],'https://tieba.baidu.com/p/801?pn=2')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0],1)


def load_tests(loader,tests,pattern):
    return unittest.TestSuite(ReadingQueue(name) for name in ReadingQueue.__dict__ if name.startswith('test_queue_'))
