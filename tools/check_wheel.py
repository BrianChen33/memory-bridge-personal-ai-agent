"""Build/install a wheel and exercise it with no checkout on the import path."""
import json,os,subprocess,sys,tempfile,venv
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def run(argv,cwd,env):
    p=subprocess.run(list(map(str,argv)),cwd=cwd,env=env,check=True)

def main():
    env=os.environ.copy();env.pop('PYTHONPATH',None);env['PYTHONUTF8']='1'
    with tempfile.TemporaryDirectory(prefix='personal-memory-wheel-') as temp:
        work=Path(temp).resolve();wheels=work/'wheels';wheels.mkdir()
        build_flags=['--no-build-isolation'] if '--no-build-isolation' in sys.argv else []
        run([sys.executable,'-m','pip','wheel','--no-deps',*build_flags,'--wheel-dir',wheels,ROOT],work,env)
        venv.EnvBuilder(with_pip=True).create(work/'venv')
        py=work/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        wheel=next(wheels.glob('memory_bridge_muse_dot-*.whl'))
        run([py,'-m','pip','install','--no-deps',wheel],work,env)
        run([py,'-c','from pathlib import Path; import personal_bot,sys; assert Path(personal_bot.__file__).is_relative_to(Path(sys.prefix)); print("installed package origin verified")'],work,env)
        run([py,'-m','personal_bot','self-test'],work,env)
        state=work/'state with spaces'
        run([py,'-m','personal_bot','--root',state,'init'],work,env)
        run([py,'-m','personal_bot','--root',state,'enable'],work,env)
        run([py,'-m','personal_bot','--root',state,'doctor'],work,env)
        script='''
import json,sys
from pathlib import Path
from personal_bot import deploy
root=Path(sys.argv[1])
assert json.loads((root/'sticker-policy.json').read_text())['enabled'] is False
policy=json.loads((root/'sticker-policy.json').read_text());policy['enabled']=True
deploy.write_json(root/'sticker-policy.json',policy)
event=dict(scope='owner-private',source='fixture:wheel-isolated',event_id='one',actor='user')
q=dict(event,op='prepare',text='发图',occurred_at=1700000000,emotion_assessment=dict(version=1,changed=False,label=None,delta=dict(p=0,a=0,d=0),intensity_delta=0))
assert deploy.request(root,q)['emotion']['status']=='unchanged'
decision=deploy.request(root,dict(event,op='sticker',action='decide',intent=dict(mode='direct',evidence='发图')))
assert decision['should_send'] is True and decision['u'] is None
assert deploy.request(root,dict(event,op='sticker',action='status'))['replayed'] is False
print('Installed wheel sticker lifecycle verified; no media sent')
'''
        run([py,'-c',script,state],work,env)
    print('Wheel accepted outside checkout; synthetic state cleaned.')

if __name__=='__main__':main()
