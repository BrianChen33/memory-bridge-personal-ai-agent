import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
from brain import Brain
from support import seed_legacy_policy
BJ=timezone(timedelta(hours=8))
T=datetime(2026,11,3,12,tzinfo=BJ).timestamp()

class ReminderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=Brain(self.tmp.name)
        seed_legacy_policy(self.tmp.name)
        self.b.dispatch(dict(op='configure',enabled=True,features={'reminders':True}))
        self.clock=patch('time.time',return_value=T);self.clock.start()
    def tearDown(self):
        self.clock.stop();self.b.close();self.tmp.cleanup()
    def call(self,action,**kw):
        return self.b.dispatch(dict(op='reminder',action=action,scope='owner-private',**kw))
    def create(self,**kw):
        q=dict(text='十分钟后提醒我喝水',body='这是提醒闭环合成测试：喝水',source='main:test',event_id='request1')
        q.update(kw);return self.call('create',**q)
    def ready(self):
        r=self.create()['reminder'];self.call('attach',id=r['id'],version=1,native_job_id=r['native_job_id']);return r
    def test_create_idempotent_and_reconcile_attach(self):
        a=self.create()['reminder'];b=self.create()['reminder'];self.assertEqual(a['id'],b['id'])
        self.assertEqual(a['due_at'],T+600)
        self.assertEqual(a['status'],'unscheduled')
        self.assertEqual(self.call('pending')['reminders'][0]['native_job_id'],a['native_job_id'])
        self.assertTrue(self.call('attach',id=a['id'],version=1,native_job_id=a['native_job_id'])['ok'])
        self.assertTrue(self.call('attach',id=a['id'],version=1,native_job_id=a['native_job_id'])['ok'])
        with self.assertRaisesRegex(ValueError,'native_job_mismatch'):
            self.call('attach',id=a['id'],version=1,native_job_id='wrong')
    def test_ambiguous_due_has_no_ledger(self):
        r=self.create(text='明天三点提醒我');self.assertTrue(r['needs_clarification'])
        self.assertEqual(self.call('pending')['reminders'],[])
    def test_early_claim_rejected_even_with_fake_now(self):
        r=self.ready()
        a=self.call('claim',id=r['id'],version=1,now=T+1000)
        self.assertFalse(a['ok']);self.assertEqual(a['reason'],'not_due')
        self.assertNotIn('body',a)
    def test_due_claim_authorize_handoff_once_unknown_not_replayed(self):
        r=self.ready()
        with patch('time.time',return_value=T+601):
            a=self.call('claim',id=r['id'],version=1)
            self.assertTrue(a['ok']);self.assertNotIn('body',a)
            self.assertFalse(self.call('claim',id=r['id'],version=1)['ok'])
            v=dict(id=r['id'],version=1,lease=a['lease'],epoch=a['epoch'])
            self.assertTrue(self.call('authorize',**v)['ok'])
            h=self.call('handoff',**v)
            self.assertEqual(h['status'],'unknown');self.assertEqual(h['body'],r['body'])
            self.assertFalse(self.call('claim',id=r['id'],version=1)['ok'])
            self.assertFalse(self.call('handoff',**v)['ok'])
    def test_cancel_between_authorize_and_handoff(self):
        r=self.ready()
        with patch('time.time',return_value=T+601):
            a=self.call('claim',id=r['id'],version=1)
            self.call('cancel',id=r['id'])
            self.assertFalse(self.call('handoff',id=r['id'],version=1,lease=a['lease'],epoch=a['epoch'])['ok'])
    def test_reschedule_invalidates_version_and_lists_retired_job(self):
        r=self.ready()
        s=self.call('reschedule',id=r['id'],text='二十分钟后提醒我')['reminder']
        self.assertEqual(s['version'],2);self.assertNotEqual(s['native_job_id'],r['native_job_id'])
        self.assertIn(r['native_job_id'],self.call('pending')['disable_native_jobs'])
        with self.assertRaisesRegex(ValueError,'stale_version'):
            self.call('attach',id=r['id'],version=1,native_job_id=r['native_job_id'])
    def test_life_pause_does_not_cancel_requested_reminder(self):
        r=self.ready();self.b.dispatch(dict(op='configure',modules={'life':False}))
        with patch('time.time',return_value=T+601):self.assertTrue(self.call('claim',id=r['id'],version=1)['ok'])
    def test_feature_off_fences_inflight(self):
        r=self.ready()
        with patch('time.time',return_value=T+601):
            a=self.call('claim',id=r['id'],version=1)
            self.b.dispatch(dict(op='configure',features={'reminders':False}))
            self.assertFalse(self.call('handoff',id=r['id'],version=1,lease=a['lease'],epoch=a['epoch'])['ok'])
    def test_quiet_hours_defer_without_explicit_exception(self):
        night=datetime(2026,11,4,2,tzinfo=BJ).timestamp()
        with patch('time.time',return_value=night):
            r=self.create()['reminder']
            self.assertEqual(r['wake_at'],datetime(2026,11,4,7,tzinfo=BJ).timestamp())
            self.call('attach',id=r['id'],version=1,native_job_id=r['native_job_id'])
            with patch('time.time',return_value=night+601):
                a=self.call('claim',id=r['id'],version=1)
                self.assertEqual(a['reason'],'quiet_hours');self.assertFalse(a['ok'])
    def test_explicit_night_override(self):
        night=datetime(2026,11,4,2,tzinfo=BJ).timestamp()
        with patch('time.time',return_value=night):
            r=self.create(quiet_override=True,quiet_permission='explicit_user_request')['reminder']
            self.call('attach',id=r['id'],version=1,native_job_id=r['native_job_id'])
            with patch('time.time',return_value=night+601):self.assertTrue(self.call('claim',id=r['id'],version=1)['ok'])
    def test_no_fake_quiet_exception_or_nonowner(self):
        with self.assertRaisesRegex(ValueError,'explicit_quiet_permission_required'):self.create(quiet_override=True)
        with self.assertRaisesRegex(ValueError,'reminder_owner_only'):
            self.b.dispatch(dict(op='reminder',action='pending',scope='qq:group:A'))
    def test_same_request_changed_payload_conflicts(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'reminder_request_conflict'):self.create(body='另一件事')

    def test_due_guard_waits_and_observes_cancellation(self):
        from muse_ext.reminders import wait_and_claim
        r=self.ready()
        with patch('time.time',return_value=T+599),patch('muse_ext.reminders.time.sleep') as sleep:
            sleep.side_effect=lambda _: self.call('cancel',id=r['id'])
            a=wait_and_claim(self.b,r['id'],1,max_wait=10)
        self.assertFalse(a['ok']);self.assertEqual(a['reason'],'stopped');sleep.assert_called_once()
    def test_independent_connection_cannot_double_claim(self):
        r=self.ready()
        other=Brain(self.tmp.name)
        try:
            with patch('time.time',return_value=T+601):
                a=self.call('claim',id=r['id'],version=1)
                b=other.dispatch(dict(op='reminder',action='claim',scope='owner-private',id=r['id'],version=1))
            self.assertTrue(a['ok']);self.assertFalse(b['ok'])
        finally:other.close()
    def test_handoff_rechecks_quiet_clock_and_epoch(self):
        r=self.ready()
        with patch('time.time',return_value=T+601):a=self.call('claim',id=r['id'],version=1)
        v=dict(id=r['id'],version=1,lease=a['lease'],epoch=a['epoch'])
        night=datetime(2026,11,4,2,tzinfo=BJ).timestamp()
        with patch('time.time',return_value=night):
            self.assertFalse(self.call('handoff',**v)['ok'])
        self.assertEqual(self.call('status',id=r['id'])['reminder']['status'],'claimed')
    def test_invalid_policy_and_expired_lease_fail_closed(self):
        r=self.ready()
        with patch('time.time',return_value=T+601):a=self.call('claim',id=r['id'],version=1)
        with patch('time.time',return_value=T+1000):
            self.assertFalse(self.call('handoff',id=r['id'],version=1,lease=a['lease'],epoch=a['epoch'])['ok'])
        (self.b.root/'proactive-policy.json').write_text('{}')
        with patch('time.time',return_value=T+1001),self.assertRaises(ValueError):self.call('claim',id=r['id'],version=1)

    def test_one_command_wait_authorize_handoff_returns_prepared_body_once(self):
        from muse_ext.reminders import wait_and_handoff
        r=self.ready()
        with patch('time.time',return_value=T+601):
            a=wait_and_handoff(self.b,r['id'],1)
            b=wait_and_handoff(self.b,r['id'],1)
        self.assertTrue(a['ok']);self.assertEqual(a['body'],r['body']);self.assertEqual(a['status'],'unknown')
        self.assertFalse(b['ok']);self.assertNotIn('body',b)
