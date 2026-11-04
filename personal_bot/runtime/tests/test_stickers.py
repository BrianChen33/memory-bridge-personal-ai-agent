"""Synthetic lifecycle tests, including concurrent callers and restored ledgers."""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from brain import Brain, atomic_json
from muse_ext.stickers import DEFAULT_POLICY, intensity
from support import seed_legacy_policy

UNCHANGED = dict(version=1, changed=False, label=None,
                 delta=dict(p=0, a=0, d=0), intensity_delta=0)


class StickerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)/'private'
        self.brain = Brain(self.root)
        self.brain.dispatch(dict(op='configure', enabled=True,
                                 features=dict(events=True, emotion_events=True)))
        atomic_json(self.root/'sticker-policy.json', dict(DEFAULT_POLICY, enabled=True))
        atomic_json(self.root/'sticker-catalog.json', dict(version=1, items=[]))
        atomic_json(self.root/'backup-sources.json', dict(version=1, sources=[]))
        seed_legacy_policy(self.root)
        self.counter = 0

    def tearDown(self):
        self.brain.close()
        self.temp.cleanup()

    def event(self, text='普通短消息', assessed=True, scope='owner-private', actor='user', assessment=None):
        self.counter += 1
        q = dict(op='prepare', scope=scope, source='fixture:isolated-dot',
                 event_id=str(self.counter), actor=actor, occurred_at=1700000000, text=text)
        if assessed:
            q['emotion_assessment'] = assessment or UNCHANGED
        self.brain.dispatch(q)
        return {k: q[k] for k in ('scope', 'source', 'event_id', 'actor')}

    def call(self, event, action='decide', **kwargs):
        return self.brain.dispatch(dict(event, op='sticker', action=action, **kwargs))

    def asset(self, sid='general'):
        rel = 'media/stickers/'+sid+'.png'
        path = self.root/rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lMsAAAAASUVORK5CYII='))
        entry = dict(id=sid, path=rel, format='png', sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                     license='Synthetic test fixture, generated pixel', reviewed=True,
                     emotion=[], tags=['通用'], use=['普通互动'])
        catalog = json.loads((self.root/'sticker-catalog.json').read_text())
        catalog['items'].append(entry)
        atomic_json(self.root/'sticker-catalog.json', catalog)
        registry = json.loads((self.root/'backup-sources.json').read_text())
        registry['sources'].append(dict(name='project/'+rel, path=str(path), required=True))
        atomic_json(self.root/'backup-sources.json', registry)
        return path, entry

    def selected(self, actor='user'):
        self.asset()
        event = self.event('请发个表情包', actor=actor)
        if actor == 'user':
            self.call(event, intent=dict(mode='direct', evidence='发个表情包'))
        else:
            with patch('muse_ext.stickers.secrets.SystemRandom') as random:
                random.return_value.random.return_value = 0
                self.call(event)
        self.call(event, 'select', sticker_id='general')
        return event

    def test_intensity_formula_and_invalid_numbers(self):
        self.assertEqual(intensity(dict(ok=True,p=0,a=0,d=0)), 0)
        self.assertEqual(intensity(dict(ok=True,p=1,a=1,d=1)), 1)
        self.assertEqual(intensity(dict(ok=True,p=0,a=0,d=0,labels=[dict(label='期待',intensity=.3)])), .5)
        for bad in (True, float('nan'), float('inf'), 2, '0'):
            self.assertIsNone(intensity(dict(ok=True,p=bad,a=0,d=0)))
        self.assertEqual(intensity(dict(ok=True,p=0,a=0,d=0,labels=[dict(intensity=10)])), 0)
        self.assertEqual(intensity(dict(ok=True,p=0,a=0,d=0,labels=[dict(label='invalid',intensity=.6)])), 0)

    def test_missing_invalid_assessment_does_not_consume_draw(self):
        event = self.event(assessed=False)
        self.assertEqual(self.call(event)['status'], 'assessment_required')
        q = dict(event,op='prepare',text='普通短消息',occurred_at=1700000000,emotion_assessment={})
        self.brain.dispatch(q)
        self.assertEqual(self.call(event)['status'], 'assessment_required')
        q['emotion_assessment'] = UNCHANGED
        self.brain.dispatch(q)
        self.assertEqual(self.call(event)['status'], 'decided')

    def test_new_mood_is_used_and_no_change_does_not_reset_timestamp(self):
        assessment = dict(version=1,changed=True,label='期待',delta=dict(p=.12,a=0,d=0),intensity_delta=.12)
        event = self.event(assessment=assessment)
        at = self.brain.db.execute('SELECT at FROM mood').fetchone()[0]
        with patch('muse_ext.stickers.time.time',return_value=at):
            result = self.call(event)
            self.assertAlmostEqual(result['probability'], .52)
            self.event()
        self.assertEqual(self.brain.db.execute('SELECT at FROM mood').fetchone()[0],at)

    def test_one_draw_and_immutable_decision_on_retry(self):
        event = self.event()
        with patch('muse_ext.stickers.secrets.SystemRandom') as random:
            random.return_value.random.return_value = .41
            first = self.call(event)
            self.assertFalse(first['should_send'])
            policy = dict(DEFAULT_POLICY, enabled=True, base_probability=1.)
            atomic_json(self.root/'sticker-policy.json',policy)
            second = self.call(event)
            self.assertEqual(first['u'],second['u'])
            self.assertFalse(second['should_send'])
            random.return_value.random.assert_called_once()

    def test_direct_and_skip_have_no_random_draw(self):
        with patch('muse_ext.stickers.secrets.SystemRandom') as random:
            direct = self.call(self.event('发个表情包'),intent=dict(mode='direct',evidence='发个表情包'))
            skip = self.call(self.event('这次不要发图'),intent=dict(mode='skip',evidence='不要发图'))
            self.assertTrue(direct['should_send'])
            self.assertFalse(skip['should_send'])
            self.assertIsNone(direct['u'])
            random.assert_not_called()

    def test_auto_uses_strict_probability_boundary(self):
        with patch('muse_ext.stickers.secrets.SystemRandom') as random:
            random.return_value.random.return_value = .4
            self.assertFalse(self.call(self.event())['should_send'])
            random.return_value.random.return_value = .399999
            self.assertTrue(self.call(self.event())['should_send'])

    def test_explicit_mood_disable_uses_base_and_unavailable_status(self):
        event = self.event(assessed=False)
        self.brain.dispatch(dict(op='configure',modules=dict(mood=False)))
        result = self.call(event)
        self.assertAlmostEqual(result['probability'],.4)
        self.assertEqual(result['mood_status'],'unavailable')

    def test_explicit_intent_requires_original_user_quote(self):
        event = self.event()
        with self.assertRaisesRegex(ValueError,'actual_user_quote'):
            self.call(event,intent=dict(mode='direct',evidence='正文里没有这句话'))
        bot = self.event('发个表情包',actor='assistant')
        with self.assertRaisesRegex(ValueError,'actual_user_quote'):
            self.call(bot,intent=dict(mode='direct',evidence='发个表情包'))

    def test_control_messages_skip_without_creating_event(self):
        result = self.brain.dispatch(dict(op='sticker',action='decide',scope='owner-private',control=True))
        self.assertEqual(result['status'],'control_skipped')
        self.assertEqual(self.brain.db.execute('SELECT COUNT(*) FROM source_events').fetchone()[0],0)

    def test_short_and_serious_messages_are_both_auto(self):
        for text in ('嗯', '请推导这个金融公式，并认真核查结果。'):
            self.assertEqual(self.call(self.event(text))['mode'],'auto')

    def test_broad_fallback_after_hit_and_one_selection(self):
        self.asset('general');self.asset('other')
        event = self.event('发图')
        self.call(event,intent=dict(mode='direct',evidence='发图'))
        candidates = self.call(event,'candidates',tags=['完全不匹配'])
        self.assertEqual(len(candidates['candidates']),2)
        self.assertTrue(self.call(event,'select',sticker_id='general')['ok'])
        self.assertFalse(self.call(event,'select',sticker_id='other')['ok'])

    def test_missing_media_does_not_change_a_hit_to_miss(self):
        event = self.event('发图')
        self.call(event,intent=dict(mode='direct',evidence='发图'))
        self.assertEqual(self.call(event,'candidates')['status'],'no_available_media')
        self.assertTrue(self.call(event,'status')['should_send'])

    def test_hash_license_and_backup_registration_are_checked(self):
        path, entry = self.asset()
        event = self.event('发图')
        self.call(event,intent=dict(mode='direct',evidence='发图'))
        for field, value in [('sha256','0'*64),('reviewed',False),('path','../outside.png')]:
            atomic_json(self.root/'sticker-catalog.json',dict(version=1,items=[dict(entry,**{field:value})]))
            self.assertEqual(self.call(event,'candidates')['status'],'no_available_media')
        atomic_json(self.root/'sticker-catalog.json',dict(version=1,items=[entry]))
        atomic_json(self.root/'backup-sources.json',dict(version=1,sources=[]))
        self.assertIn('backup_registration',self.call(event,'candidates')['catalog_errors'][0]['reason'])

    def test_texts_must_finish_before_single_handoff(self):
        event = self.selected()
        self.assertEqual(self.call(event,'handoff',texts_complete=False,text_receipts=['part-1'])['status'],
                         'all_text_receipts_required')
        sent = self.call(event,'handoff',texts_complete=True,text_receipts=['part-1','part-2'])
        self.assertTrue(sent['send_once']);self.assertEqual(sent['status'],'unknown')
        retry = self.call(event,'handoff',texts_complete=True,text_receipts=['part-1','part-2'])
        self.assertFalse(retry['retry']);self.assertEqual(retry['status'],'already_handed_off')
        self.assertEqual(self.call(event,'receipt',outcome='accepted',receipt_id='media-api-1')['status'],'accepted')
        self.assertEqual(self.call(event,'status')['delivery'],'accepted')
        self.assertEqual(self.call(event,'receipt',outcome='visible',receipt_id='client-1')['status'],'visible')

    def test_media_is_revalidated_at_handoff(self):
        event = self.selected()
        (self.root/'media/stickers/general.png').write_bytes(b'changed')
        self.assertEqual(self.call(event,'handoff',texts_complete=True,text_receipts=['text-1'])['status'],
                         'selected_media_unavailable')

    def test_pause_blocks_send_but_allows_recording_actual_receipt(self):
        event = self.selected()
        self.call(event,'handoff',texts_complete=True,text_receipts=['text-1'])
        self.brain.dispatch(dict(op='configure',enabled=False))
        self.assertEqual(self.call(event,'handoff',texts_complete=True,text_receipts=['text-1'])['status'],'disabled')
        self.assertEqual(self.call(event,'receipt',outcome='accepted',receipt_id='late-api-result')['status'],'accepted')

    def test_disable_reenable_does_not_revive_old_send_permission(self):
        event = self.selected()
        self.brain.dispatch(dict(op='configure',enabled=False))
        self.brain.dispatch(dict(op='configure',enabled=True))
        self.assertEqual(self.call(event,'handoff',texts_complete=True,text_receipts=['text-1'])['status'],'stale_epoch')

    def test_shared_mood_is_opt_in_and_never_copies_private_context(self):
        assessment = dict(version=1,changed=True,label='期待',delta=dict(p=.12,a=0,d=0),intensity_delta=.12)
        self.event('主人私聊的测试原话',assessment=assessment)
        off = self.call(self.event(scope='qq:group:fixture'))
        self.assertAlmostEqual(off['probability'],.4)
        atomic_json(self.root/'sticker-policy.json',dict(DEFAULT_POLICY,enabled=True,share_owner_mood=True))
        on = self.call(self.event(scope='qq:group:fixture'))
        self.assertGreater(on['probability'],off['probability'])
        text = json.dumps(on,ensure_ascii=False)
        self.assertNotIn('原话',text);self.assertNotIn('reason',text)

    def test_proactive_output_uses_auto_but_obeys_night_gate(self):
        event = self.selected(actor='assistant')
        night = datetime(2026,11,4,2,0,tzinfo=timezone(timedelta(hours=8)))
        with patch('proactive.beijing_now',return_value=night):
            result = self.call(event,'handoff',texts_complete=True,text_receipts=['actual-text-1'])
        self.assertFalse(result['ok']);self.assertTrue(result['quiet_hours'])
        self.assertIsNone(self.call(event,'status')['delivery'])

    def test_scope_isolation_and_no_resurrection_of_forgotten_source(self):
        event = self.event()
        self.call(event)
        with self.assertRaisesRegex(ValueError,'active_sticker_source'):
            self.call(dict(event,scope='qq:group:other'),'status')
        with self.brain.db:
            self.brain.db.execute("UPDATE source_events SET status='forgotten'")
        with self.assertRaisesRegex(ValueError,'active_sticker_source'):
            self.call(event,'status')

    def test_concurrent_calls_generate_exactly_one_decision(self):
        event = self.event()
        def worker(_):
            b = Brain(self.root)
            try:
                return b.dispatch(dict(event,op='sticker',action='decide'))
            finally:
                b.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker,range(2)))
        self.assertEqual(results[0]['u'],results[1]['u'])
        self.assertEqual(sum(not r['replayed'] for r in results),1)

    def test_policy_corruption_fails_instead_of_claiming_disabled(self):
        (self.root/'sticker-policy.json').write_text('{broken')
        with self.assertRaises(ValueError):
            self.call(self.event())
