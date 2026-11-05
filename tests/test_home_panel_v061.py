"""One final isolated acceptance: real projections, safe assets and delayed publication."""
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from personal_bot import deploy
sys.path.insert(0, str(deploy.RUNTIME))
from brain import Brain
from muse_ext import panel_refresh as refresh
from muse_ext.panel_home import artwork


class HomePanel(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='home-panel-isolated-')
        self.root=Path(self.tmp.name)/'state'
        deploy.init(self.root); deploy.enable(self.root,list(deploy.DEFAULT_FEATURES))
        self.b=Brain(self.root)

    def tearDown(self):
        self.b.close(); self.tmp.cleanup()

    def data(self, path):
        html=Path(path).read_text(encoding='utf-8')
        return html,json.loads(html.split('id="snapshot">')[1].split('</script>')[0])

    def test_complete_catalog_unknown_values_and_nonmutating_safe_profile(self):
        self.b.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)',('owner-private','好奇',.005,'fixture',1000))
        self.b.db.execute('INSERT OR REPLACE INTO ct_label VALUES(?,?,?)',('owner-private','好奇',2))
        self.b.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)',('other-private','生气',.6,'fixture',1000))
        self.b.db.commit()
        profile={'title':'Example </script><script>bad()</script>','voice':{'happy':'fixture greeting'},'token':'must never be exported'}
        (self.root/'panel-profile.json').write_text(json.dumps(profile),encoding='utf-8')
        before=self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0]
        with patch('time.time',return_value=1000):
            result=self.b.dispatch({'op':'companion_panel'})
        html,data=self.data(result['path'])
        self.assertEqual(len(data['mood']['labels']),48)
        values={x['label']:x['intensity'] for x in data['mood']['labels']}
        self.assertEqual(values['好奇'],.005)
        self.assertIsNone(values['生气'])
        self.assertIsNone(values['难过'])
        self.assertEqual(data['panel_profile']['voice']['happy'],'fixture greeting')
        self.assertNotIn('must never be exported',html)
        self.assertNotIn('</script><script>bad()',html)
        self.assertFalse(data['preview'])
        self.assertEqual(before,self.b.db.execute('SELECT count(*) FROM source_events').fetchone()[0])
        self.assertEqual(self.b.db.execute('SELECT at FROM emotion WHERE scope=?',('owner-private',)).fetchone()[0],1000)
        if shutil.which('node'):
            script=re.findall(r'<script>\s*(.*?)</script>',html,re.S)[0]
            source=Path(self.tmp.name)/'panel-check.js'; source.write_text(script,encoding='utf-8')
            subprocess.run(['node','--check',str(source)],check=True,capture_output=True)

    def test_event_offset_native_binding_replay_and_stale_cycle(self):
        target=Path(self.tmp.name)/'library'/'panel.html'
        with patch('time.time',return_value=1000):
            receipt=refresh.record(self.root,'real-host-run-1','host-life-task')
        self.assertEqual(receipt['due_at'],1300)
        with patch('time.time',return_value=1020):
            replay=refresh.record(self.root,'real-host-run-1','host-life-task')
        self.assertTrue(replay['replayed']); self.assertEqual(replay['due_at'],1300)
        refresh.bind(self.root,'real-host-run-1','fixture-native-task')
        with patch('time.time',return_value=1299):
            self.assertTrue(refresh.publish(self.root,target,'real-host-run-1')['waiting'])
        self.assertFalse(target.exists())
        with patch('time.time',return_value=1300):
            result=refresh.publish(self.root,target,'real-host-run-1')
        self.assertTrue(result['ok']); self.assertEqual(result['notifications'],0)
        self.assertEqual(refresh.bind(self.root,'real-host-run-1','fixture-native-task')['status'],'published')
        original=target.read_bytes()
        with patch('time.time',return_value=1400):
            self.assertTrue(refresh.publish(self.root,target,'real-host-run-1')['replayed'])
        self.assertEqual(original,target.read_bytes())
        with patch('time.time',return_value=1800): refresh.record(self.root,'real-host-run-2','host-life-task')
        self.assertEqual(refresh.publish(self.root,target,'real-host-run-1')['skipped'],'stale_or_missing_cycle')

    def test_private_asset_paths_and_unrelated_files_are_protected(self):
        folder=self.root/'assets'/'panel'; folder.mkdir(parents=True)
        (folder/'manifest.json').write_text(json.dumps({'items':{'happy':{'file':'../outside.gif'}}}),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'outside_root'): artwork(self.root)
        unrelated=Path(self.tmp.name)/'unrelated.html'; unrelated.write_text('unrelated original',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'unrelated_html'): refresh.publish(self.root,unrelated,manual=True)
        self.assertEqual(unrelated.read_text(encoding='utf-8'),'unrelated original')


if __name__=='__main__': unittest.main()
