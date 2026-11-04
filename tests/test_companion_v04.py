"""One final isolated companion/vault acceptance; no network or live messages."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import MagicMock

from personal_bot import deploy, vault

sys.path.insert(0,str(deploy.RUNTIME))
from brain import Brain
from muse_ext import companion as c


class CompanionV04(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='companion-v04-isolated-')
        self.base=Path(self.temp.name);self.root=self.base/'state'
        deploy.init(self.root);deploy.enable(self.root,list(deploy.DEFAULT_FEATURES));self.b=Brain(self.root)

    def tearDown(self):
        self.b.close();self.temp.cleanup()

    def event(self,event='one',**extra):
        q=dict(op='prepare',scope='owner-private',source='fixture:isolated',event_id=event,
               actor='user',person_id='owner',text='你今天做得很好')
        q.update(extra);return self.b.dispatch(q)

    def appraisal(self):
        return dict(version=2,changed=True,label='得意',delta=dict(p=.2,a=.1,d=.05),intensity_delta=.3,
                    emotions=[dict(label='满足',delta=.15)],relationship=dict(contact_delta=10),
                    expectations=dict(create=[dict(kind='praise',summary='想分享完成的成果',strength=.6)],resolve=[]))

    def test_model_v2_idempotency_and_scoped_context(self):
        a=self.appraisal();r=self.event(emotion_assessment=a)
        self.assertEqual(r['emotion']['status'],'updated');self.assertGreater(r['companion']['contact_desire'],44)
        self.assertEqual(self.event(emotion_assessment=a)['emotion']['status'],'replayed')
        g=self.event('group',scope='qq:group:isolated',person_id='qq:fixture',emotion_assessment=a)
        self.assertEqual(g['companion']['pending_expectations'],[]);self.assertIsNone(g['companion']['activity'])

    def test_life_event_is_model_appraised_and_future_outcome_hidden(self):
        from datetime import datetime
        noon=datetime(2026,11,5,12,tzinfo=c.TZ).timestamp()
        with patch.object(c,'stamp',return_value=noon):
            c._set(self.b,'life',dict(activity=None,next_at=0));self.b.db.commit()
            tick=self.b.dispatch(dict(op='companion_tick'));self.assertTrue(tick['created'])
            ctx=self.b.dispatch(dict(op='companion_context'))['companion']
            self.assertNotIn('outcome',ctx['activity']);self.assertNotIn('cost',ctx['activity'])
            row=self.b.dispatch(dict(op='companion_pending',claim=True))['events'][0]
            result=self.b.dispatch(dict(op='companion_life_assess',id=row['id'],assessment=self.appraisal()))
            self.assertEqual(result['emotion']['status'],'updated')

    def test_expression_direct_once_and_shared_recent_avoidance(self):
        deploy.write_json(self.root/'expression-policy.json',dict(enabled=True,base_probability=.4,maximum_probability=.9,recent_seconds=3600,candidate_limit=10))
        first=self.event(emotion_assessment=self.appraisal())
        q=dict(op='expression',scope='owner-private',source_event=first['event']['id'],intent='direct',assets=[dict(id='asset-a')])
        one=self.b.dispatch(q);self.assertTrue(one['hit']);self.assertEqual(one['asset'],'asset-a')
        self.assertTrue(self.b.dispatch(q)['replayed'])
        self.b.dispatch(dict(q,action='finish',text_finished=True,outcome='accepted'))
        second=self.event('two',emotion_assessment=self.appraisal())
        other=dict(q,source_event=second['event']['id'])
        missing=self.b.dispatch(other);self.assertTrue(missing['hit']);self.assertEqual(missing['status'],'asset_required')
        selected=self.b.dispatch(dict(other,assets=[dict(id='asset-b')]))
        self.assertEqual(selected['asset'],'asset-b');self.assertEqual(selected['roll'],missing['roll'])

    def test_source_change_hides_old_summary_and_cache(self):
        mid=self.b._remember(dict(scope='owner-private',text='某位朋友喜欢青柠茶',source='fixture:isolated',event_id='fact',kind='fact',evidence='observed'));self.b.db.commit()
        q=dict(op='recall',scope='owner-private',text='青柠茶');self.b.dispatch(q)
        self.assertEqual(self.b.dispatch(q)['cache'],'hit')
        self.b.dispatch(dict(op='companion_summary_commit',target_scope='owner-private',origin='real',level=2,key='drink',content='某位朋友喜欢青柠茶',source_ids=[mid]))
        self.b.db.execute("UPDATE memories SET status='forgotten' WHERE id=?",(mid,));self.b.db.commit()
        self.assertEqual(self.b.dispatch(q)['cache'],'miss')
        from muse_ext.companion_io import summaries
        self.assertEqual(summaries(self.b,q)['scene_context'],[])

    def test_native_vault_consistency_dedup_and_daily_gate(self):
        person=self.base/'person.md';person.write_text('# 合成人物\n仅测试资料',encoding='utf-8')
        deploy.write_json(self.root/'backup-sources.json',dict(sources=[dict(name='native/person.md',path=str(person)),dict(name='native/same.md',path=str(person))],trees=[]))
        with self.assertRaisesRegex(ValueError,'daily_summary_not_completed'):
            vault.export_snapshot(self.root,self.base/'daily','a'*40,day='2026-11-05')
        out=self.base/'snapshot';m=vault.export_snapshot(self.root,out,'a'*40,bootstrap=True)
        from personal_bot import __version__
        self.assertEqual(m['architecture']['version'],__version__)
        self.assertEqual(m['aliases']['native/same.md'],'native/person.md')
        self.assertEqual((out/'native/person.md').read_bytes(),person.read_bytes())
        with closing(sqlite3.connect(out/'brain.sqlite')) as db:self.assertEqual(db.execute('PRAGMA quick_check').fetchone()[0],'ok')
        self.assertFalse(any('code/' in x['path'] for x in m['files']))

    def test_emotion48_schema_alias_and_retired_request(self):
        from muse_ext.emotion_catalog import LABELS,DEFINITIONS,normalize
        schema=self.b.dispatch(dict(op='companion_schema'))
        self.assertEqual(len(schema['labels']),48);self.assertEqual(set(LABELS),set(DEFINITIONS))
        old=self.appraisal();old['version']=1
        rejected=self.event('retired',emotion_assessment=old)
        self.assertEqual(rejected['emotion']['status'],'invalid')
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0],0)
        a=self.appraisal();a['label']='愧疚';a['appraisal']=dict(kind='feedback',target='self',agency='self',certainty=.8,feeling='这次漏做了，想先修好',action='repair')
        accepted=self.event('retired',emotion_assessment=a)
        self.assertEqual(accepted['reaction']['emotions'][0]['label'],'内疚')
        a['label']='内疚';self.assertEqual(self.event('retired',emotion_assessment=a)['emotion']['status'],'replayed')
        for label in LABELS:
            with self.subTest(label=label):
                sample=dict(version=2,changed=True,label=label,delta=dict(p=0,a=.01,d=0),intensity_delta=.01)
                c._validate(normalize(sample))

    def test_current_reaction_does_not_erase_background_or_cross_scope(self):
        self.event('happy',emotion_assessment=self.appraisal())
        a=self.appraisal();a.update(label='内疚',emotions=[dict(label='懊恼',delta=.1)],appraisal=dict(kind='feedback',target='self',agency='self',certainty=.8,action='repair'))
        result=self.event('feedback',emotion_assessment=a)
        self.assertEqual(result['reaction']['appraisal']['action'],'repair')
        self.assertEqual(result['reaction']['emotions'][0]['label'],'内疚')
        self.assertIn('得意',[x['label'] for x in result['mood']['labels']])
        group=self.event('group-focus',scope='qq:group:isolated',person_id='qq:fixture')
        self.assertIsNone(group['reaction']);self.assertEqual(group['companion']['pending_expectations'],[])

    def test_missing_assessment_still_records_one_honest_draw(self):
        from muse_ext import expression
        deploy.write_json(self.root/'expression-policy.json',dict(enabled=True,base_probability=.4,maximum_probability=.9,recent_seconds=3600,candidate_limit=10))
        event=self.event('pending')
        q=dict(op='expression',scope='owner-private',source_event=event['event']['id'],intent='auto',assets=[dict(id='fixture')])
        with patch.object(expression,'RNG') as random:
            random.random.return_value=.2;random.choice.side_effect=lambda x:x[0]
            first=self.b.dispatch(q);again=self.b.dispatch(q)
            self.assertTrue(first['hit']);self.assertEqual(first['assessment_status'],'degraded_missing_assessment')
            self.assertEqual(again['roll'],first['roll']);random.random.assert_called_once()
        self.assertEqual(self.b.db.execute('SELECT count(*) FROM ct_appraisal').fetchone()[0],0)

    def test_invalid_appraisal_metadata_keeps_opportunity(self):
        a=self.appraisal();a['appraisal']=dict(certainty=True)
        self.assertEqual(self.event('bad-meta',emotion_assessment=a)['emotion']['status'],'invalid')
        a['appraisal']=dict(certainty=.6)
        self.assertEqual(self.event('bad-meta',emotion_assessment=a)['emotion']['status'],'updated')

    def test_current_only_host_entry_does_not_retain_old_validator(self):
        from muse_ext import emotion_current
        self.assertEqual(emotion_current.ASSESSMENT_VERSION,2);self.assertEqual(len(emotion_current.LABELS),48)
        event=self.event('current-entry')['event']['id']
        self.assertEqual(emotion_current.submit_assessment(self.b,event,self.appraisal())['status'],'updated')
        old=self.appraisal();old['version']=1
        self.assertEqual(emotion_current.submit_assessment(self.b,event,old)['status'],'invalid')

    def test_vault_refuses_public_repo_secrets_and_live_destination(self):
        with patch.object(vault,'github_json',return_value={'private':False}),self.assertRaisesRegex(ValueError,'public_repository'):
            vault.privacy_check('fixture/repo')
        secret=self.base/'native.md';secret.write_text('ghp_'+'X'*35,encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'credential_content'):
            vault.scan_file(secret)
        with self.assertRaisesRegex(ValueError,'outside_live_state'):
            vault.export_snapshot(self.root,self.root/'exports','a'*40,bootstrap=True)

    def test_ssh443_proxy_env_auth_and_refusal(self):
        connection=MagicMock()
        header=b'HTTP/1.1 200 Connection established\r\n\r\n'
        connection.recv.side_effect=[bytes([x]) for x in header]
        with patch.object(vault.socket,'create_connection',return_value=connection) as dial:
            self.assertIs(vault.proxy_tunnel('http://fixture-user:fixture-pass@proxy.invalid:3128'),connection)
        dial.assert_called_once_with(('proxy.invalid',3128),timeout=20)
        sent=connection.sendall.call_args.args[0]
        self.assertIn(b'CONNECT ssh.github.com:443 HTTP/1.1',sent)
        self.assertIn(b'Proxy-Authorization: Basic ',sent)
        denied=b'HTTP/1.1 407 Proxy Authentication Required\r\n\r\n'
        connection.recv.side_effect=[bytes([x]) for x in denied]
        with patch.object(vault.socket,'create_connection',return_value=connection),self.assertRaisesRegex(ValueError,'proxy_CONNECT_refused'):
            vault.proxy_tunnel('http://proxy.invalid:3128')
        connection.close.assert_called_once()

    def test_vault_push_receipt_is_idempotent_with_mock_transport(self):
        key=self.base/'repo-key';key.write_text('synthetic-key-only');os.chmod(key,0o600)
        work=self.base/'private-checkout';url='git@github.com:fixture/private-vault.git'
        state={'remote':'0'*40,'commits':0}
        def fake(args,cwd=None,env=None,timeout=90,check=True):
            output='';status=0
            if args[0]=='clone':work.mkdir();(work/'.git').mkdir()
            elif args[:2]==['remote','get-url']:output=url+'\n'
            elif 'commit' in args:state['commits']+=1
            elif args[0]=='rev-parse':output='b'*40+'\n'
            elif args[0]=='push':state['remote']='b'*40
            elif args[0]=='ls-remote':output=state['remote']+'\trefs/heads/main\n'
            elif args[0]=='merge-base':status=0 if args[2]==state['remote'] else 1
            return subprocess.CompletedProcess(args,status,output,'')
        with patch.object(vault,'git',side_effect=fake),patch.object(vault,'privacy_check'),patch.object(vault,'github_json',return_value={'ssh_keys':['ssh-ed25519 synthetic-host-key']}):
            first=vault.publish(self.root,work,'fixture/private-vault',key,'a'*40,bootstrap=True)
            second=vault.publish(self.root,work,'fixture/private-vault',key,'a'*40,bootstrap=True)
            upgrade=vault.publish(self.root,work,'fixture/private-vault',key,'c'*40,bootstrap=True)
        self.assertTrue(first['ok']);self.assertTrue(second['already_uploaded']);self.assertEqual(state['commits'],2)
        self.assertFalse(upgrade['already_uploaded'])
        self.assertEqual(json.loads((work/'current/manifest.json').read_text(encoding='utf-8'))['architecture']['commit'],'c'*40)


if __name__=='__main__':unittest.main()
