import json,subprocess,sys,tempfile,unittest,sqlite3
from pathlib import Path

REPO=Path(__file__).resolve().parents[1]

class DeployTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)/'private state with spaces'
    def tearDown(self):self.temp.cleanup()
    def cli(self,*args,q=None,root=None):
        a=[sys.executable,'-m','personal_bot','--root',str(root or self.root),*args]
        p=subprocess.run(a,cwd=REPO,input=json.dumps(q,ensure_ascii=False) if q is not None else None,capture_output=True,text=True,encoding='utf-8',timeout=15)
        return p,json.loads(p.stdout or '{}')
    def init(self):
        p,r=self.cli('init');self.assertEqual(p.returncode,0,p.stderr);return r
    def test_init_external_root_disabled_and_reinit_preserves_data(self):
        self.init();cfg=self.root/'config.json';data=json.loads(cfg.read_text());self.assertFalse(data['enabled'])
        data['custom']='preserve';cfg.write_text(json.dumps(data))
        self.cli('init');self.assertEqual(json.loads(cfg.read_text())['custom'],'preserve')
        self.assertFalse((self.root/'brain.py').exists())
    def test_refuses_existing_nonowned_directory(self):
        self.root.mkdir();(self.root/'MEMORY.md').write_text('existing bot state')
        p,_=self.cli('init');self.assertNotEqual(p.returncode,0)
        self.assertEqual((self.root/'MEMORY.md').read_text(),'existing bot state')
    def test_schedules_are_disabled_real_commands_and_no_private_paths(self):
        self.init();text=(self.root/'state/scheduler-blueprint.json').read_text(encoding='utf-8');d=json.loads(text)
        self.assertEqual(len(d['tasks']),7)
        meme_tasks=[t for t in d['tasks'] if 'meme' in t['id']]
        self.assertEqual(len(meme_tasks),1)
        self.assertEqual(meme_tasks[0]['schedule'],dict(kind='weekly',weekday='Sunday',at='07:40'))
        self.assertEqual(meme_tasks[0]['timezone'],'Asia/Shanghai')
        self.assertTrue(all(t['enabled'] is False for t in d['tasks']))
        self.assertIn('personal_bot',text);self.assertNotIn('/home/hatch',text)
        self.assertNotIn('179366',text);self.assertTrue(all(t['body'] for t in d['tasks']))
        self.assertIn('disabled',d['native_export_requirements'])
    def test_actual_prepare_and_emotion_and_time(self):
        self.init();self.cli('enable')
        q=dict(op='prepare',scope='owner-private',text='谢谢你，帮了大忙',source='synthetic:isolated',event_id='test-one',occurred_at=100)
        p,r=self.cli('request',q=q);self.assertEqual(p.returncode,0);self.assertEqual(r['event']['status'],'captured')
        self.assertEqual(r['emotion']['status'],'missing');self.assertEqual(r['mood']['p'],0)
        q['emotion_assessment']=dict(version=2,changed=True,label='欣喜',delta=dict(p=.04,a=.02,d=0),intensity_delta=.07)
        p,r=self.cli('request',q=q);self.assertEqual(p.returncode,0);self.assertEqual(r['emotion']['status'],'updated');self.assertGreater(r['mood']['p'],0)
        _,r=self.cli('request',q=dict(op='recall',scope='owner-private',text='',start=99,end=101))
        self.assertEqual(r['events'][0]['event_id'],'test-one')
    def test_full_backup_and_restore_to_different_root(self):
        self.init();self.cli('enable')
        self.cli('request',q=dict(op='remember',scope='owner-private',text='备份验收资料',source='synthetic:isolated',event_id='remember'))
        p,r=self.cli('backup','--manual');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        snapshot=r['snapshot'];self.assertTrue((Path(snapshot)/'project/code/personal_bot/runtime/brain.py').is_file())
        dest=Path(self.temp.name)/'restored'
        p,r=self.cli('restore','--snapshot',snapshot,'--destination',str(dest));self.assertEqual(p.returncode,0)
        p,r=self.cli('status',root=dest/'project');self.assertEqual(p.returncode,0);self.assertEqual(r['integrity'],'ok')
        p,r=self.cli('relocate',root=dest/'project');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertFalse(json.loads((dest/'project/config.json').read_text())['enabled'])
        reg=json.loads((dest/'project/backup-sources.json').read_text())
        self.assertTrue(all(Path(x['path']).exists() for x in reg['sources'] if x.get('required')))
    def test_rollback_pauses_preserves_new_messages_and_needs_native_actions(self):
        self.init();self.cli('enable')
        self.cli('request',q=dict(op='remember',scope='owner-private',text='后写入的消息',source='synthetic:isolated',event_id='later'))
        _,r=self.cli('rollback');self.assertFalse(r['completed']);self.assertTrue(r['local_paused']);self.assertTrue(r['host_actions_required'])
        db=sqlite3.connect(self.root/'data/brain.sqlite')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM memories').fetchone()[0],1);db.close()
    def test_vector_not_enabled_by_default(self):
        self.init();self.cli('enable');_,r=self.cli('status');self.assertFalse(r['config']['features']['vector'])
    def test_self_test_needs_no_live_root(self):
        p=subprocess.run([sys.executable,'-m','personal_bot','self-test'],cwd=REPO,capture_output=True,text=True,encoding='utf-8',timeout=20)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertTrue(json.loads(p.stdout)['ok'])
    def test_model_help_and_due_guard_have_portable_cli(self):
        p=subprocess.run([sys.executable,'-m','personal_bot','model','--help'],cwd=REPO,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        p=subprocess.run([sys.executable,'-m','personal_bot','reminder','--help'],cwd=REPO,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_normal_runtime_refusals_keep_clarification_fields(self):
        self.init();self.cli('enable')
        p,r=self.cli('request',q=dict(op='reminder',action='create',scope='owner-private',text='明天三点提醒我',body='测试提醒',source='fixture:isolated',event_id='ambiguous'))
        self.assertFalse(r['ok']);self.assertTrue(r['needs_clarification']);self.assertEqual(r['reason'],'ambiguous_am_pm')
    def test_existing_persona_is_not_named_after_original_installation(self):
        self.init();self.cli('enable')
        _,r=self.cli('request',q=dict(op='prepare',scope='owner-private',text='hello',source='fixture:test',event_id='style'))
        self.assertNotIn('小鱼',r['style']['guidance'])
    def test_interrupted_init_preserves_existing_config(self):
        from personal_bot.deploy import root_path,write_json,MARKER
        self.root.mkdir();write_json(self.root/MARKER,dict(application='personal-bot-memory',schema=1))
        cfg={'version':'custom','enabled':False,'epoch':4,'modules':{},'features':{},'custom':'keep'}
        write_json(self.root/'config.json',cfg)
        self.init();self.assertEqual(json.loads((self.root/'config.json').read_text()),cfg)

    def test_data_root_cannot_be_inside_program_package(self):
        from personal_bot import deploy
        from unittest.mock import patch
        package=Path(self.temp.name)/'fake-package'
        with patch.object(deploy,'PACKAGE',package),self.assertRaisesRegex(ValueError,'outside_code'):
            deploy.init(package/'data')
    def test_different_bot_roots_get_distinct_scheduler_ids(self):
        from personal_bot.deploy import blueprint
        a=blueprint(self.root);b=blueprint(self.root.parent/'second bot')
        self.assertFalse({x['id'] for x in a['tasks']} & {x['id'] for x in b['tasks']})

    def test_host_path_normalizes_native_aliases_with_missing_suffix(self):
        from personal_bot.deploy import host_path
        parent=Path(self.temp.name).resolve()
        alias=parent/'unused'/'..'/'removed-state'/'snapshots'/'1'/'manifest.json'
        self.assertEqual(host_path(alias),host_path(parent/'removed-state'/'snapshots'/'1'/'manifest.json'))

    @unittest.skipUnless(sys.platform=='win32','Windows short-name paths')
    def test_host_path_expands_windows_short_alias_before_missing_suffix(self):
        import ctypes
        from personal_bot.deploy import host_path
        parent=Path(self.temp.name).resolve()
        buf=ctypes.create_unicode_buffer(32768)
        api=ctypes.windll.kernel32.GetShortPathNameW
        api.argtypes=[ctypes.c_wchar_p,ctypes.c_wchar_p,ctypes.c_uint32]
        api.restype=ctypes.c_uint32
        size=api(str(parent),buf,len(buf))
        self.assertTrue(0<size<len(buf),'GetShortPathNameW failed')
        short=Path(buf.value)
        if str(short).casefold()==str(parent).casefold():self.skipTest('volume has no short-name aliases')
        self.assertEqual(host_path(short/'removed-state'/'snapshots'/'1'/'manifest.json'),
                         host_path(parent/'removed-state'/'snapshots'/'1'/'manifest.json'))
        self.assertEqual(host_path(short/'host-rules.md'),host_path(parent/'host-rules.md'))

    def test_foreign_host_path_stays_lexical(self):
        from pathlib import PurePosixPath,PureWindowsPath
        from personal_bot.deploy import host_path
        value='/srv/former-host/state' if sys.platform=='win32' else r'C:\Users\FormerHost\state'
        expected=PurePosixPath('/srv/former-host/state') if sys.platform=='win32' else PureWindowsPath(r'C:\Users\FormerHost\state')
        self.assertEqual(host_path(value),expected)

    def test_pause_works_without_opening_corrupt_database(self):
        self.init();self.cli('enable')
        db=self.root/'data/brain.sqlite';db.write_bytes(b'corrupt database fixture')
        before=db.read_bytes();old=json.loads((self.root/'config.json').read_text())['epoch']
        p,r=self.cli('rollback');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        cfg=json.loads((self.root/'config.json').read_text());self.assertFalse(cfg['enabled']);self.assertGreater(cfg['epoch'],old)
        self.assertEqual(db.read_bytes(),before);self.assertTrue(r['local_paused'])
    def test_relocated_native_tree_survives_next_full_backup(self):
        self.init();folder=Path(self.temp.name)/'memory';folder.mkdir();(folder/'note.md').write_text('synthetic native note')
        reg=json.loads((self.root/'backup-sources.json').read_text());reg['trees']=[dict(name='native/memory',path=str(folder),required=True)]
        (self.root/'backup-sources.json').write_text(json.dumps(reg))
        _,r=self.cli('backup','--manual');dest=Path(self.temp.name)/'tree-restore'
        self.cli('restore','--snapshot',r['snapshot'],'--destination',str(dest))
        p,r=self.cli('relocate',root=dest/'project');self.assertEqual(p.returncode,0,p.stdout)
        _,second=self.cli('backup','--manual',root=dest/'project')
        self.assertEqual((Path(second['snapshot'])/'native/memory/note.md').read_text(),'synthetic native note')
    def test_host_rollback_originals_recover_without_original_state(self):
        from personal_bot import deploy
        import shutil
        self.init();target=Path(self.temp.name)/'host-rules.md';target.write_text('original host rules')
        script='from ops import snapshot,install; import sys,json; m=snapshot(sys.argv[1],[sys.argv[2]]);install(m,sys.argv[2],b"installed rules");print(json.dumps({"manifest":str(m)}))'
        proc=subprocess.run([sys.executable,'-c',script,str(self.root),str(target)],cwd=deploy.RUNTIME,env=deploy.runtime_env(),capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr);manifest=json.loads(proc.stdout)['manifest']
        state=json.loads((self.root/'state/deployment.json').read_text());state['host_manifests']=[manifest]
        (self.root/'state/deployment.json').write_text(json.dumps(state))
        reg=json.loads((self.root/'backup-sources.json').read_text());reg['sources'].append(dict(name='native/host-rules.md',path=str(target),required=True))
        (self.root/'backup-sources.json').write_text(json.dumps(reg))
        p,r=self.cli('backup','--manual');self.assertEqual(p.returncode,0,p.stdout)
        snapshot=Path(r['snapshot']);rel=Path(manifest).relative_to(self.root)
        self.assertTrue((snapshot/'project'/rel).is_file(),'full backup omitted installation manifest')
        dest=Path(self.temp.name)/'host-restore';self.cli('restore','--snapshot',str(snapshot),'--destination',str(dest))
        assert self.root.resolve().is_relative_to(Path(self.temp.name).resolve()) and (self.root/'.personal-bot.json').is_file()
        shutil.rmtree(self.root)  # Verified owned temporary test root only.
        target.write_text('current external file must stay untouched')
        p,r=self.cli('relocate',root=dest/'project');self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        rebound=json.loads((dest/'project/state/deployment.json').read_text())['host_manifests'][0]
        fixed=json.loads(Path(rebound).read_text())
        self.assertEqual(Path(fixed['entries'][0]['path']).resolve(),(dest/'native/host-rules.md').resolve())
        script='from ops import rollback; import sys,json; print(json.dumps(rollback(sys.argv[1],sys.argv[2])))'
        proc=subprocess.run([sys.executable,'-c',script,str(dest/'project'),rebound],cwd=deploy.RUNTIME,env=deploy.runtime_env(),capture_output=True,text=True)
        self.assertTrue(json.loads(proc.stdout)['ok'],proc.stdout+proc.stderr)
        self.assertEqual((dest/'native/host-rules.md').read_text(),'original host rules')
        self.assertEqual(target.read_text(),'current external file must stay untouched')
