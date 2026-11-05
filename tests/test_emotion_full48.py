"""Full48 real-runtime checks, isolated from all host queues and state."""
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c
from muse_ext.emotion_catalog import LABELS


class Full48(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='full48-isolated-')
        self.root = Path(self.temp.name) / 'state'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        self.b = Brain(self.root)
        self.b.dispatch(dict(op='companion_expression_config', patch={'emotion_gain': 1.5}))

    def tearDown(self):
        self.b.close()
        self.temp.cleanup()

    def assessment(self, **changes):
        value = dict(version=2, format='full48-v1', impact='ordinary',
                     delta=dict(p=0, a=0, d=0), emotion_deltas=dict.fromkeys(LABELS, 0),
                     appraisal=dict(kind='other', target='self', agency='none', certainty=.7,
                                    feeling='An isolated fixture.', action='neutral'))
        value['emotion_deltas'].update(changes)
        return value

    def event(self, eid='one', assessment=None):
        q = dict(op='prepare', scope='owner-private', actor='user', person_id='owner',
                 source='fixture:full48', event_id=eid, text='Isolated conversation input')
        if assessment is not None:
            q['emotion_assessment'] = assessment
        return self.b.dispatch(q)

    def test_complete_vector_preserved_and_six_groups_use_absolute_actual_delta(self):
        with self.b.db:
            self.b.db.execute('INSERT INTO emotion VALUES(?,?,?,?,?)',
                              ('owner-private', '委屈', .2, 'fixture', time.time()))
        a = self.assessment(愉快=.02, 欣喜=.01, 委屈=-.01)
        result = self.event(assessment=a)
        effect = result['emotion_effect']
        self.assertEqual(result['emotion']['status'], 'updated')
        self.assertEqual(len(effect['raw_labels']), 48)
        self.assertEqual(len(effect['applied_labels']), 48)
        self.assertEqual(len(effect['full48']['after']), 48)
        self.assertEqual(len(effect['group_changes']), 6)
        first = effect['group_changes'][0]
        self.assertEqual(first['label'], '愉快')
        self.assertEqual(first['delta'], .03)
        self.assertEqual(effect['group_changes'][1]['label'], None)
        self.assertEqual(effect['group_changes'][3]['label'], '委屈')
        self.assertAlmostEqual(effect['group_changes'][3]['delta'], -.015)
        self.assertEqual(result['reaction']['group_changes'], effect['group_changes'])

    def test_missing_and_wrong_fields_fail_with_specific_errors_and_same_source_can_be_corrected(self):
        a = self.assessment()
        del a['emotion_deltas']['纠结']
        bad = self.event(assessment=a)
        self.assertEqual(bad['emotion']['status'], 'invalid')
        self.assertIn('emotion_deltas', bad['emotion']['detail'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0], 0)
        a = self.assessment(好奇=.01)
        a['appraisal'] = {'event': 'feedback', 'object': 'self'}
        bad = self.event(assessment=a)
        self.assertIn('appraisal', bad['emotion']['detail'])
        for appraisal in ('missing', None, {}, {'kind': 'other'}):
            with self.subTest(appraisal=appraisal):
                a = self.assessment(好奇=.01)
                if appraisal == 'missing':
                    del a['appraisal']
                else:
                    a['appraisal'] = appraisal
                bad = self.event(assessment=a)
                self.assertEqual(bad['emotion']['status'], 'invalid')
                self.assertIn('appraisal:', bad['emotion']['detail'])
                self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0], 0)
        a = self.assessment(好奇=.01)
        a['additional_labels'] = []
        self.assertIn('additional_labels', self.event(assessment=a)['emotion']['detail'])
        valid = self.event(assessment=self.assessment(好奇=.01))
        again = self.event(assessment=self.assessment(好奇=.01))
        self.assertEqual(valid['emotion']['status'], 'updated')
        self.assertEqual(again['emotion']['status'], 'replayed')
        self.assertEqual(valid['emotion_effect'], again['emotion_effect'])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0], 1)

    def test_component_and_total_budgets_bound_ordinary_and_salient_events(self):
        ordinary = self.assessment(**dict.fromkeys(LABELS, .4))
        effect = self.event('ordinary', ordinary)['emotion_effect']
        self.assertLessEqual(sum(abs(x['delta']) for x in effect['applied_labels']), .060001)
        self.assertLessEqual(max(abs(x['delta']) for x in effect['applied_labels']), .030001)
        self.assertLess(effect['full48']['budget']['label_scale'], 1)
        salient = self.assessment(自豪=.4)
        salient['impact'] = 'salient'
        effect = self.event('salient', salient)['emotion_effect']
        self.assertAlmostEqual(next(x['delta'] for x in effect['applied_labels'] if x['label']=='自豪'), .2)

    def test_gain_is_applied_once_and_replay_keeps_original_effect(self):
        a = self.assessment(亲近=.01)
        effect = self.event(assessment=a)['emotion_effect']
        self.assertEqual(effect['gain'], 1.5)
        self.assertEqual(effect['group_changes'][1]['delta'], .015)
        self.b.dispatch(dict(op='companion_expression_config', patch={'emotion_gain': 3}))
        self.assertEqual(self.event(assessment=a)['emotion_effect'], effect)
        later = self.event('second', a)['emotion_effect']
        self.assertEqual(later['group_changes'][1]['delta'], .03)

    def test_decay_is_not_reported_as_a_new_event_and_all_zero_is_valid(self):
        now = time.time()
        with self.b.db:
            self.b.db.execute('INSERT INTO emotion VALUES(?,?,?,?,?)',
                              ('owner-private', '委屈', .2, 'fixture', now-3600))
            self.b.db.execute('INSERT OR REPLACE INTO ct_label VALUES(?,?,?)',
                              ('owner-private', '委屈', 1))
        with patch.object(c, 'stamp', return_value=now):
            result = self.event(assessment=self.assessment())
        self.assertEqual(result['emotion']['status'], 'unchanged')
        effect = result['emotion_effect']
        self.assertAlmostEqual(effect['full48']['before']['委屈'], .1)
        self.assertAlmostEqual(effect['full48']['after']['委屈'], .1)
        self.assertTrue(all(x['delta']==0 for x in effect['applied_labels']))
        self.assertTrue(all(x['label'] is None for x in effect['group_changes']))

    def test_context_and_panel_expose_template_frame_and_actual_receipt(self):
        context = self.event()
        self.assertEqual(len(context['emotion_template']['emotion_deltas']), 48)
        self.assertEqual(len(context['emotion_frame']['values']), 48)
        self.event(assessment=self.assessment(惊讶=.01))
        receipt = self.b.dispatch(dict(op='companion_panel', scope='owner-private'))
        html = Path(receipt['path']).read_text(encoding='utf-8')
        snapshot = json.loads(html.split('id="snapshot">')[1].split('</script>')[0])
        self.assertEqual(len(snapshot['emotion_assessment']['applied']), 48)
        self.assertEqual(snapshot['emotion_assessment']['group_changes'][2]['label'], '惊讶')


if __name__ == '__main__':
    unittest.main()
