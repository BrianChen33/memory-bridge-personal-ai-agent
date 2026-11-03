import tempfile,unittest
from brain import Brain
from support import seed_legacy_policy

class SharingTests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.b=Brain(self.t.name);seed_legacy_policy(self.t.name)
        self.b.dispatch(dict(op='configure',enabled=True,features={'events':True,'emotion_events':True,'consolidation':True}))
    def tearDown(self):self.b.close();self.t.cleanup()
    def test_real_emotion_threshold_creates_source_backed_candidate_once(self):
        for i in range(4):self.b.dispatch(dict(op='prepare',scope='owner-private',text='谢谢你，帮了大忙',source='fixture:user',event_id=str(i),emotion_assessment=dict(version=1,changed=True,label='欣喜',delta=dict(p=.045,a=.02,d=.015),intensity_delta=.1)))
        rows=self.b.db.execute("SELECT * FROM candidates WHERE topic LIKE 'emotion:%'").fetchall()
        self.assertEqual(len(rows),1);self.assertTrue(self.b.valid_sources(rows[0]))
        self.assertEqual(rows[0]['status'],'pending')
    def test_channel_claim_leaves_other_pending(self):
        m=self.b.dispatch(dict(op='remember',scope='owner-private',text='真实出处',source='fixture:user',event_id='source'))['id']
        for topic in ['emotion:one','reading:two','life:three']:
            self.b.dispatch(dict(op='life',scope='owner-private',text='有出处的观察',sources=[m],topic=topic))
        a=self.b.dispatch(dict(op='digest_claim',scope='owner-private',channels=['emotion']))
        self.assertEqual(len(a['candidates']),1);self.assertEqual(a['remaining'],0)
        self.assertEqual(self.b.db.execute("SELECT COUNT(*) FROM candidates WHERE status='pending'").fetchone()[0],2)
    def test_derivation_is_labelled_linked_and_not_factual_recall(self):
        m=self.b.dispatch(dict(op='remember',scope='owner-private',text='先验证备份再修改生产',source='fixture:user',event_id='source'))['id']
        q=dict(op='derive',scope='owner-private',sources=[m],text='升级之前应先验证恢复通路。',kind='lesson')
        a=self.b.dispatch(q);self.assertEqual(self.b.dispatch(q)['id'],a['id'])
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='升级备份'))
        self.assertTrue(r['insights']);self.assertEqual(r['insights'][0]['evidence'],'inference')
        self.assertFalse(any(x['id']==a['id'] for x in r['memories']))
        self.b.dispatch(dict(op='forget',scope='owner-private',id=m))
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='升级备份'))
        self.assertEqual(r['insights'],[])

    def test_inference_note_obeys_explicit_and_calendar_time_ranges(self):
        from unittest.mock import patch
        from datetime import datetime,timedelta,timezone
        m=self.b.dispatch(dict(op='remember',scope='owner-private',text='验证Backup恢复后再升级',source='fixture:user',event_id='source',occurred_at=100))['id']
        with patch('time.time',return_value=100):
            self.b.dispatch(dict(op='derive',scope='owner-private',sources=[m],text='Backup升级前应验证恢复。',kind='lesson'))
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='Backup',start=0,end=2))
        self.assertEqual(r['insights'],[])
        self.b.dispatch(dict(op='configure',features={'time_query':True}))
        with patch('muse_ext.temporal._now',return_value=datetime(2026,11,3,9,tzinfo=timezone(timedelta(hours=8)))):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='昨天的Backup'))
        self.assertEqual(r['insights'],[])
