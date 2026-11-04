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
        run([sys.executable,'-m','pip','wheel','--no-deps','--wheel-dir',wheels,ROOT],work,env)
        venv.EnvBuilder(with_pip=True).create(work/'venv')
        py=work/'venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        wheel=next(wheels.glob('personal_ai_companion_kit-*.whl'))
        run([py,'-m','pip','install','--no-deps',wheel],work,env)
        run([py,'-c','from pathlib import Path; import personal_bot,sys; assert Path(personal_bot.__file__).is_relative_to(Path(sys.prefix)); print("installed package origin verified")'],work,env)
        run([py,'-m','personal_bot','self-test'],work,env)
        state=work/'state with spaces'
        run([py,'-m','personal_bot','--root',state,'init'],work,env)
        run([py,'-m','personal_bot','--root',state,'enable'],work,env)
        run([py,'-m','personal_bot','--root',state,'doctor'],work,env)
        request_file=work/'panel-request.json'
        request_file.write_text(json.dumps({'op':'companion_panel','scope':'owner-private'}),encoding='utf-8')
        run([py,'-m','personal_bot','--root',state,'request','--file',request_file],work,env)
        if not (state/'exports/Companion面板.html').is_file():raise RuntimeError('installed HTML template missing')
    print('Wheel accepted outside checkout; synthetic state cleaned.')

if __name__=='__main__':main()
