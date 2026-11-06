"""Final isolated acceptance: synthetic observations, no login/network/sends."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace as Item
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1] / 'plugins' / 'mi-fitness'


def module(name, file):
    spec = importlib.util.spec_from_file_location(name, PLUGIN / file)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


worker = module('mi_fitness_worker_acceptance', 'bridge.py')
shim = module('mi_fitness_plugin_acceptance', '__init__.py')


class FakeClient:
    session = None

    def __init__(self, records=None):
        self.records = records or {}
        self.calls = []

    def __getattr__(self, metric):
        def read(first, last):
            self.calls.append(metric)
            return Item(records=self.records.get(metric, []), notes=[])
        return read


class MiFitnessAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='health-isolated-')
        self.addCleanup(self.temp.cleanup)
        self.private = Path(self.temp.name) / 'private'
        self.now = time.time()
        self.day = worker.day_at(self.now).isoformat()

    def sleep(self):
        return Item(date=self.day, asleep_min=60, deep_min=None, light_min=40, rem_min=20, awake_min=2,
                    avg_hr_bpm=999, avg_spo2_pct=999,
                    sessions=[Item(start_epoch_s=self.now-3720, end_epoch_s=self.now, asleep_min=60)])

    def test_projection_keeps_sleep_not_independent_vitals_or_zero_fill(self):
        value = worker.project('sleep', self.sleep())
        self.assertIsNone(value['deep_min'])
        self.assertNotIn('999', json.dumps(value))
        self.assertNotIn('avg_hr_bpm', value)
        with self.assertRaises(ValueError):
            worker.project('heart_rate', self.sleep())

    def test_sync_allowlist_hourly_gate_missing_records_and_silent_baseline(self):
        fake = FakeClient({'sleep': [self.sleep()]})
        result = worker.sync(self.private, fake, self.now)
        self.assertTrue(result['initial_baseline'])
        self.assertEqual(fake.calls, list(worker.ALLOWED))
        self.assertEqual(worker.sync(self.private, fake, self.now+1)['status'], 'cached')
        self.assertEqual(len(fake.calls), 4)
        db = worker.database(self.private)
        self.addCleanup(db.close)
        self.assertEqual(db.execute("SELECT count(*) FROM care WHERE status='pending'").fetchone()[0], 0)
        self.assertEqual(db.execute("SELECT count(*) FROM daily WHERE metric='steps'").fetchone()[0], 0)

    def test_owner_context_is_cache_only_and_cross_scope_is_empty(self):
        fake = FakeClient({'sleep': [self.sleep()]})
        worker.sync(self.private, fake, self.now)
        brain = Path(self.temp.name) / 'brain'
        brain.mkdir()
        (brain / 'mi-fitness.json').write_text(json.dumps({'private_dir': str(self.private), 'worker_python': 'unused', 'chat_summary_memory_allowed': True}))
        b = Item(root=brain)
        with patch.object(shim.subprocess, 'run', side_effect=AssertionError('foreground network worker')):
            value = shim.context(b, {'scope': 'owner-private'})
        self.assertEqual(value['recent']['sleep'][0]['asleep_min'], 60)
        self.assertLess(len(json.dumps(value)), 3000)
        self.assertEqual(shim.context(b, {'scope': 'qq:group:synthetic'}), {})

    def test_context_waits_for_conversation_backup_choice(self):
        worker.sync(self.private, FakeClient({'sleep': [self.sleep()]}), self.now)
        brain = Path(self.temp.name) / 'brain'
        brain.mkdir()
        (brain / 'mi-fitness.json').write_text(json.dumps({'private_dir': str(self.private), 'worker_python': 'unused'}))
        value = shim.context(Item(root=brain), {'scope': 'owner-private'})
        self.assertEqual(value['status'], 'awaiting_summary_privacy_choice')
        self.assertNotIn('recent', value)

    def test_newest_workouts_remain_in_compact_projection(self):
        workouts = [Item(start_epoch_s=self.now-i*100, end_epoch_s=self.now-i*100+1, sport='walking',
                         duration_s=1, distance_m=1, active_kcal=1, steps=i) for i in range(3)]
        worker.sync(self.private, FakeClient({'workouts': workouts}), self.now)
        value = json.loads((self.private / 'context.json').read_text())
        self.assertEqual([r['steps'] for r in value['recent']['workouts']], [0, 1])

    def test_care_quiet_claim_receipt_and_unknown_not_resent(self):
        root = worker.private_root(self.private)
        db = worker.database(root)
        self.addCleanup(db.close)
        noon = worker.datetime(2026, 1, 10, 12, tzinfo=worker.TZ).timestamp()
        quiet = worker.datetime(2026, 1, 10, 2, tzinfo=worker.TZ).timestamp()
        with db:
            db.execute("INSERT INTO care(id,payload,created,status) VALUES('fixture','{}',?,'pending')", (quiet,))
        self.assertFalse(worker.care_work(db, quiet)['candidates'])
        self.assertEqual(len(worker.care_work(db, noon)['candidates']), 1)
        self.assertFalse(worker.care_work(db, noon+1)['candidates'])
        with self.assertRaises(ValueError):
            worker.settle(db, 'fixture', 'delivered', '')
        self.assertFalse(worker.care_work(db, noon+901)['candidates'])
        self.assertEqual(db.execute("SELECT status FROM care WHERE id='fixture'").fetchone()[0], 'unknown')

    def test_storage_inside_brain_rejected(self):
        brain = Path(self.temp.name) / 'brain'
        brain.mkdir()
        (brain / 'mi-fitness.json').write_text(json.dumps({'private_dir': str(brain/'secrets'), 'worker_python': 'unused'}))
        with self.assertRaises(ValueError):
            shim.configuration(Item(root=brain))

    def test_optional_plugin_installs_disabled_then_projects_through_existing_hook(self):
        from personal_bot import deploy
        sys.path.insert(0, str(deploy.RUNTIME))
        from brain import Brain
        from muse_ext.plugins import context
        root = Path(self.temp.name) / 'brain-state'
        deploy.init(root)
        deploy.enable(root, list(deploy.DEFAULT_FEATURES))
        b = Brain(root)
        self.addCleanup(b.close)
        result = b.dispatch({'op': 'plugin_manage', 'scope': 'owner-private', 'plugin': 'mi-fitness',
                             'action': 'install', 'source_dir': str(PLUGIN)})
        self.assertFalse(result['enabled'])
        self.assertNotIn('mi-fitness', context(b, {'scope': 'owner-private'}))
        b.dispatch({'op': 'plugin_manage', 'scope': 'owner-private', 'plugin': 'mi-fitness', 'action': 'enable'})
        (root / 'mi-fitness.json').write_text(json.dumps({'private_dir': str(self.private), 'worker_python': 'unused', 'chat_summary_memory_allowed': True}))
        worker.sync(self.private, FakeClient({'sleep': [self.sleep()]}), self.now)
        self.assertEqual(context(b, {'scope': 'owner-private'})['mi-fitness']['recent']['sleep'][0]['asleep_min'], 60)
        self.assertEqual(context(b, {'scope': 'qq:group:fixture'}), {})

    def test_handoff_recipient_integrity_expiry_and_allowed_scope(self):
        try:
            handoff = module('mi_fitness_handoff_acceptance', 'handoff.py')
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import rsa
        except ImportError:
            self.skipTest('optional cryptography dependency absent')
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        fp, tid = handoff.fingerprint(key.public_key()), 'a'*32
        session = {'user_id': 'fixture', 'c_user_id': 'fixture', 'service_token': 'synthetic-token',
                   'ssecurity': 'synthetic-secret', 'region': 'cn', 'created_at': 'fixture'}
        envelope = handoff.seal_session(session, public, tid, fp, now=1000)
        self.assertNotIn('synthetic-token', json.dumps(envelope))
        self.assertEqual(handoff.unseal(envelope, private, tid, fp, now=1001), session)
        with self.assertRaises(ValueError):
            handoff.unseal(envelope, private, tid, fp, now=5000)
        changed = dict(envelope, transfer_id='b'*32)
        with self.assertRaises(ValueError):
            handoff.unseal(changed, private, tid, fp, now=1001)
        changed = dict(envelope, ciphertext=envelope['ciphertext'][:-4] + 'AAAA')
        with self.assertRaises(Exception):
            handoff.unseal(changed, private, tid, fp, now=1001)
