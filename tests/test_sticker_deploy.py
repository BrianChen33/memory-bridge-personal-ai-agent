"""Exercise the public CLI and full restore with a private synthetic asset."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from personal_bot import deploy


class StickerDeploymentTests(unittest.TestCase):
    def test_new_install_stickers_stay_disabled_and_reinit_preserves_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'private'
            deploy.init(root)
            self.assertFalse(json.loads((root/'sticker-policy.json').read_text())['enabled'])
            deploy.write_json(root/'sticker-catalog.json',dict(version=1,items=[dict(id='preserve')]))
            deploy.init(root)
            self.assertEqual(json.loads((root/'sticker-catalog.json').read_text())['items'][0]['id'],'preserve')

    def test_cli_full_backup_restores_decision_asset_and_disabled_master(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)/'private'
            deploy.init(root);deploy.enable(root,deploy.DEFAULT_FEATURES)
            deploy.write_json(root/'sticker-policy.json',dict(version=1,enabled=True,
                              base_probability=.4,max_probability=1.,share_owner_mood=False))
            event = dict(scope='owner-private',source='fixture:isolated-dot',event_id='one',actor='user')
            q = dict(event,op='prepare',text='请发图',occurred_at=1700000000,
                     emotion_assessment=dict(version=1,changed=False,label=None,
                                             delta=dict(p=0,a=0,d=0),intensity_delta=0))
            deploy.request(root,q)
            request = dict(event,op='sticker',action='decide',intent=dict(mode='direct',evidence='发图'))
            p = subprocess.run([sys.executable,'-m','personal_bot','--root',str(root),'request'],
                               input=json.dumps(request),capture_output=True,text=True,check=True)
            self.assertTrue(json.loads(p.stdout)['should_send'])
            rel = 'media/stickers/pixel.png';path=root/rel;path.parent.mkdir(parents=True)
            path.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lMsAAAAASUVORK5CYII='))
            item = dict(id='pixel',path=rel,format='png',sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        reviewed=True,license='Synthetic generated fixture',emotion=[],tags=[],use=[])
            deploy.write_json(root/'sticker-catalog.json',dict(version=1,items=[item]))
            registry = json.loads((root/'backup-sources.json').read_text())
            registry['sources'].append(dict(name='project/'+rel,path=str(path),required=True))
            deploy.write_json(root/'backup-sources.json',registry)
            deploy.request(root,dict(event,op='sticker',action='select',sticker_id='pixel'))
            deploy.request(root,dict(event,op='sticker',action='handoff',texts_complete=True,text_receipts=['fixture:text']))
            def cli(*args, at=root):
                result = subprocess.run([sys.executable,'-m','personal_bot','--root',str(at),*args],
                                        capture_output=True,text=True,check=True)
                return json.loads(result.stdout)
            snapshot = cli('backup','--manual')['snapshot']
            cli('verify','--snapshot',snapshot)
            destination=Path(temp)/'restored'
            cli('restore','--snapshot',snapshot,'--destination',str(destination))
            restored=destination/'project'
            cli('relocate',at=restored)
            self.assertFalse(json.loads((restored/'config.json').read_text())['enabled'])
            self.assertEqual((restored/rel).read_bytes(),path.read_bytes())
            db=sqlite3.connect(restored/'data/brain.sqlite')
            try:
                self.assertEqual(db.execute('SELECT delivery FROM sticker_turns').fetchone()[0],'unknown')
                self.assertTrue(json.loads(db.execute('SELECT decision_json FROM sticker_turns').fetchone()[0])['should_send'])
            finally:
                db.close()
