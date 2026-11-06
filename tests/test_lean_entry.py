"""Source-bound main-entry acceptance, using private temporary runtime state only."""
import copy
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest

from personal_bot import deploy


@unittest.skipUnless(shutil.which('node'), 'Node is not installed')
class LeanEntry(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lean-entry-isolated-')
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / 'muse-brain'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        stickers = self.workspace / 'stickers'
        stickers.mkdir()
        (stickers / 'config.json').write_text(json.dumps({
            'enabled': True, 'policy': {'base_probability': .4, 'max_probability': 1}
        }), encoding='utf-8')
        # Exercise the real brain. A lean commit must not invoke the expensive
        # retrieval/persona/knowledge builders even if an adapter accidentally
        # changes the operation name or the Python implementation regresses.
        (self.root / 'brain.py').write_text('''import json,sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from personal_bot import deploy
sys.path.insert(0,str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion_io,presentation,humor,plugins,events
root=Path(sys.argv[sys.argv.index('--root')+1])
q=json.load(sys.stdin)
with (root/'requests.jsonl').open('a',encoding='utf-8') as f:
    f.write(json.dumps(q,ensure_ascii=False)+'\\n')
b=Brain(root)
try:
    with ExitStack() as stack:
        if q.get('op') in ('companion_commit','companion_proactive'):
            for owner,name in [(Brain,'recall'),(companion_io,'summaries'),
                               (presentation,'persona'),(presentation,'camera'),
                               (humor,'context'),(plugins,'context'),(events,'capture_event')]:
                stack.enter_context(patch.object(owner,name,side_effect=AssertionError('commit rebuilt context')))
        result=b.dispatch(q)
    print(json.dumps(result,ensure_ascii=False))
finally:
    b.close()
''', encoding='utf-8')
        self.env = dict(os.environ, PYTHONUTF8='1',
                        PYTHONPATH=str(Path(__file__).resolve().parents[1]),
                        STICKER_PYTHON=sys.executable, STICKER_BRAIN_ROOT=str(self.root))
        self.native = {'chat_id': 'fixture:lean-owner', 'page': {'has_more': False}, 'turns': [
            {'id': 'fixture:lean-turn', 'items': [
                {'role': 'assistant', 'content': 'Synthetic assistant text is not an input.',
                 'seq': 10, 'occurred_at_ms': 1700000000000},
                {'role': 'user', 'content': '  Synthetic original\nkept intact.  ',
                 'seq': 11, 'occurred_at_ms': 1700000001000}
            ]}
        ]}

    def tearDown(self):
        self.temp.cleanup()

    def run_entry(self, phase, native=None, **extra):
        request = dict(phase=phase, native_response=native or self.native, **extra)
        result = subprocess.run([
            shutil.which('node'), str(deploy.RUNTIME / 'main_native_entry.mjs'),
            '--root', str(self.workspace), '--chat-id', 'fixture:lean-owner'
        ], input=json.dumps(request), encoding='utf-8', capture_output=True, env=self.env)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def run_main(self, request):
        result = subprocess.run([
            shutil.which('node'), str(deploy.RUNTIME / 'sticker_main.mjs'), '--root', str(self.workspace)
        ], input=json.dumps(request), encoding='utf-8', capture_output=True, env=self.env)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def requests(self):
        path = self.root / 'requests.jsonl'
        return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

    def test_feedback_captures_actual_assistant_usage_separately_from_emotion(self):
        sys.path.insert(0,str(deploy.RUNTIME))
        from brain import Brain
        b=Brain(self.root)
        try:
            b.dispatch(dict(op='plugin_manage',scope='owner-private',plugin='social-reading',action='install',
                source_dir=str(Path(__file__).resolve().parents[1]/'plugins/social-reading')))
            b.dispatch(dict(op='plugin_manage',scope='owner-private',plugin='social-reading',action='enable'))
        finally:
            b.close()
        native=copy.deepcopy(self.native)
        native['turns'][0]['items'][0].update(content='A real-shape isolated assistant expression.',
                                            occurred_at_ms=int((time.time()-150)*1000))
        native['turns'][0]['items'][1]['occurred_at_ms']=int((time.time()-180)*1000)
        code,result=self.run_entry('feedback',native=native)
        self.assertEqual(code,0,result)
        self.assertEqual(self.count('sr_output'),1)
        self.assertEqual(self.count('source_events'),1)
        self.assertEqual(self.count('ct_appraisal'),0)
        self.assertEqual(self.requests()[0]['native_outputs'][0]['seq'],10)
        code,result=self.run_entry('feedback',native=native)
        self.assertEqual(code,0,result)
        self.assertEqual(self.count('sr_output'),1)
        self.assertFalse((self.workspace/'stickers/decisions').exists())

    def count(self, table):
        with closing(sqlite3.connect(self.root / 'data' / 'brain.sqlite')) as db:
            return db.execute('SELECT count(*) FROM ' + table).fetchone()[0]

    def test_commit_reuses_the_prepared_source_without_retrieval_or_context_echo(self):
        code, prepared = self.run_entry('context')
        self.assertEqual(code, 0, prepared)
        self.assertEqual(len(prepared['context']['emotion_template']['emotion_deltas']), 48)
        assessment = prepared['context']['emotion_template']
        assessment['emotion_deltas']['好奇'] = .01
        code, committed = self.run_entry('commit', emotion_assessment=assessment)
        self.assertEqual(code, 0, committed)
        self.assertTrue(committed['ready_to_send'])
        self.assertNotIn('context', committed)
        for key in ('memories', 'current_persona', 'plugin_context', 'emotion_template'):
            self.assertNotIn(key, committed)
        self.assertEqual(len(committed['updates']['emotion_effect']['applied_labels']), 48)
        self.assertEqual(committed['event']['id'], prepared['event']['id'])
        requests = self.requests()
        self.assertEqual([q['op'] for q in requests], ['prepare', 'companion_commit'])
        commit = requests[1]
        self.assertEqual(commit['source_event'], prepared['event']['id'])
        self.assertEqual(commit['source'], 'main:sticker')
        self.assertEqual(commit['occurred_at'], 1700000001)
        self.assertEqual(commit['text'], '  Synthetic original\nkept intact.  ')
        self.assertEqual(self.count('source_events'), 1)
        self.assertEqual(self.count('ct_appraisal'), 1)

    def test_invalid_full48_then_repair_and_replay_keep_one_immutable_decision(self):
        _, prepared = self.run_entry('context')
        incomplete = copy.deepcopy(prepared['context']['emotion_template'])
        del incomplete['emotion_deltas']['纠结']
        code, invalid = self.run_entry('commit', emotion_assessment=incomplete)
        self.assertNotEqual(code, 0)
        self.assertFalse(invalid['ready_to_send'])
        self.assertEqual(invalid['emotion'], 'invalid')
        self.assertEqual(self.count('ct_appraisal'), 0)
        code, repaired = self.run_entry('commit', emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code, 0, repaired)
        self.assertTrue(repaired['ready_to_send'])
        code, replayed = self.run_entry('commit')
        self.assertEqual(code, 0, replayed)
        self.assertEqual(replayed['emotion'], 'replayed')
        for output in (repaired, replayed):
            self.assertEqual(output['decision']['roll'], invalid['decision']['roll'])
            self.assertEqual(output['decision']['decided_at'], invalid['decision']['decided_at'])
        self.assertEqual(len(list((self.workspace / 'stickers' / 'decisions').glob('*.json'))), 1)
        self.assertEqual(self.count('ct_appraisal'), 1)
        self.assertEqual([q['op'] for q in self.requests()].count('prepare'), 1)

    def test_a_new_owner_item_invalidates_an_old_snapshot_even_if_it_is_resubmitted(self):
        _, old = self.run_entry('context')
        newer = copy.deepcopy(self.native)
        newer['turns'][0]['items'].append({'role': 'user', 'content': 'A newer synthetic owner input.',
                                         'seq': 12, 'occurred_at_ms': 1700000002000})
        _, prepared = self.run_entry('context', newer)
        before = len(self.requests())
        code, stale = self.run_entry('commit', emotion_assessment=old['context']['emotion_template'])
        self.assertNotEqual(code, 0)
        self.assertFalse(stale.get('ready_to_send', False))
        self.assertEqual(stale['error'], 'new_owner_turn_requires_context')
        self.assertEqual(len(self.requests()), before)
        code, current = self.run_entry('commit', newer, emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code, 0, current)
        self.assertTrue(current['ready_to_send'])
        code, old_target = self.run_entry('gate', newer, target_seq=11)
        self.assertNotEqual(code, 0)
        self.assertEqual(old_target['error'], 'new_owner_turn_requires_context')
        _, audit = self.run_entry('audit', newer)
        self.assertEqual(audit['audit']['complete'], 1)

    def test_changed_text_time_and_native_binding_cannot_reuse_prepared_source(self):
        _, prepared = self.run_entry('context')
        for field, changed in [('content', 'Different synthetic source.'), ('occurred_at_ms', 1700000001001)]:
            with self.subTest(field=field):
                native = copy.deepcopy(self.native)
                native['turns'][0]['items'][1][field] = changed
                code, rejected = self.run_entry('commit', native, emotion_assessment=prepared['context']['emotion_template'])
                self.assertNotEqual(code, 0)
                self.assertFalse(rejected.get('ready_to_send', False))
        plain = dict(phase='commit', turnId='fixture:lean-turn', text='  Synthetic original\nkept intact.  ',
                     timestamp=1700000001, emotion_assessment=prepared['context']['emotion_template'])
        process = subprocess.run([shutil.which('node'), str(deploy.RUNTIME / 'sticker_main.mjs'), '--root', str(self.workspace)],
                                 input=json.dumps(plain), encoding='utf-8', capture_output=True, env=self.env)
        self.assertNotEqual(process.returncode, 0)
        self.assertFalse(json.loads(process.stdout).get('ready_to_send', False))
        self.assertEqual([q['op'] for q in self.requests()], ['prepare'])

    def test_reading_bindings_survive_omission_on_retry(self):
        _, prepared = self.run_entry('context')
        code, first = self.run_entry('commit', emotion_assessment=prepared['context']['emotion_template'],
                                     reading_documents=['fixture:not-observed'])
        self.assertNotEqual(code, 0)
        self.assertFalse(first['ready_to_send'])
        code, again = self.run_entry('commit')
        self.assertNotEqual(code, 0)
        self.assertFalse(again['ready_to_send'])
        self.assertIn('reading_completion', again['formal_entry']['missing'])
        self.assertEqual(again['decision']['decided_at'], first['decision']['decided_at'])
        self.assertEqual(self.count('ct_appraisal'), 1)

    def test_disabled_companion_cannot_turn_a_context_receipt_into_permission(self):
        _, prepared = self.run_entry('context')
        config = self.root / 'config.json'
        values = json.loads(config.read_text(encoding='utf-8'))
        values['enabled'] = False
        config.write_text(json.dumps(values), encoding='utf-8')
        code, result = self.run_entry('commit', emotion_assessment=prepared['context']['emotion_template'])
        self.assertNotEqual(code, 0)
        self.assertFalse(result['ready_to_send'])
        self.assertEqual(self.count('ct_appraisal'), 0)

    def test_gate_rejects_a_sticker_receipt_for_a_different_source_without_redrawing(self):
        _, prepared = self.run_entry('context')
        code, committed = self.run_entry('commit', emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code, 0, committed)
        decision = next((self.workspace / 'stickers' / 'decisions').glob('*.json'))
        record = json.loads(decision.read_text(encoding='utf-8'))
        record['event_id'] = 'fixture:a-different-source'
        decision.write_text(json.dumps(record), encoding='utf-8')
        before = len(self.requests())
        code, gate = self.run_entry('gate')
        self.assertNotEqual(code, 0)
        self.assertFalse(gate['ready_to_send'])
        self.assertIn('sticker_decision', gate['missing'])
        self.assertEqual(len(self.requests()), before)
        self.assertEqual(json.loads(decision.read_text(encoding='utf-8'))['roll'], committed['decision']['roll'])

    def test_direct_and_skip_commit_receipts_do_not_create_a_random_roll(self):
        for seq, text, want in [(12, '发个表情包', 'direct'), (13, '不要发表情包', 'skip')]:
            with self.subTest(mode=want):
                native = copy.deepcopy(self.native)
                native['turns'][0]['items'].append({'role': 'user', 'content': text, 'seq': seq,
                                                 'occurred_at_ms': 1700000000000 + seq * 1000})
                _, prepared = self.run_entry('context', native)
                code, committed = self.run_entry('commit', native, emotion_assessment=prepared['context']['emotion_template'])
                self.assertEqual(code, 0, committed)
                self.assertEqual(committed['decision']['mode'], want)
                self.assertIsNone(committed['decision']['roll'])
                self.assertEqual(committed['decision']['sampled'], want == 'direct')

    def test_feedback_forwards_verified_historical_user_items_without_a_draw_or_context(self):
        native = copy.deepcopy(self.native)
        now_ms = int(time.time() * 1000)
        native['turns'][0]['items'][1]['occurred_at_ms'] = now_ms - 182000
        native['turns'][0]['items'].append({'role': 'user', 'content': 'A second synthetic original.',
                                          'seq': 12, 'occurred_at_ms': now_ms - 181000})
        code, result = self.run_entry('feedback', native)
        self.assertEqual(code, 0, result)
        self.assertNotIn('context', result)
        self.assertNotIn('decision', result)
        self.assertEqual(result['native_sample']['chat_id'], 'fixture:lean-owner')
        requests = self.requests()
        self.assertEqual([q['op'] for q in requests], ['companion_feedback'])
        self.assertEqual(requests[0]['action'], 'scan')
        self.assertEqual(requests[0]['scope'], 'owner-private')
        self.assertEqual(requests[0]['native_events'], [
            {'source': 'main:sticker', 'event_id': 'fixture:lean-turn:user:12', 'actor': 'user',
             'text': 'A second synthetic original.', 'occurred_at': (now_ms - 181000) / 1000},
            {'source': 'main:sticker', 'event_id': 'fixture:lean-turn', 'actor': 'user',
             'text': '  Synthetic original\nkept intact.  ', 'occurred_at': (now_ms - 182000) / 1000}
        ])
        self.assertEqual(self.count('source_events'), 2)
        self.assertEqual(list((self.workspace / 'stickers' / 'decisions').glob('*.json')), [])
        self.assertEqual(list((self.workspace / 'stickers' / 'main-entry').glob('native-head-*.json')), [])

    def test_proactive_round_reuses_original_appraisal_without_capturing_or_appraising_its_own_output(self):
        seed = '''import json,sys,time
from personal_bot import deploy
sys.path.insert(0,str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c,emotion_full48
b=Brain(sys.argv[1])
try:
    life=c._life_event(b,'学习','completed','A synthetic completed life result.',occurred=time.time()-180)
    b.db.commit()
    assessment=emotion_full48.template()
    assessment['emotion_deltas']['好奇']=.01
    result=b.dispatch(dict(op='companion_life_assess',scope='owner-private',id=life,assessment=assessment))
    assert result['emotion']['status']=='updated',result
    source=b.db.execute('SELECT source_event FROM ct_life WHERE id=?',(life,)).fetchone()[0]
    print(json.dumps(dict(source_event=source)))
finally:
    b.close()
'''
        seeded = subprocess.run([sys.executable, '-c', seed, str(self.root)],
                                encoding='utf-8', capture_output=True, env=self.env)
        self.assertEqual(seeded.returncode, 0, seeded.stdout + seeded.stderr)
        source = json.loads(seeded.stdout)['source_event']
        outgoing = dict(phase='proactive', actor='assistant', turnId='fixture:life-share',
                        text='A synthetic outgoing life share.', source_events=[source])
        code, one = self.run_main(outgoing)
        self.assertEqual(code, 0, one)
        self.assertTrue(one['ready_to_send'])
        self.assertEqual(one['emotion'], 'replayed')
        self.assertEqual(one['emotion_origin'], 'original_events')
        self.assertFalse(one['assessment_required'])
        self.assertNotIn('context', one)
        self.assertIsNone(one['event'])
        code, again = self.run_main(outgoing)
        self.assertEqual(code, 0, again)
        self.assertEqual(again['decision']['roll'], one['decision']['roll'])
        self.assertEqual(again['decision']['decided_at'], one['decision']['decided_at'])
        self.assertEqual(len(list((self.workspace / 'stickers' / 'decisions').glob('*.json'))), 1)
        self.assertEqual(self.count('source_events'), 1)
        self.assertEqual(self.count('ct_appraisal'), 1)
        self.assertEqual([q['op'] for q in self.requests()], ['companion_proactive', 'companion_proactive'])
        code, news = self.run_main(dict(phase='proactive', actor='assistant', turnId='fixture:news-share',
                                       text='A synthetic news delivery with no new stimulus.'))
        self.assertEqual(code, 0, news)
        self.assertEqual(news['emotion'], 'not_applicable_self_output')
        self.assertEqual(news['emotion_origin'], 'no_new_stimulus')
        self.assertFalse(news['assessment_required'])
        self.assertFalse(news['decision']['degraded'])
        code, invalid = self.run_main(dict(outgoing, turnId='fixture:bad-share', source_events=[999999]))
        self.assertNotEqual(code, 0)
        self.assertFalse(invalid['ready_to_send'])
        self.assertFalse(invalid['assessment_required'])
        self.assertEqual(self.count('source_events'), 1)
        self.assertEqual(self.count('ct_appraisal'), 1)


    def test_feedback_selects_lossless_records_under_the_real_stdin_byte_limit(self):
        native=copy.deepcopy(self.native)
        now=int((time.time()-180)*1000)
        native['turns'][0]['items']=[dict(role='user',content='原样保留的用户输入',seq=1,occurred_at_ms=now)]
        for i in range(4):
            native['turns'][0]['items'].append(dict(role='assistant',content='字'*6000,
                seq=2+i,occurred_at_ms=now+1000+i))
        code,result=self.run_entry('feedback',native=native)
        self.assertEqual(code,0,result)
        sent=self.requests()[0]
        self.assertLessEqual(len(json.dumps(sent,ensure_ascii=False).encode('utf-8')),65536)
        self.assertTrue(sent['coverage']['partial'])
        self.assertEqual(sent['native_events'][0]['text'],'原样保留的用户输入')
        self.assertTrue(all(x['text']=='字'*6000 for x in sent['native_outputs']))
        self.assertGreater(len(sent['native_outputs']),0)
        self.assertLess(len(sent['native_outputs']),4)


if __name__ == '__main__':
    unittest.main()
