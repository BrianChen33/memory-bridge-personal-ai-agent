"""Native-format private GitHub memory snapshots. stdlib + git + OpenSSH.

May also be copied to a host and executed as a standalone script. Credentials
are NEVER read, serialized, committed, printed, or transported by this module.
"""
import argparse
import base64
from contextlib import closing
import hashlib
import json
import os
import re
import shutil
import shlex
import socket
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlsplit

SCHEMA='companion-memory-vault-v1'
SECRET=re.compile(rb'-----BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY-----|github_pat_[A-Za-z0-9_]{30,}|gh[pousr]_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,}')
BLOCKED={'.git','.ssh','credentials','secrets','vault','node_modules','__pycache__'}


def json_text(data): return json.dumps(data,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'


def write_json(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name('.'+path.name+'.tmp')
    temp.write_text(json_text(data),encoding='utf-8'); os.chmod(temp,0o600); temp.replace(path)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def safe_source(path):
    p=Path(path).expanduser().absolute()
    if any(x.is_symlink() for x in (p,*p.parents)): raise ValueError('symlink_source_refused')
    if any(x.lower() in BLOCKED or x.lower().startswith('.env') for x in p.parts): raise ValueError('credential_path_refused')
    return p


def safe_name(name):
    p=PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name or '\n' in name or '\r' in name:
        raise ValueError('unsafe_export_name')
    if any(x.lower() in BLOCKED or x.lower().startswith('.env') for x in p.parts): raise ValueError('credential_path_refused')
    return p.as_posix()


def scan_file(path):
    if path.stat().st_size>95*1024*1024: raise ValueError('file_exceeds_95MiB_native_git_limit')
    overlap=b''
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):
            if SECRET.search(overlap+block): raise ValueError('credential_content_refused:'+path.name)
            overlap=block[-256:]
    if path.suffix=='.json':
        try: obj=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,UnicodeError): return
        def check(v):
            if isinstance(v,dict):
                for k,x in v.items():
                    if re.search(r'(^|_)(token|password|secret|api_key|private_key|authorization)$',str(k),re.I) and x not in (None,'',False):
                        raise ValueError('credential_json_refused:'+path.name)
                    check(x)
            elif isinstance(v,list):
                for x in v: check(x)
        check(obj)


def summary_proof(root,day,bootstrap=False):
    if bootstrap: return {'kind':'bootstrap','day':datetime.now(timezone(timedelta(hours=8))).date().isoformat()}
    if not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): raise ValueError('daily_summary_day_required')
    uri=(root/'data/brain.sqlite').resolve().as_uri()+'?mode=ro'
    with closing(sqlite3.connect(uri,uri=True)) as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE name='ct_kv'").fetchone()
        row=db.execute('SELECT value FROM ct_kv WHERE key=?',('daily_summary:'+day,)).fetchone() if exists else None
    if not row: raise ValueError('daily_summary_not_completed')
    return {'kind':'daily','day':day,'completed_summary':json.loads(row[0])}


def export_snapshot(root,destination,architecture_ref,day=None,bootstrap=False,identity_file=None,architecture_repo='https://github.com/BrianChen33/personal-ai-companion-kit'):
    root=safe_source(root).resolve(); dest=Path(destination).resolve()
    if not re.fullmatch(r'[0-9a-f]{40}',architecture_ref): raise ValueError('exact_architecture_commit_required')
    if not re.fullmatch(r'https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',architecture_repo): raise ValueError('invalid_architecture_repository')
    if dest==root or root.is_relative_to(dest) or dest.is_relative_to(root): raise ValueError('export_must_be_outside_live_state')
    proof=summary_proof(root,day,bootstrap)
    registry=root/'backup-sources.json'
    catalog=json.loads(registry.read_text(encoding='utf-8')) if registry.is_file() else {'sources':[],'trees':[]}
    selected={}
    for entry in catalog.get('sources',[]):
        name=safe_name(entry['name'])
        if not name.startswith(('native/','scheduler/')): continue
        path=safe_source(entry['path'])
        if not path.is_file():
            if entry.get('required'): raise ValueError('required_source_missing:'+name)
            continue
        selected[name]=path
    for tree in catalog.get('trees',[]):
        folder=safe_source(tree['path'])
        if folder.name not in ('memory','companion','definitions','library'): raise ValueError('tree_not_allowlisted')
        if not folder.is_dir():
            if tree.get('required'): raise ValueError('required_tree_missing')
            continue
        for p in sorted(folder.rglob('*')):
            if p.is_file() and p.suffix.lower() in ('.md','.json','.jsonl','.txt'):
                selected[safe_name(tree['name']+'/'+p.relative_to(folder).as_posix())]=safe_source(p)
    for name in ('config.json','proactive-policy.json','interests.json','reading-sources.json','expression-policy.json','plugins.json'):
        if (root/name).is_file(): selected['configuration/'+name]=safe_source(root/name)
    for name in ('native-schedules.json','host-bindings.json'):
        if (root/'state'/name).is_file(): selected['operations/'+name]=safe_source(root/'state'/name)
    if identity_file: selected['operations/channel-identities.json']=safe_source(identity_file)
    dest.mkdir(parents=True,exist_ok=True)
    marker=dest/'manifest.json'
    old=json.loads(marker.read_text(encoding='utf-8')) if marker.is_file() else None
    if any(dest.iterdir()) and (not old or old.get('schema')!=SCHEMA): raise ValueError('nonowned_export_directory')
    for p in (dest,*dest.parents):
        if p.is_symlink(): raise ValueError('symlink_export_refused')
    before={name:sha(p) for name,p in selected.items()}
    files=[];aliases={};seen={}
    # SQLite online backup includes WAL data; never raw-copy a running DB.
    target=dest/'brain.sqlite'
    if target.is_symlink(): raise ValueError('symlink_export_refused')
    src=sqlite3.connect((root/'data/brain.sqlite').resolve().as_uri()+'?mode=ro',uri=True,timeout=2)
    dst=sqlite3.connect(target)
    try:
        src.backup(dst)
        if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise ValueError('snapshot_database_invalid')
    finally: dst.close(); src.close()
    os.chmod(target,0o600);scan_file(target)
    files.append({'path':'brain.sqlite','sha256':sha(target),'bytes':target.stat().st_size,'category':'cognitive_database'})
    for name,p in selected.items():
        scan_file(p); signature=before[name]
        if signature in seen: aliases[name]=seen[signature];continue
        seen[signature]=name
        out=dest/name
        if any(x.is_symlink() for x in (out,*out.parents)): raise ValueError('symlink_export_refused')
        out.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,out);os.chmod(out,0o600)
        if sha(out)!=signature: raise ValueError('source_changed_retry_later')
        files.append({'path':name,'sha256':signature,'bytes':p.stat().st_size,
                      'category':'operational_reference' if name.startswith(('operations/','scheduler/')) else 'native_memory_or_persona'})
    if any(sha(p)!=before[name] for name,p in selected.items()): raise ValueError('source_changed_retry_later')
    keep={x['path'] for x in files}
    if old:
        for oldfile in old.get('files',[]):
            name=safe_name(oldfile['path']); p=dest/name
            if name not in keep and p.is_file():
                if p.is_symlink() or not p.resolve().is_relative_to(dest): raise ValueError('unsafe_stale_file')
                p.unlink()
    manifest={'schema':SCHEMA,'created_at':time.time(),'summary_proof':proof,'files':files,'aliases':aliases,
              'architecture':{'repository':architecture_repo,'commit':architecture_ref,'package':'personal-ai-companion-kit','version':'0.8.0'},
              'inheritance':{'default':['native_memory_or_persona','cognitive_database'],'never_auto_activate':['operational_reference'],
                             'excluded':['credentials','SSH keys','channel login state','runtime code','models','generated panels','completed learning queue files']}}
    write_json(marker,manifest)
    return manifest


def github_json(url):
    req=Request(url,headers={'User-Agent':'personal-ai-companion-kit','Accept':'application/vnd.github+json'})
    with urlopen(req,timeout=20) as response: return json.load(response)


def privacy_check(repo):
    # Private GitHub repositories return404 to unauthenticated REST clients.
    # The caller ALSO proves repository existence/access with authenticated SSH.
    try:
        data=github_json('https://api.github.com/repos/'+repo)
        if data.get('private') is not True: raise ValueError('refuse_to_upload_memories_to_public_repository')
    except HTTPError as exc:
        if exc.code!=404: raise ValueError('repository_visibility_unverified') from None


def git(args,cwd=None,env=None,timeout=90,check=True):
    cmd=['git','-c','core.hooksPath=/dev/null','-c','commit.gpgsign=false',*args]
    result=subprocess.run(cmd,cwd=cwd,env=env,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if check and result.returncode: raise RuntimeError('git_'+args[0]+'_failed; inspect local transport without printing credentials')
    return result


def proxy_tunnel(proxy):
    """Use the host's existing proxy; credentials never enter argv or files."""
    parsed=urlsplit(proxy)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        raise ValueError('HTTP_CONNECT_proxy_required')
    connection=socket.create_connection((parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80)),timeout=20)
    try:
        if parsed.scheme=='https':
            connection=ssl.create_default_context().wrap_socket(connection,server_hostname=parsed.hostname)
        headers=['CONNECT ssh.github.com:443 HTTP/1.1','Host: ssh.github.com:443']
        if parsed.username is not None:
            auth=(unquote(parsed.username)+':'+unquote(parsed.password or '')).encode('utf-8')
            headers.append('Proxy-Authorization: Basic '+base64.b64encode(auth).decode('ascii'))
        connection.sendall(('\r\n'.join(headers)+'\r\n\r\n').encode('ascii'))
        response=bytearray()
        # Read only the headers, leaving any following SSH banner untouched.
        while not response.endswith(b'\r\n\r\n'):
            chunk=connection.recv(1)
            if not chunk or len(response)>=65536: raise ValueError('proxy_CONNECT_response_invalid')
            response.extend(chunk)
        status=bytes(response).split(b'\r\n',1)[0].split()
        if len(status)<2 or status[1]!=b'200': raise ValueError('proxy_CONNECT_refused')
        connection.settimeout(None)
        return connection
    except Exception:
        connection.close()
        raise


def ssh_proxy():
    """OpenSSH ProxyCommand, restricted to the official GitHub SSH443 host."""
    proxy=next((os.environ[k] for k in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy','ALL_PROXY','all_proxy') if os.environ.get(k)),None)
    if not proxy: raise ValueError('proxy_environment_missing')
    with closing(proxy_tunnel(proxy)) as connection:
        def upload():
            try:
                while True:
                    data=os.read(sys.stdin.fileno(),65536)
                    if not data: break
                    connection.sendall(data)
                connection.shutdown(socket.SHUT_WR)
            except OSError: pass
        threading.Thread(target=upload,daemon=True).start()
        while True:
            data=connection.recv(65536)
            if not data: break
            sys.stdout.buffer.write(data);sys.stdout.buffer.flush()


def finish_receipt(root,ledger,receipts,record_key,receipt):
    ledger['receipts'][record_key]=receipt
    ledger.setdefault('pending',{}).pop(record_key,None)
    write_json(receipts,ledger)
    with closing(sqlite3.connect(root/'data/brain.sqlite',timeout=2)) as db, db:
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='ct_delivery'").fetchone():
            db.execute('INSERT OR REPLACE INTO ct_delivery VALUES(?,?,?,?,?,?)',
                       ('github:'+record_key.rsplit(':',1)[-1],'github_backup','accepted',json_text(receipt),time.time(),receipt['url']))
    return dict(ok=True,already_uploaded=False,**receipt)


def publish(root,worktree,repo,key,architecture_ref,day=None,bootstrap=False,identity_file=None,architecture_repo='https://github.com/BrianChen33/personal-ai-companion-kit',ssh_transport='standard'):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo): raise ValueError('invalid_repository')
    if ssh_transport not in ('standard','github443','github443-proxy'): raise ValueError('invalid_SSH_transport')
    root=safe_source(root).resolve(); worktree=Path(worktree).expanduser().resolve()
    if worktree==root or root.is_relative_to(worktree) or worktree.is_relative_to(root): raise ValueError('worktree_must_be_separate')
    key=Path(key).expanduser().resolve()
    if not key.is_file() or key.is_symlink(): raise ValueError('host_local_SSH_identity_required')
    if os.name!='nt' and key.stat().st_mode&0o077: raise ValueError('SSH_identity_permissions_require_600')
    proof=summary_proof(root,day,bootstrap)
    proof_key=hashlib.sha256(json_text({'summary':proof,'architecture_repo':architecture_repo,'architecture_commit':architecture_ref}).encode()).hexdigest()
    receipts=root/'state/github-vault-receipts.json'
    ledger=json.loads(receipts.read_text(encoding='utf-8')) if receipts.is_file() else {'version':1,'receipts':{}}
    record_key=repo+':'+proof_key
    privacy_check(repo)
    # Obtain host keys through GitHub's official HTTPS metadata; do not trust
    # an unauthenticated ssh-keyscan or disable SSH host-key verification.
    hostkeys=github_json('https://api.github.com/meta').get('ssh_keys',[])
    hostkeys=[x for x in hostkeys if x.startswith(('ssh-ed25519 ','ecdsa-sha2-nistp256 ','ssh-rsa '))]
    if not hostkeys: raise ValueError('github_host_keys_unavailable')
    hosts=root/'state/github-vault-known-hosts'
    hosts.parent.mkdir(parents=True,exist_ok=True);hosts.write_text(''.join('github.com,[ssh.github.com]:443 '+x+'\n' for x in hostkeys),encoding='utf-8');os.chmod(hosts,0o600)
    env=os.environ.copy();env['GIT_TERMINAL_PROMPT']='0'
    command=['ssh','-i',key.as_posix(),'-o','IdentitiesOnly=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+hosts.as_posix(),'-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=2']
    if ssh_transport!='standard': command+=['-o','HostName=ssh.github.com','-p','443']
    if ssh_transport=='github443-proxy':
        command+=['-o','ProxyCommand='+shlex.join([sys.executable,Path(__file__).resolve().as_posix(),'--ssh-proxy'])]
    env['GIT_SSH_COMMAND']=shlex.join(command)
    url='git@github.com:'+repo+'.git'
    git(['ls-remote',url],env=env)  # authenticates exact repository, including404 case
    if not (worktree/'.git').is_dir():
        if worktree.exists() and any(worktree.iterdir()): raise ValueError('nonempty_nonrepo_worktree')
        git(['clone',url,str(worktree)],env=env)
    if git(['remote','get-url','origin'],worktree,env).stdout.strip()!=url: raise ValueError('wrong_worktree_origin')
    git(['fetch','origin','main'],worktree,env)
    if record_key in ledger['receipts']:
        receipt=ledger['receipts'][record_key]
        known=git(['merge-base','--is-ancestor',receipt['commit'],'origin/main'],worktree,env,check=False)
        if known.returncode==0: return dict(ok=True,already_uploaded=True,**receipt)
        raise ValueError('previous_receipt_no_longer_reachable_do_not_blindly_resend')
    pending=ledger.get('pending',{}).get(record_key)
    if pending:
        reachable=git(['merge-base','--is-ancestor',pending['commit'],'origin/main'],worktree,env,check=False).returncode==0
        if not reachable:
            # Retry EXACTLY the preserved immutable commit, never regenerate a
            # snapshot or force-update a branch after an unknown result.
            git(['push','origin',pending['commit']+':refs/heads/main'],worktree,env)
            reachable=git(['ls-remote','origin','refs/heads/main'],worktree,env).stdout.split()[0]==pending['commit']
        if not reachable: raise RuntimeError('pending_push_unconfirmed')
        pending['confirmed_at']=time.time()
        return finish_receipt(root,ledger,receipts,record_key,pending)
    if git(['status','--porcelain'],worktree,env).stdout.strip(): raise ValueError('dirty_vault_worktree_requires_inspection')
    git(['merge','--ff-only','origin/main'],worktree,env)
    manifest=export_snapshot(root,worktree/'current',architecture_ref,day,bootstrap,identity_file,architecture_repo)
    write_json(worktree/'LATEST.json',{'schema':SCHEMA,'manifest':'current/manifest.json','kind':proof['kind'],'day':proof['day'],
                                    'created_at':manifest['created_at'],'files':len(manifest['files']),'architecture':manifest['architecture']})
    git(['add','--all','--','current','LATEST.json'],worktree,env)
    git(['-c','user.name=Companion Memory Backup','-c','user.email=companion-memory@users.noreply.github.com',
         'commit','-m','Memory '+proof['kind']+' '+proof['day']],worktree,env)
    commit=git(['rev-parse','HEAD'],worktree,env).stdout.strip()
    receipt={'repository':repo,'commit':commit,'day':proof['day'],'kind':proof['kind'],
             'files':len(manifest['files']),'aliases':len(manifest['aliases']),'confirmed_at':None,
             'url':'https://github.com/'+repo+'/commit/'+commit}
    ledger.setdefault('pending',{})[record_key]=receipt;write_json(receipts,ledger)
    privacy_check(repo)
    try: git(['push','origin','HEAD:main'],worktree,env)
    except (RuntimeError,subprocess.TimeoutExpired):
        # A timeout may follow a successful push. Only a real remote commit is
        # a receipt. Do not create a second commit or force-push on uncertainty.
        pass
    remote=git(['ls-remote','origin','refs/heads/main'],worktree,env).stdout.split()
    if not remote or remote[0]!=commit: raise RuntimeError('push_receipt_unknown_local_commit_preserved')
    receipt['confirmed_at']=time.time()
    return finish_receipt(root,ledger,receipts,record_key,receipt)


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if argv==['--ssh-proxy']:
        try: ssh_proxy();return 0
        except Exception:
            # Never include proxy URLs, auth headers or network exceptions.
            print('GitHub proxy tunnel failed',file=sys.stderr);return 1
    parser=argparse.ArgumentParser(description='Private GitHub native-format cognitive snapshot')
    parser.add_argument('--root',required=True);parser.add_argument('--worktree',required=True)
    parser.add_argument('--repo',required=True);parser.add_argument('--ssh-key',required=True)
    parser.add_argument('--architecture-ref',required=True);parser.add_argument('--day');parser.add_argument('--bootstrap',action='store_true')
    parser.add_argument('--architecture-repo',default='https://github.com/BrianChen33/personal-ai-companion-kit')
    parser.add_argument('--identity-file')
    parser.add_argument('--ssh-transport',choices=('standard','github443','github443-proxy'),default='standard')
    args=parser.parse_args(argv)
    try:
        result=publish(args.root,args.worktree,args.repo,args.ssh_key,args.architecture_ref,args.day,args.bootstrap,args.identity_file,args.architecture_repo,args.ssh_transport)
        print(json_text(result));return 0
    except Exception as exc:
        print(json_text({'ok':False,'error':type(exc).__name__,'reason':str(exc)[:220],'uploaded':False}));return 1


if __name__=='__main__': raise SystemExit(main())
