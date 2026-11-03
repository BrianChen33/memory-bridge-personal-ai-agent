import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from brain import Brain
from muse_ext.backup import create_snapshot, restore_snapshot, verify_snapshot


class FullBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.root = self.base/'project'
        self.b = Brain(self.root)
        self.b.dispatch({'op': 'configure', 'enabled': True})
        self.b.dispatch({'op': 'remember', 'scope': 'owner-private',
                         'text': '合成测试：保存蓝鲸笔记', 'kind': 'fact',
                         'source': 'fixture:user', 'event_id': 'one'})
        self.b.dispatch({'op': 'mood', 'scope': 'owner-private',
                         'delta': {'p': .1}, 'label': '高兴', 'reason': '合成测试'})
        (self.root/'state').mkdir()
        (self.root/'state'/'reading.json').write_text('{"offset":42}')
        self.native = self.base/'native-memory.md'
        self.native.write_text('合成原生记忆，仅供恢复验收', encoding='utf-8')
        self.sources = [
            {'path': str(self.root/'config.json'), 'name': 'project/config.json', 'required': True},
            {'path': str(self.root/'state'/'reading.json'), 'name': 'project/state/reading.json', 'required': True},
            {'path': str(self.native), 'name': 'native/MEMORY.md', 'required': True},
        ]

    def tearDown(self):
        self.b.close()
        self.tmp.cleanup()

    def snapshot(self, **kw):
        return create_snapshot(self.root, self.sources, **kw)

    def test_roundtrip_includes_database_emotion_config_and_cursor(self):
        r = self.snapshot()
        self.assertTrue(r['ok'])
        dest = self.base/'restored'
        restore_snapshot(r['snapshot'], dest)
        db = sqlite3.connect(dest/'project'/'data'/'brain.sqlite')
        try:
            self.assertEqual(db.execute('select text from memories').fetchone()[0], '合成测试：保存蓝鲸笔记')
            self.assertEqual(db.execute('select p from mood').fetchone()[0], .1)
            self.assertEqual(db.execute('select label from emotion').fetchone()[0], '高兴')
        finally:
            db.close()
        self.assertTrue(json.loads((dest/'project'/'config.json').read_text())['enabled'])
        self.assertEqual(json.loads((dest/'project'/'state'/'reading.json').read_text())['offset'], 42)
        self.assertEqual((dest/'native'/'MEMORY.md').read_text(encoding='utf-8'), self.native.read_text(encoding='utf-8'))

    def test_restore_uses_snapshot_not_modified_live_files(self):
        r = self.snapshot()
        self.native.write_text('后来变化', encoding='utf-8')
        (self.root/'state'/'reading.json').write_text('{"offset":999}')
        dest = self.base/'restored'
        restore_snapshot(r['snapshot'], dest)
        self.assertEqual(json.loads((dest/'project'/'state'/'reading.json').read_text())['offset'], 42)
        self.assertNotEqual((dest/'native'/'MEMORY.md').read_text(encoding='utf-8'), self.native.read_text(encoding='utf-8'))

    def test_seven_daily_slots_manual_does_not_evict_daily(self):
        bj = timezone(timedelta(hours=8))
        d0 = datetime(2026, 11, 1, 4, 10, tzinfo=bj)
        daily = [self.snapshot(now=d0+timedelta(days=n)) for n in range(8)]
        manual = self.snapshot(daily=False, now=d0+timedelta(days=8))
        index = json.loads((self.root/'backups'/'full'/'index.json').read_text())
        self.assertEqual(len(index['daily']), 7)
        self.assertNotIn('2026-11-01', index['daily'])
        self.assertTrue(Path(manual['snapshot']).is_dir())
        self.assertFalse(Path(daily[0]['snapshot']).exists())
        self.assertTrue(all(Path(r['snapshot']).exists() for r in daily[1:]))

    def test_same_day_reuses_verified_daily_snapshot(self):
        a = self.snapshot()
        b = self.snapshot()
        self.assertEqual(a['snapshot'], b['snapshot'])
        self.assertTrue(b['reused'])

    def test_corruption_refuses_before_restore_writes(self):
        r = self.snapshot()
        (Path(r['snapshot'])/'project'/'config.json').write_text('corrupt')
        dest = self.base/'restore'
        with self.assertRaisesRegex(ValueError, 'hash'):
            restore_snapshot(r['snapshot'], dest)
        self.assertFalse(dest.exists())

    def test_manifest_path_traversal_is_refused(self):
        r = self.snapshot()
        mpath = Path(r['snapshot'])/'manifest.json'
        m = json.loads(mpath.read_text())
        m['files']['../../outside.txt'] = {'sha256': hashlib.sha256(b'x').hexdigest(), 'size': 1}
        mpath.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'path'):
            verify_snapshot(r['snapshot'])
        self.assertFalse((self.base/'outside.txt').exists())

    def test_missing_required_file_never_publishes_success(self):
        bad = self.sources + [{'path': str(self.base/'missing'), 'name': 'native/MISSING.md', 'required': True}]
        with self.assertRaisesRegex(ValueError, 'required'):
            create_snapshot(self.root, bad)
        self.assertFalse((self.root/'backups'/'full'/'index.json').exists())

    def test_credentials_and_live_restore_target_refused(self):
        secret = self.base/'.env'
        secret.write_text('SYNTHETIC_SECRET=never_copy')
        with self.assertRaisesRegex(ValueError, 'credential'):
            create_snapshot(self.root, self.sources+[{'path': str(secret), 'name': 'project/.env'}])
        r = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'empty'):
            restore_snapshot(r['snapshot'], self.root)

    def test_optional_missing_source_is_explicit(self):
        sources = self.sources + [{'path': str(self.base/'optional.md'), 'name': 'native/OPTIONAL.md'}]
        r = create_snapshot(self.root, sources)
        self.assertIn('native/OPTIONAL.md', r['missing_optional'])

    def test_cross_file_change_during_capture_refuses_publication(self):
        import shutil
        original_copy = shutil.copyfile

        def copy_and_mutate(src, dst, *a, **kw):
            result = original_copy(src, dst, *a, **kw)
            if Path(src).name == 'reading.json':
                self.native.write_text('备份过程中发生变化', encoding='utf-8')
            return result

        with mock.patch('muse_ext.backup.shutil.copyfile', copy_and_mutate):
            with self.assertRaisesRegex(ValueError, 'changed'):
                self.snapshot()
        self.assertFalse((self.root/'backups'/'full'/'index.json').exists())

    def test_source_symlink_is_never_followed(self):
        link = self.base/'linked.md'
        try:
            link.symlink_to(self.native)
        except OSError:
            self.skipTest('host cannot create test symlinks')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            create_snapshot(self.root, [{'path': str(link), 'name': 'native/LINK.md'}])

    def test_registered_memory_tree_includes_new_files(self):
        memory = self.base/'memory'
        memory.mkdir()
        (memory/'new-note.md').write_text('新产生的合成笔记', encoding='utf-8')
        registry = {'version': 1, 'sources': [], 'trees': [
            {'path': str(memory), 'name': 'native/memory', 'required': True},
        ]}
        (self.root/'backup-sources.json').write_text(json.dumps(registry))
        r = create_snapshot(self.root)
        m = verify_snapshot(r['snapshot'])
        self.assertIn('native/memory/new-note.md', m['files'])

    def test_home_directory_cannot_be_registered_as_memory_tree(self):
        registry = {'version': 1, 'sources': [], 'trees': [
            {'path': str(self.base), 'name': 'native/memory'},
        ]}
        (self.root/'backup-sources.json').write_text(json.dumps(registry))
        with self.assertRaisesRegex(ValueError, 'tree'):
            create_snapshot(self.root)


if __name__ == '__main__':
    unittest.main()
