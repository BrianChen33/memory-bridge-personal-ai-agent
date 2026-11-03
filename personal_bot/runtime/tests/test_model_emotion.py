"""Synthetic contract tests for model-judged emotion; never contact a model."""
import copy
import json
import tempfile
import unittest
from unittest.mock import patch

from brain import Brain
from support import seed_legacy_policy


def assessment(changed=True, label='����', p=.03, a=.02, d=0, intensity=.04):
    return dict(version=1, changed=changed, label=label,
                delta=dict(p=p, a=a, d=d), intensity_delta=intensity)


def unchanged():
    return assessment(False, None, 0, 0, 0, 0)


class ModelEmotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.b = Brain(self.temp.name)
        seed_legacy_policy(self.temp.name)
        self.b.dispatch(dict(op='configure', enabled=True,
                             features={'events': True, 'emotion_events': True}))

    def tearDown(self):
        self.b.close()
        self.temp.cleanup()

    def send(self, envelope=None, **kw):
        q = dict(op='prepare', scope='owner-private', source='fixture:incoming',
                 event_id='e1', actor='user', text='����һС��λ��������')
        if envelope is not None:
            q['emotion_assessment'] = envelope
        q.update(kw)
        return self.b.dispatch(q)

    def snapshot(self):
        return {table: [tuple(row) for row in self.b.db.execute('SELECT * FROM '+table)]
                for table in ('mood', 'emotion', 'emotion_events', 'assessment_log')}

    def test_keywords_without_assessment_never_change_mood_and_can_submit_later(self):
        r = self.send(text='лл����˴�æ')
        self.assertEqual(r['emotion']['status'], 'missing')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM mood').fetchone()[0], 0)
        r = self.send(assessment(), text='лл����˴�æ')
        self.assertEqual(r['emotion']['status'], 'updated')
        self.assertAlmostEqual(r['mood']['p'], .03, places=5)

    def test_contextual_label_and_exact_model_amplitude_without_fixed_increment(self):
        r = self.send(assessment())
        self.assertEqual(r['emotion']['status'], 'updated')
        row = self.b.db.execute('SELECT * FROM emotion').fetchone()
        self.assertEqual(row['label'], '����')
        self.assertEqual(row['intensity'], .04)
        self.assertTrue(row['reason'].startswith('inference:model_assessment:'))
        self.assertNotIn('����һ', row['reason'])

    def test_capture_has_no_emotion_side_effect(self):
        r = self.send(op='capture', text='лл��')
        self.assertEqual(r['emotion']['status'], 'pending_assessment')
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM mood').fetchone()[0], 0)
        self.assertEqual(self.send(assessment(), text='лл��')['emotion']['status'], 'updated')

    def test_unchanged_is_logged_without_refreshing_mood_labels_or_at(self):
        self.send(assessment())
        before = self.snapshot()
        self.assertEqual(self.send(unchanged(), event_id='e2')['emotion']['status'], 'unchanged')
        after = self.snapshot()
        for table in ('mood', 'emotion', 'emotion_events'):
            self.assertEqual(after[table], before[table])
        self.assertEqual(len(after['assessment_log']), 2)
        self.assertEqual(self.send(unchanged(), event_id='e2')['emotion']['status'], 'replayed')
        self.assertEqual(self.snapshot(), after)

    def test_replay_and_conflict_keep_first_result(self):
        self.send(assessment())
        before = self.snapshot()
        self.assertEqual(self.send(assessment())['emotion']['status'], 'replayed')
        self.assertEqual(self.send(assessment(p=.05))['emotion']['status'], 'conflict')
        self.assertEqual(self.snapshot(), before)

    def test_strict_validation_keeps_later_valid_opportunity(self):
        cases = []
        for field, value in [('version', True), ('version', 1.0), ('changed', 1),
                             ('label', '����'), ('intensity_delta', True),
                             ('intensity_delta', float('nan')), ('intensity_delta', .121)]:
            item = assessment(); item[field] = value; cases.append(item)
        for value in (True, float('inf'), -.121, '0.03'):
            item = assessment(); item['delta']['p'] = value; cases.append(item)
        item = assessment(); del item['delta']['d']; cases.append(item)
        item = assessment(); del item['intensity_delta']; cases.append(item)
        cases.extend([assessment(p=0, a=0, intensity=0), assessment(False), 'bad-envelope'])
        for i, bad in enumerate(cases):
            with self.subTest(i=i):
                eid = 'bad-'+str(i)
                r = self.send(copy.deepcopy(bad), event_id=eid)
                self.assertEqual(r['emotion']['status'], 'invalid')
                self.assertEqual(self.send(assessment(), event_id=eid)['emotion']['status'], 'updated')

    def test_signed_intensity_and_zero_intensity_do_not_add_point_one(self):
        with patch('time.time', return_value=1000):
            self.send(assessment(intensity=.10))
            self.send(assessment(intensity=-.04), event_id='e2')
            r = self.send(assessment(intensity=0), event_id='e3')
        self.assertAlmostEqual(r['mood']['labels'][0]['intensity'], .06)

    def test_read_decay_does_not_write_and_update_uses_decayed_state(self):
        with patch('time.time', return_value=1000):
            self.send(assessment(p=.12, a=0, intensity=.12))
        before = self.snapshot()
        with patch('time.time', return_value=22600):
            r = self.b.dispatch(dict(op='mood', scope='owner-private'))
        self.assertAlmostEqual(r['p'], .06)
        self.assertEqual(self.snapshot(), before)
        with patch('time.time', return_value=3700):
            self.send(assessment(p=0, a=0, intensity=.02), event_id='e2')
        self.assertAlmostEqual(self.b.db.execute('SELECT intensity FROM emotion').fetchone()[0], .08)

    def test_output_article_bot_and_control_do_not_create_user_emotion(self):
        for actor in ('assistant', 'article', 'bot'):
            self.assertEqual(self.send(assessment(), actor=actor, event_id=actor)['emotion']['status'], 'ignored')
        self.send(assessment(), event_id='debug', text='��Codex���ԣ�лл')
        self.send(assessment(), event_id='synthetic', synthetic=True)
        self.assertEqual(self.b.db.execute('SELECT COUNT(*) FROM mood').fetchone()[0], 0)
        self.assertEqual(self.send(unchanged(), actor='assistant', event_id='out')['emotion']['status'], 'unchanged')

    def test_scope_does_not_change_owner_state(self):
        self.send(assessment(), scope='qq:group:synthetic-room')
        self.assertEqual(self.b.db.execute("SELECT COUNT(*) FROM mood WHERE scope='owner-private'").fetchone()[0], 0)
        self.assertEqual(self.b.dispatch(dict(op='mood', scope='owner-private'))['p'], 0)

    def test_disabled_and_reenabled_require_real_assessment(self):
        for disable in ({'enabled': False}, {'modules': {'mood': False}},
                        {'features': {'events': False}}, {'features': {'emotion_events': False}}):
            with self.subTest(disable=disable):
                self.b.dispatch(dict(op='configure', **disable))
                self.assertEqual(self.send(assessment())['emotion']['status'], 'disabled_by_config')
                self.b.dispatch(dict(op='configure', enabled=True, modules={'mood': True},
                                     features={'events': True, 'emotion_events': True}))
                self.assertEqual(self.send()['emotion']['status'], 'missing')
        self.assertEqual(self.send(assessment())['emotion']['status'], 'updated')

    def test_config_damage_is_not_explicit_disable(self):
        self.b.config_path.write_text('{broken', encoding='utf-8')
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            self.send(assessment())

    def test_legacy_recorded_event_is_not_reapplied_after_upgrade(self):
        event = self.send(op='capture')['event']['id']
        with self.b.db:
            self.b.db.execute('INSERT INTO mood VALUES(?,?,?,?,?)', ('owner-private', .2, 0, 0, 1000))
            self.b.db.execute('INSERT INTO emotion_events VALUES(?,?,?,?,?,?)',
                              (event, 'owner-private', '��ϲ', '{}', 'inference', 1000))
        before = self.snapshot()
        self.assertEqual(self.send(assessment())['emotion']['status'], 'legacy_recorded')
        self.assertEqual(self.snapshot(), before)

    def test_model_updates_reach_caps_and_create_one_threshold_candidate(self):
        with patch('time.time', return_value=1000):
            for i in range(15):
                self.send(assessment(p=.12, a=.12, d=.12, intensity=.12), event_id=str(i))
        row = self.b.db.execute('SELECT * FROM mood').fetchone()
        self.assertEqual((row['p'], row['a'], row['d']), (1, 1, 1))
        self.assertEqual(self.b.db.execute('SELECT intensity FROM emotion').fetchone()[0], .6)
        rows = self.b.db.execute("SELECT * FROM candidates WHERE topic LIKE 'emotion:%'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertTrue(self.b.valid_sources(rows[0]))
