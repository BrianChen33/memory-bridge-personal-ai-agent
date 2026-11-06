"""Final isolated driver checks; no native sender, browser or production state."""
import copy
import json
import shutil
import subprocess
import unittest
import hashlib
import time

from personal_bot import deploy
import test_lean_entry as entry_fixture


class ReplyDriver(entry_fixture.LeanEntry):
    def driver(self, **request):
        result = subprocess.run([shutil.which('node'), str(deploy.RUNTIME/'reply_driver.mjs'),
            '--root', str(self.workspace), '--chat-id', self.native['chat_id']],
            input=json.dumps(request), encoding='utf-8', capture_output=True, env=self.env)
        self.assertTrue(result.stdout.strip(), result.stderr)
        return result.returncode, json.loads(result.stdout)

    def test_driver_commits_original_source_without_builder_or_retrieval(self):
        code, prepared = self.driver(phase='context', native_response=self.native)
        self.assertEqual(code, 0, prepared)
        assessment = prepared['context']['emotion_template']
        assessment['emotion_deltas']['好奇'] = .01
        code, committed = self.driver(phase='commit', ticket=prepared['ticket'], emotion_assessment=assessment)
        self.assertEqual(code, 0, committed)
        self.assertTrue(committed['ready_to_send'])
        self.assertNotIn('context', committed)
        self.assertEqual(self.requests()[0]['text'], self.native['turns'][0]['items'][1]['content'])
        self.assertEqual([q['op'] for q in self.requests()], ['prepare', 'companion_commit'])
        code, replay = self.driver(phase='commit', ticket=prepared['ticket'], emotion_assessment=assessment)
        self.assertEqual(code, 0, replay)
        self.assertEqual(committed['decision']['roll'], replay['decision']['roll'])
        self.assertEqual(self.count('ct_appraisal'), 1)

    def test_driver_new_owner_input_invalidates_an_older_ticket(self):
        _, old = self.driver(phase='context', native_response=self.native)
        native = copy.deepcopy(self.native)
        native['turns'][0]['items'].append(dict(role='user', content='A newer synthetic input.',
            seq=12, occurred_at_ms=1700000002000))
        code, newer = self.driver(phase='context', native_response=native)
        self.assertEqual(code, 0, newer)
        code, rejected = self.driver(phase='commit', ticket=old['ticket'],
            emotion_assessment=old['context']['emotion_template'])
        self.assertNotEqual(code, 0, rejected)
        self.assertFalse(rejected.get('ready_to_send', False))
        self.assertEqual(self.count('ct_appraisal'), 0)

    def test_driver_accepts_fresh_native_metadata_without_rebinding_old_source(self):
        _, old = self.driver(phase='context', native_response=self.native)
        native = copy.deepcopy(self.native)
        native['turns'][0]['items'].append(dict(role='user', content='Another real-shape fixture.',
            seq=12, occurred_at_ms=1700000002000))
        code, rejected = self.driver(phase='commit', ticket=old['ticket'], native_response=native,
            emotion_assessment=old['context']['emotion_template'])
        self.assertNotEqual(code, 0, rejected)
        self.assertEqual(rejected['error'], 'new_owner_turn_requires_context')

    def test_driver_ticket_tampering_and_path_traversal_cannot_capture_input(self):
        _, prepared = self.driver(phase='context', native_response=self.native)
        path = self.workspace/'stickers/reply-rounds'/(prepared['ticket']+'.json')
        record = json.loads(path.read_text(encoding='utf-8'))
        record['native']['turns'][0]['items'][0]['content'] = 'Changed fixture.'
        path.write_text(json.dumps(record), encoding='utf-8')
        for ticket in [prepared['ticket'], '../../outside']:
            code, result = self.driver(phase='commit', ticket=ticket,
                emotion_assessment=prepared['context']['emotion_template'])
            self.assertNotEqual(code, 0, result)
        self.assertEqual(len(self.requests()), 1)

    def test_driver_incomplete_assessment_can_repair_same_ticket_without_reroll(self):
        _, prepared = self.driver(phase='context', native_response=self.native)
        malformed = copy.deepcopy(prepared['context']['emotion_template'])
        malformed['emotion_deltas'].pop(next(iter(malformed['emotion_deltas'])))
        code, rejected = self.driver(phase='commit', ticket=prepared['ticket'], emotion_assessment=malformed)
        self.assertNotEqual(code, 0, rejected)
        code, repaired = self.driver(phase='commit', ticket=prepared['ticket'],
            emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code, 0, repaired)
        self.assertTrue(repaired['ready_to_send'])
        self.assertEqual(rejected['decision']['roll'], repaired['decision']['roll'])

    def test_driver_coherent_rebinding_and_python_runtime_upgrade_invalidate_ticket(self):
        _,old=self.driver(phase='context',native_response=self.native)
        native=copy.deepcopy(self.native)
        native['turns'][0]['items'].append(dict(role='user',content='Current synthetic input',seq=12,occurred_at_ms=1700000002000))
        _,new=self.driver(phase='context',native_response=native)
        folder=self.workspace/'stickers/reply-rounds'
        rebound=json.loads((folder/(new['ticket']+'.json')).read_text(encoding='utf-8'))
        rebound['ticket']=old['ticket']
        (folder/(old['ticket']+'.json')).write_text(json.dumps(rebound),encoding='utf-8')
        code,result=self.driver(phase='commit',ticket=old['ticket'],emotion_assessment=new['context']['emotion_template'])
        self.assertNotEqual(code,0,result)
        with (self.root/'brain.py').open('a',encoding='utf-8') as f:f.write('\n# synthetic runtime upgrade\n')
        code,result=self.driver(phase='commit',ticket=new['ticket'],emotion_assessment=new['context']['emotion_template'])
        self.assertNotEqual(code,0,result)
        self.assertEqual(self.count('ct_appraisal'),0)

    def test_driver_timings_do_not_persist_text_or_claim_model_telemetry(self):
        _, prepared = self.driver(phase='context', native_response=self.native)
        self.assertGreaterEqual(prepared['timing']['local_ms'], 0)
        path = self.workspace/'stickers/reply-rounds/timings.json'
        text = path.read_text(encoding='utf-8')
        self.assertNotIn(self.native['turns'][0]['items'][1]['content'], text)
        code, stats = self.driver(phase='stats')
        self.assertEqual(code, 0, stats)
        self.assertEqual(stats['phases']['context']['count'], 1)
        self.assertNotIn('model_ms', text)
        self.assertEqual(len(self.requests()), 1)

    def test_driver_local_media_selects_once_and_respects_shared_sent_ledger(self):
        folder = self.workspace/'stickers'
        (folder/'config.json').write_text(json.dumps(dict(enabled=True,policy=dict(base_probability=1,max_probability=1))),encoding='utf-8')
        (folder/'meta').mkdir()
        (folder/'assets').mkdir()
        items=[]
        for i in range(12):
            blob=b'GIF89a'+bytes([i])*20
            digest=hashlib.sha1(blob).hexdigest()[:12]
            (folder/'assets'/(digest+'.gif')).write_bytes(blob)
            items.append(dict(id='fixture/'+str(i),hash=digest,emotion='合成',text='合成图'))
        (folder/'meta/nekowhale.json').write_text(json.dumps(dict(stickers=items)),encoding='utf-8')
        ledger={item['id']:int(time.time()*1000) for item in items[:-1]}
        (folder/'recently_sent.json').write_text(json.dumps(ledger),encoding='utf-8')
        _, prepared=self.driver(phase='context',native_response=self.native)
        code, committed=self.driver(phase='commit',ticket=prepared['ticket'],emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code,0,committed)
        self.assertTrue(committed['ready_to_send'])
        self.assertEqual(committed['media']['asset_id'],'fixture/11')
        self.assertEqual(committed['media']['delivery'],'unconfirmed')
        avoided=json.loads((folder/'recently_sent.json').read_text())
        self.assertEqual({k:v for k,v in avoided.items() if k!='fixture/11'},ledger)
        self.assertIn('fixture/11',avoided)  # Conservative cross-channel reservation, no delivered status.
        self.assertEqual(committed['decision']['send_status'],'not_handed_off')
        _, again=self.driver(phase='media',ticket=prepared['ticket'])
        self.assertEqual(again['media']['asset_id'],committed['media']['asset_id'])
        code,rejected=self.driver(phase='finish',ticket=prepared['ticket'],outcome='accepted',text_finished=True)
        self.assertNotEqual(code,0,rejected)
        code,finished=self.driver(phase='finish',ticket=prepared['ticket'],outcome='accepted',text_finished=True,receipt='fixture:actual-final')
        self.assertEqual(code,0,finished)
        stamp=json.loads((folder/'recently_sent.json').read_text())['fixture/11']
        _, replay=self.driver(phase='finish',ticket=prepared['ticket'],outcome='accepted',text_finished=True,receipt='fixture:actual-final')
        self.assertTrue(replay['replayed'])
        self.assertEqual(json.loads((folder/'recently_sent.json').read_text())['fixture/11'],stamp)
        self.assertEqual(self.count('ct_appraisal'),1)

    def test_driver_missing_local_media_keeps_draw_and_text_ready(self):
        folder=self.workspace/'stickers'
        (folder/'config.json').write_text(json.dumps(dict(enabled=True,policy=dict(base_probability=1,max_probability=1))),encoding='utf-8')
        _,prepared=self.driver(phase='context',native_response=self.native)
        code,result=self.driver(phase='commit',ticket=prepared['ticket'],emotion_assessment=prepared['context']['emotion_template'])
        self.assertEqual(code,0,result)
        self.assertTrue(result['ready_to_send'])
        self.assertTrue(result['decision']['sampled'])
        self.assertEqual(result['media']['status'],'media_unavailable')


def load_tests(loader, tests, pattern):
    # Reuse a fixture without repeating the full inherited baseline suite.
    return unittest.TestSuite(ReplyDriver(name) for name in ReplyDriver.__dict__ if name.startswith('test_driver_'))
