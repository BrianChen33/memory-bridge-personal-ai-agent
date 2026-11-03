import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from brain import Brain
from ops import snapshot, install, rollback


class OpsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state = self.root/'brain'
        self.f = self.root/'existing.txt'
        self.f.write_text('original',encoding='utf-8')

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_twice_and_database_retained(self):
        b = Brain(self.state)
        b.dispatch(dict(op='configure',enabled=True))
        b.close()
        m = snapshot(self.state,[self.f,self.root/'new.txt'])
        install(m,self.f,b'enhanced')
        install(m,self.root/'new.txt',b'index')
        self.assertTrue(rollback(self.state,m)['ok'])
        self.assertEqual(self.f.read_text(),'original')
        self.assertFalse((self.root/'new.txt').exists())
        self.assertTrue((self.state/'data/brain.sqlite').exists())
        self.assertTrue(rollback(self.state,m)['ok'])
        b = Brain(self.state)
        self.assertFalse(b.config()['enabled'])
        b.close()

    def test_foreign_edit_not_overwritten(self):
        m = snapshot(self.state,[self.f])
        install(m,self.f,b'enhanced')
        self.f.write_text('foreign edit')
        r = rollback(self.state,m)
        self.assertFalse(r['ok'])
        self.assertEqual(self.f.read_text(),'foreign edit')
        self.assertTrue(r['conflicts'])

    def test_damaged_backup_never_restored(self):
        m = snapshot(self.state,[self.f])
        install(m,self.f,b'enhanced')
        (m.parent/'0.bin').write_bytes(b'damaged')
        r = rollback(self.state,m)
        self.assertFalse(r['ok'])
        self.assertEqual(self.f.read_text(),'enhanced')

    def test_unlisted_target_rejected(self):
        m = snapshot(self.state,[self.f])
        with self.assertRaises(ValueError):
            install(m,self.root/'unlisted',b'no')

    def test_failed_upgrade_can_still_rollback_previous_install(self):
        m=snapshot(self.state,[self.f])
        install(m,self.f,b'v1')
        with patch('ops.atomic_bytes',side_effect=OSError('simulated write failure')):
            with self.assertRaises(OSError):
                install(m,self.f,b'v2')
        self.assertTrue(rollback(self.state,m)['ok'])
        self.assertEqual(self.f.read_text(),'original')

