"""Compact input preserves full48 state math and strict legacy validation."""
import unittest
from personal_bot import deploy
import sys
sys.path.insert(0,str(deploy.RUNTIME))
from muse_ext.emotion_full48 import template,compact_template,normalize,bound
from muse_ext.emotion_catalog import LABELS


class CompactEmotion(unittest.TestCase):
    def test_mixed_signed_input_is_exactly_equivalent_to_full_input(self):
        compact=compact_template()
        compact['emotion_deltas'].update(欣喜=-.01,委屈=.02,亲近=.005)
        full=template()
        full['emotion_deltas'].update(compact['emotion_deltas'])
        self.assertEqual(normalize(compact),normalize(full))
        self.assertEqual(bound(normalize(compact)),bound(normalize(full)))
        self.assertEqual(compact['format'],'compact48-v1')  # caller input is unchanged

    def test_omitted_values_are_zero_without_fabricating_positive_feelings(self):
        raw=normalize(compact_template())
        self.assertEqual(set(raw['emotion_deltas']),set(LABELS))
        self.assertFalse(raw['changed'])
        self.assertTrue(all(value==0 for value in raw['emotion_deltas'].values()))
        self.assertIsNone(raw['label'])

    def test_unknown_labels_and_invalid_numbers_are_rejected(self):
        for changes in [{'made-up':.01},{'欣喜':True},{'欣喜':float('nan')},{'欣喜':.9}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                raw=compact_template();raw['emotion_deltas'].update(changes);normalize(raw)
        with self.assertRaises(ValueError):
            raw=compact_template();raw['emotion_deltas']=[];normalize(raw)

    def test_legacy_full_input_still_requires_all48(self):
        raw=template();raw['emotion_deltas'].pop('欣喜')
        with self.assertRaisesRegex(ValueError,'exactly_all_48'):
            normalize(raw)

    def test_compact_input_keeps_required_existing_appraisal_and_pad_shape(self):
        for field in ['delta','appraisal']:
            raw=compact_template();raw.pop(field)
            with self.assertRaises(ValueError):normalize(raw)
        raw=compact_template();raw['appraisal']['extra_reflection']='not a new field'
        with self.assertRaises(ValueError):normalize(raw)
