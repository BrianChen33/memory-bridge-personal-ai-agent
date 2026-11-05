"""One isolated acceptance for live voice, local lookup and lifecycle photos."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c, meme_store, presentation


class Presentation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='presentation-isolated-')
        self.root = Path(self.temp.name) / 'state'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        self.b = Brain(self.root)

    def tearDown(self):
        self.b.close()
        self.temp.cleanup()

    def event(self, eid='user-one', **extra):
        request = dict(op='prepare', scope='owner-private', actor='user', person_id='owner',
                       source='fixture:isolated', event_id=eid, text='一条合成来信')
        request.update(extra)
        return self.b.dispatch(request)

    def config(self, **extra):
        (self.root / 'presentation-profile.json').write_text(json.dumps(extra), encoding='utf-8')

    def test_live_persona_refreshes_on_same_event_without_reappraisal_or_private_leak(self):
        voice = Path(self.temp.name) / 'SOUL.md'
        voice.write_text('A calm concise persona.', encoding='utf-8')
        self.config(persona_file=str(voice), life_photos=True)
        first = self.event()
        count = self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        voice.write_text('A quietly playful concise persona.', encoding='utf-8')
        again = self.event()
        self.assertNotEqual(first['current_persona']['sha256'], again['current_persona']['sha256'])
        self.assertEqual(again['current_persona']['sha256'], hashlib.sha256(voice.read_bytes()).hexdigest())
        self.assertIn('quietly playful', again['current_persona']['content'])
        self.assertEqual(count, self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0], 0)
        group = self.event('group-one', scope='qq:group:fixture', person_id='someone')
        self.assertEqual(group['current_persona']['status'], 'not_configured')
        self.assertFalse(group['camera_context']['enabled'])

    def test_automatic_lookup_reports_real_event_and_keeps_manual_search_when_disabled(self):
        with self.b.db:
            meme_store.put_public(self.b, dict(slug='fixture-broadcast', title='示例开播了',
                                              aliases=['abcxyz'], summary='合成的接梗资料'))
        result = self.event(text='ABCXYZ')
        ctx = result['expression_context']
        self.assertTrue(ctx['lookup']['attempted'])
        self.assertEqual(ctx['lookup']['source_event'], result['event']['id'])
        self.assertEqual(ctx['lookup']['candidate_count'], 1)
        self.assertEqual(ctx['candidates'][0]['title'], '示例开播了')
        self.b.dispatch(dict(op='companion_expression_config', scope='owner-private', patch={'auto_memes': False}))
        disabled = self.event('disabled', text='ABCXYZ')['expression_context']
        self.assertFalse(disabled['lookup']['attempted'])
        manual = self.b.dispatch(dict(op='meme_search', scope='owner-private', text='ABCXYZ'))
        self.assertEqual(len(manual['items']), 1)

    def test_photo_promise_waits_for_matching_cycle_and_settles_once(self):
        self.config(life_photos=True)
        source = self.event()['event']['id']
        old = c._life_event(self.b, '烘焙', 'started', '上一轮开始', occurred=1000)
        c._life_event(self.b, '烘焙', 'completed', '上一轮已结束', occurred=1500)
        started = c._life_event(self.b, '烘焙', 'started', '本轮开始', occurred=2000)
        c._set(self.b, 'life', {'activity': {'name': '烘焙', 'started_at': 2000, 'ends_at': 3000}})
        self.b.db.commit()
        plan = dict(op='companion_photo', scope='owner-private', source_event=source,
                    activity_id=started, camera='rear', when='completed')
        self.assertTrue(self.b.dispatch(plan)['ok'])
        self.assertTrue(self.b.dispatch(plan)['replayed'])
        with patch.object(c, 'stamp', return_value=2500):
            before = presentation.camera(self.b, 'owner-private')
        self.assertEqual(before['activity']['stage'], 'in_progress')
        self.assertEqual(before['activity']['remaining_seconds'], 500)
        self.assertFalse(before['photo_requests'][0]['ready'])
        with self.assertRaisesRegex(ValueError, 'photo_milestone_not_completed'):
            self.b.dispatch(dict(op='companion_photo', scope='owner-private', action='settle', source_event=source, outcome='accepted'))
        c._life_event(self.b, '烘焙', 'completed', '本轮结果', occurred=3000)
        self.b.db.commit()
        with patch.object(c, 'stamp', return_value=3001):
            after = self.b.dispatch({'op': 'companion_pending'})['camera_context']
        self.assertTrue(after['photo_requests'][0]['ready'])
        self.assertEqual(after['photo_requests'][0]['completed']['description'], '本轮结果')
        self.assertNotEqual(old, started)
        receipt = dict(op='companion_photo', scope='owner-private', action='settle', source_event=source, outcome='unknown')
        self.assertTrue(self.b.dispatch(receipt)['ok'])
        self.assertTrue(self.b.dispatch(receipt)['replayed'])
        self.assertEqual(presentation.camera(self.b, 'owner-private')['photo_requests'], [])

    def test_invalid_sources_and_broken_profile_do_not_change_configuration(self):
        with self.assertRaisesRegex(ValueError, 'real_photo_request_source'):
            self.b.dispatch(dict(op='companion_photo', scope='owner-private', source_event=99999, activity_id='not-real'))
        (self.root / 'presentation-profile.json').write_text('not json', encoding='utf-8')
        result = self.event()
        self.assertTrue(result['ok'])
        self.assertEqual(result['current_persona']['status'], 'unavailable')
        self.assertFalse(result['camera_context']['enabled'])
        self.assertEqual(self.b.dispatch(dict(op='companion_expression_config'))['values']['emotion_gain'], 1)

    def test_malformed_private_learning_does_not_break_public_lookup_or_prepare(self):
        with self.b.db:
            meme_store.put_public(self.b, dict(slug='valid-fixture', title='正常词条', aliases=['abcxyz'], summary='公开合成资料'))
            for mid, payload, evidence in [('legacy-a', '{"meaning":"manual insertion"}', 'user_teaching_fixture'),
                                            ('legacy-b', 'not-json', '[1]')]:
                self.b.db.execute('INSERT INTO ct_meme_private VALUES(?,?,?,?,?,?,?,?)',
                                  (mid, 'owner-private', mid, payload, 'active', 1, evidence, 1))
        result = self.event(text='abcxyz')
        self.assertTrue(result['ok'])
        self.assertEqual(result['expression_context']['candidates'][0]['key'], 'public:valid-fixture')
        self.assertEqual(result['expression_context']['association_patterns'], [])
        for row in self.b.db.execute('SELECT * FROM ct_meme_private'):
            self.assertFalse(meme_store.evidence_active(self.b, row))
        manual = self.b.dispatch(dict(op='meme_search', scope='owner-private', text='abcxyz'))
        self.assertEqual(len(manual['items']), 1)


if __name__ == '__main__':
    unittest.main()
