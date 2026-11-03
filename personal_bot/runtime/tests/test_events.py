import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from brain import Brain
from support import seed_legacy_policy

BJ = timezone(timedelta(hours=8))

class EventTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = Brain(self.tmp.name)
        seed_legacy_policy(self.tmp.name)
        self.b.dispatch(dict(op='configure', enabled=True, features={'events':True,'time_query':True,'emotion_events':True}))
    def tearDown(self):
        self.b.close(); self.tmp.cleanup()
    def send(self, **kw):
        q=dict(op='prepare', scope='owner-private', text='лл�㣬���˴�æ', source='main:message', event_id='e1', actor='user')
        q['emotion_assessment'] = dict(version=1, changed=True, label='��ϲ', delta=dict(p=.045,a=.02,d=.015), intensity_delta=.1)
        q.update(kw)
        return self.b.dispatch(q)
    def test_real_prepare_writes_once_and_updates_mood(self):
        a=self.send()
        self.assertEqual(a['event']['status'], 'captured')
        self.assertGreater(a['mood']['p'], 0)
        before=dict(self.b.db.execute('SELECT * FROM mood').fetchone())
        self.send()
        self.assertEqual(dict(self.b.db.execute('SELECT * FROM mood').fetchone()),before)
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],1)
        row=self.b.db.execute('SELECT * FROM emotion_events').fetchone()
        self.assertEqual(row['event_id'], a['event']['id'])
        self.assertEqual(row['evidence'],'inference')
    def test_debug_synthetic_and_assistant_are_not_owner_emotion(self):
        self.send(text='[Codex����] лл��')
        self.send(text='��������1103��лл��', event_id='e2')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],0)
        self.send(text='лл��',actor='assistant',event_id='e3')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM emotion_events').fetchone()[0],0)
    def test_replayed_id_cannot_change_original(self):
        self.send()
        with self.assertRaisesRegex(ValueError,'event_conflict'):
            self.send(text='��һ������')
    def test_originals_and_scope_and_time_actor(self):
        yesterday=datetime(2026,11,2,9,tzinfo=BJ).timestamp()
        self.send(text='�ҵ�ԭ������������',occurred_at=yesterday)
        self.send(text='��һ��Ⱥ������',scope='qq:group:A',event_id='g',occurred_at=yesterday)
        self.send(text='���ֵ�ԭ��',actor='assistant',event_id='a',occurred_at=yesterday)
        with patch('muse_ext.temporal._now',return_value=datetime(2026,11,3,9,tzinfo=BJ)):
            r=self.b.dispatch(dict(op='recall',scope='owner-private',text='����������˵��ʲô'))
        self.assertEqual([x['text'] for x in r['events']],['�ҵ�ԭ������������'])
        self.assertEqual(r['temporal']['query'],'')
    def test_explicit_numeric_range_precedes_calendar(self):
        self.send(text='����',occurred_at=100)
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='����',start=99,end=101))
        self.assertEqual(r['events'][0]['text'],'����')
    def test_forget_also_hides_original(self):
        self.send(text='����',occurred_at=100)
        m=self.b.dispatch(dict(op='remember',scope='owner-private',text='����',source='main:message',event_id='e1'))
        self.b.dispatch(dict(op='forget',scope='owner-private',id=m['id']))
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='',start=99,end=101))
        self.assertEqual(r['events'],[])
        self.send(text='����',occurred_at=100)
        self.assertEqual(self.b.db.execute("SELECT status FROM source_events").fetchone()[0],'forgotten')
    def test_disabled_features_and_missing_metadata_do_not_capture(self):
        self.send(source='',event_id='')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],0)
        self.b.dispatch(dict(op='configure',features={'events':False}))
        self.send()
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],0)
    def test_model_supplied_concern_and_focus_are_persisted(self):
        self.send(text='�����ѹ���ô���ѹ�', emotion_assessment=dict(version=1,changed=True,label='����',delta=dict(p=-.025,a=.025,d=.015),intensity_delta=.1))
        r=self.b.db.execute('SELECT * FROM emotion_events').fetchone()
        self.assertEqual(r['label'],'����')
        self.send(text='��˵���ˣ������',event_id='correction', emotion_assessment=dict(version=1,changed=True,label='רע',delta=dict(p=0,a=.025,d=.015),intensity_delta=.1))
        self.assertEqual(self.b.db.execute('SELECT label FROM emotion_events ORDER BY rowid DESC').fetchone()[0],'רע')
    def test_caps_and_no_clock_based_repeated_write(self):
        for i in range(30):self.send(event_id=str(i))
        mood=self.b.dispatch(dict(op='mood',scope='owner-private'))
        self.assertLessEqual(mood['p'],1)
        self.assertLessEqual(max(x['intensity'] for x in mood['labels']),.6)
    def test_feature_configuration_rejects_typos_and_fences_epoch(self):
        old=self.b.config()['epoch']
        self.b.dispatch(dict(op='configure',features={'emotion_events':False}))
        self.assertGreater(self.b.config()['epoch'],old)
        with self.assertRaisesRegex(ValueError,'invalid_feature'):
            self.b.dispatch(dict(op='configure',features={'typo':True}))

    def test_numeric_range_keeps_topic_filter(self):
        self.send(text='����',occurred_at=100)
        self.send(text='����',occurred_at=100,event_id='other')
        r=self.b.dispatch(dict(op='recall',scope='owner-private',text='����',start=99,end=101))
        self.assertEqual([x['text'] for x in r['events']],['����'])
