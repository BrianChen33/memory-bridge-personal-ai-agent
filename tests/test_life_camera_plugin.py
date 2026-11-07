"""Synthetic plugin acceptance. No image service, network, native sends or persona."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c, plugins, presentation


PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'life-camera'
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=')


class LifeCamera(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='camera-isolated-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'state'
        deploy.init(self.root)
        deploy.enable(self.root, list(deploy.DEFAULT_FEATURES))
        self.b = Brain(self.root)
        self.addCleanup(self.b.close)
        self.clock = patch.object(c, 'stamp', return_value=datetime.fromisoformat('2026-11-08T12:00:00+08:00').timestamp())
        self.now = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.b.dispatch(dict(op='plugin_manage', action='install', source_dir=str(PLUGIN)))
        self.b.dispatch(dict(op='plugin_manage', action='enable', plugin='life-camera'))
        self.image = Path(self.temp.name) / 'synthetic.png'
        self.image.write_bytes(PNG)
        self.call('asset_put', authorized=True, category='characters', id='fixture',
                  name='Synthetic character', description='A blue illustrated test mascot.', images=[str(self.image)])
        self.call('configure', authorized=True, patch={'character_id': 'fixture'})
        self.call('bind_host', authorized=True, binding=dict(image_tool='synthetic.image',
                  background_runner='synthetic.task', delivery_route='synthetic.owner-main',
                  reference_images=True, separate_delivery=True, receipt='synthetic-capability-readback'))

    def call(self, action, **args):
        return self.b.dispatch(dict(op='plugin_call', plugin='life-camera', scope='owner-private', action=action, **args))

    def life(self, name='Fixture activity', stage='progress'):
        lid = c._life_event(self.b, name, stage, 'A released synthetic stage.')
        with self.b.db:
            self.b.db.execute('UPDATE ct_life SET appraised=1 WHERE id=?', (lid,))
        return lid

    def user(self):
        result = self.b.dispatch(dict(op='prepare', scope='owner-private', source='fixture:camera',
                                     event_id='request-' + str(self.now.return_value), actor='user',
                                     person_id='owner', text='Synthetic explicit image request.'))
        return result['event']['id']

    def plan(self, **args):
        return self.call('plan', life_id=args.pop('life_id', None) or self.life(),
                         camera=args.pop('camera', 'selfie'), prompt='Resting by the window.',
                         expression='quietly amused', caption='A synthetic caption.', **args)

    def rendered(self, job):
        work = self.call('work')
        self.assertEqual(work['job']['id'], job['id'])
        token = work['claim']
        self.call('bind', id=job['id'], claim=token, native_task_id='native-fixture')
        ready = self.call('rendered', id=job['id'], claim=token, native_task_id='native-fixture',
                          files=[str(self.image)], receipt='synthetic-tool-receipt')
        return ready

    def test_reference_is_first_real_file_and_context_stays_compact(self):
        job = self.plan()['job']
        work = self.call('work')
        self.assertEqual(work['request']['references'][0]['role'], 'identity_style')
        self.assertTrue(Path(work['request']['references'][0]['path']).is_file())
        self.assertIn('three-view', work['request']['prompt'])
        ctx = presentation.camera(self.b, 'owner-private')
        self.assertEqual(ctx['plugin'], 'life-camera')
        self.assertNotIn('base64', json.dumps(ctx))
        self.assertLess(len(json.dumps(ctx)), 6000)
        self.assertEqual(self.call('work')['status'], 'busy')
        self.assertEqual(job['status'], 'queued')

    def test_one_job_per_source_and_one_sender(self):
        lid = self.life()
        first = self.plan(life_id=lid)
        self.assertTrue(self.plan(life_id=lid)['replayed'])
        self.rendered(first['job'])
        send = self.call('send_work')
        self.assertEqual(send['job']['id'], first['job']['id'])
        self.assertIsNone(self.call('send_work')['job'])
        with self.assertRaisesRegex(ValueError, 'receipt'):
            self.call('settle', id=first['job']['id'], claim=send['claim'], outcome='accepted')
        done = self.call('settle', id=first['job']['id'], claim=send['claim'],
                         outcome='accepted', receipt='actual-fixture-send')
        self.assertEqual(done['job']['status'], 'accepted')
        self.assertTrue(self.call('settle', id=first['job']['id'], claim=send['claim'],
                                  outcome='accepted', receipt='actual-fixture-send')['replayed'])

    def test_invalid_or_unassessed_life_source_cannot_plan(self):
        with self.assertRaises(ValueError):
            self.plan(life_id='unreleased-future-stage')
        lid = c._life_event(self.b, 'Fixture', 'started', 'Not appraised.')
        with self.assertRaisesRegex(ValueError, 'appraised'):
            self.plan(life_id=lid)

    def test_quiet_auto_waits_but_explicit_owner_request_can_run(self):
        self.now.return_value = datetime.fromisoformat('2026-11-09T02:00:00+08:00').timestamp()
        job = self.plan()['job']
        self.assertEqual(self.call('work')['status'], 'quiet')
        manual = self.plan(source_event=self.user())['job']
        self.assertEqual(self.call('work')['job']['id'], manual['id'])
        self.assertNotEqual(job['id'], manual['id'])

    def test_reference_change_and_tampering_are_detected(self):
        job = self.plan()['job']
        self.call('asset_put', authorized=True, category='characters', id='fixture', name='Changed',
                  description='Changed identity description.', images=[str(self.image)])
        self.assertEqual(self.call('work')['status'], 'empty')
        self.assertEqual(self.call('status')['recent'][0]['status'], 'stale')
        self.assertEqual(job['status'], 'queued')
        path = self.call('assets', category='characters')['items'][0]['images'][0]['path']
        Path(path).write_bytes(b'not an image')
        with self.assertRaisesRegex(ValueError, 'reference'):
            self.plan(life_id=self.life('Another activity'))

    def test_abandoned_work_reconciles_without_blocking_other_jobs(self):
        first = self.plan()['job']
        work = self.call('work')
        self.now.return_value += 901
        self.call('reconcile')
        self.assertEqual(self.call('status')['recent'][0]['status'], 'generation_unknown')
        other = self.plan(life_id=self.life('Other activity'))['job']
        self.assertEqual(self.call('work')['job']['id'], other['id'])
        self.assertEqual(self.plan(life_id=self.b.db.execute('SELECT life_id FROM lc_job WHERE id=?', (first['id'],)).fetchone()[0])['job']['id'], first['id'])
        self.assertTrue(work['claim'])

    def test_cooldown_explicit_request_and_disabled_legacy_path(self):
        job = self.plan()['job']
        self.rendered(job)
        send = self.call('send_work')
        self.call('settle', id=job['id'], claim=send['claim'], outcome='accepted', receipt='sent')
        self.assertEqual(self.plan(life_id=self.life('Next'))['status'], 'cooldown')
        self.assertTrue(self.plan(source_event=self.user())['ok'])
        (self.root / 'presentation-profile.json').write_text('{"life_photos":true}', encoding='utf-8')
        self.b.dispatch(dict(op='plugin_manage', action='disable', plugin='life-camera'))
        self.assertFalse(presentation.camera(self.b, 'owner-private')['enabled'])
        self.assertFalse(presentation.camera(self.b, 'qq:group:fixture')['enabled'])

    def test_output_and_send_receipts_survive_reopen(self):
        job = self.plan()['job']
        self.rendered(job)
        self.b.close()
        self.b = Brain(self.root)
        self.addCleanup(self.b.close)
        send = self.call('send_work')
        self.call('settle', id=job['id'], claim=send['claim'], outcome='unknown', receipt='timeout-fixture')
        self.assertIsNone(self.call('send_work')['job'])
        self.assertEqual(self.call('status')['recent'][0]['status'], 'unknown')
        self.call('settle', id=job['id'], claim=send['claim'], outcome='accepted', receipt='late-actual-receipt')
        self.assertIsNone(self.call('send_work')['job'])
        self.assertEqual(self.call('status')['recent'][0]['status'], 'accepted')
        self.assertNotIn('prompt', json.loads(self.b.db.execute('SELECT plan FROM lc_job WHERE id=?', (job['id'],)).fetchone()[0]))

    def test_configuration_and_owner_scope_are_validated(self):
        for value in (True, float('nan'), -1, 241):
            with self.assertRaises(ValueError):
                self.call('configure', authorized=True, patch={'cooldown_minutes': value})
        with self.assertRaises(ValueError):
            self.call('configure', patch={'automatic': False})
        with self.assertRaises(ValueError):
            self.b.dispatch(dict(op='plugin_call', plugin='life-camera', scope='qq:group:fixture', action='status'))
        with self.assertRaisesRegex(ValueError, 'owner_private'):
            self.b.dispatch(dict(op='companion_photo', scope='qq:group:fixture', action='settle',
                                 source_event=1, outcome='accepted', receipt='untrusted-fixture'))

    def test_reference_quota_preserves_identity_and_rear_camera(self):
        self.call('configure', authorized=True, patch={'max_references': 2})
        for category, identity in [('outfits', 'clothes'), ('scenes', 'room'), ('props', 'cup')]:
            self.call('asset_put', authorized=True, category=category, id=identity, name=identity,
                      description='Synthetic ' + category, images=[str(self.image)])
        result = self.call('plan', life_id=self.life(), camera='rear', prompt='A cup on a table.',
                           outfit='clothes', scene='room', props=['cup'])
        work = self.call('work')
        self.assertEqual(work['job']['id'], result['job']['id'])
        self.assertEqual(len(work['request']['references']), 2)
        self.assertEqual(work['request']['references'][0]['role'], 'identity_style')
        self.assertIn('stays behind the camera', work['request']['prompt'])

    def test_photo_promise_uses_matching_completion_and_same_receipt(self):
        event = self.user()
        start = c._life_event(self.b, 'Fixture baking', 'started', 'Started now.')
        self.b.dispatch(dict(op='companion_photo', scope='owner-private', action='request',
                             source_event=event, activity_id=start, camera='rear', when='completed'))
        with self.assertRaisesRegex(ValueError, 'stage_not_ready'):
            self.plan(source_event=event, camera='rear')
        self.now.return_value += 60
        finish = c._life_event(self.b, 'Fixture baking', 'completed', 'Completed now.')
        with self.assertRaisesRegex(ValueError, 'camera_conflict'):
            self.plan(source_event=event, camera='selfie')
        job = self.plan(source_event=event, camera='rear')['job']
        self.assertEqual(job['life_id'], finish)
        self.rendered(job)
        send = self.call('send_work')
        with self.assertRaisesRegex(ValueError, 'receipt'):
            self.b.dispatch(dict(op='companion_photo', scope='owner-private', action='settle',
                                 source_event=event, outcome='accepted'))
        self.call('settle', id=job['id'], claim=send['claim'], outcome='unknown', receipt='promise-timeout')
        self.call('settle', id=job['id'], claim=send['claim'], outcome='accepted', receipt='promise-sent')
        self.assertEqual(presentation.camera(self.b, 'owner-private')['photo_requests'], [])
        self.assertEqual(c._get(self.b, 'life_photo_requests', [])[0]['status'], 'accepted')
        self.assertTrue(self.plan(source_event=event, camera='rear')['replayed'])

    def test_private_snapshot_contains_original_art_without_album(self):
        from personal_bot import vault
        self.rendered(self.plan()['job'])
        destination = Path(self.temp.name) / 'private-snapshot'
        manifest = vault.export_snapshot(self.root, destination, 'a' * 40, bootstrap=True)
        names = [item['path'] for item in manifest['files']]
        self.assertTrue(any(name.startswith('assets/life-camera/references/') for name in names))
        self.assertFalse(any('/photos/' in name for name in names))
        self.assertEqual(len(presentation.camera_backup_sources(self.b)), 1)

    def test_concurrent_planning_and_work_have_single_winners(self):
        from concurrent.futures import ThreadPoolExecutor
        lid = self.life()
        def worker(action):
            brain = Brain(self.root)
            try:
                args = dict(op='plugin_call', plugin='life-camera', scope='owner-private', action=action)
                if action == 'plan':
                    args.update(life_id=lid, camera='selfie', prompt='A concurrent synthetic scene.')
                return brain.dispatch(args)
            finally:
                brain.close()
        with ThreadPoolExecutor(max_workers=2) as executor:
            plans = list(executor.map(worker, ['plan', 'plan']))
        self.assertEqual(plans[0]['job']['id'], plans[1]['job']['id'])
        with ThreadPoolExecutor(max_workers=2) as executor:
            claims = list(executor.map(worker, ['work', 'work']))
        self.assertEqual(sorted(result['status'] for result in claims), ['busy', 'claimed'])

    def test_disabled_auto_and_inflight_reference_change_gate_delivery(self):
        job = self.plan()['job']
        self.rendered(job)
        self.call('configure', authorized=True, patch={'automatic': False})
        self.assertIsNone(self.call('send_work')['job'])
        self.assertEqual(self.call('status')['recent'][0]['status'], 'stale')

    def test_restored_jobs_cannot_send_before_real_host_rebinding(self):
        self.rendered(self.plan()['job'])
        with self.b.db:
            c._set(self.b, 'life_camera_host', {'host_identity': 'another-host'})
        self.assertEqual(self.call('status')['status'], 'awaiting_host_binding')
        self.assertEqual(self.call('send_work')['status'], 'awaiting_host_binding')
        self.assertEqual(self.b.db.execute('SELECT status FROM lc_job').fetchone()[0], 'ready')

    def test_historical_life_does_not_become_fresh_automatic_photo(self):
        lid = c._life_event(self.b, 'Yesterday', 'completed', 'An old released scene.',
                            occurred=self.now.return_value - 86400)
        with self.b.db:
            self.b.db.execute('UPDATE ct_life SET appraised=1 WHERE id=?', (lid,))
        self.assertEqual(self.plan(life_id=lid)['status'], 'scene_expired')
        self.assertTrue(self.plan(life_id=lid, source_event=self.user())['job']['manual'])


