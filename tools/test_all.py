"""Run independent exchange, full runtime and optional Node suites."""
import os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'personal_bot/runtime'
NAMES=['test_brain','test_concurrency','test_ops','test_proactive','test_news_dispatch','test_heartbeat_digest',
       'test_events','test_model_emotion','test_temporal','test_reminders','test_retrieval','test_consolidation','test_reading','test_sharing','test_full_backup']

def run(args,cwd,env):
    p=subprocess.run(args,cwd=cwd,env=env)
    if p.returncode:raise SystemExit(p.returncode)

def main():
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONPATH']=str(ROOT)
    run([sys.executable,'-m','unittest','discover','-s','tests','-v'],ROOT,env)
    env['PYTHONPATH']=str(RUNTIME)
    run([sys.executable,str(RUNTIME/'tests/run_baseline.py'),*NAMES],RUNTIME,env)
    if shutil.which('node'):
        run(['node','--test','tests/qq-adapter.test.mjs','tests/learn.test.mjs','tests/sticker-turn.test.mjs'],RUNTIME,env)
    else:print('SKIP Node adapter tests: node is not installed',flush=True)
    print('All available suites passed.',flush=True)

if __name__=='__main__':main()
