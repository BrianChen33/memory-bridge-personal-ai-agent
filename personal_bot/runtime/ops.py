"""File snapshot and conflict-aware rollback. Native cron restoration is orchestrated
by Muse tools using the separately preserved definitions, never an invented CLI.
"""
import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from brain import Brain, atomic_json, config_guard


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    temp = path.with_name(path.name+'.muse-brain-tmp')
    with open(temp,'wb') as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp,path)


def snapshot(root, paths):
    folder = Path(root)/'snapshots'/str(time.time_ns())
    folder.mkdir(parents=True)
    entries = []
    for i,p in enumerate(paths):
        p = Path(p).resolve()
        if p.is_symlink():
            raise ValueError('symlink_not_supported')
        exists = p.exists()
        data = p.read_bytes() if exists else b''
        backup = str(i)+'.bin'
        (folder/backup).write_bytes(data)
        entries.append(dict(path=str(p),existed=exists,backup=backup,original=digest(data),installed=None,
                            mode=p.stat().st_mode & 0o777 if exists else 0o600))
    manifest = folder/'manifest.json'
    atomic_json(manifest,dict(entries=entries,version=1))
    return manifest


def install(manifest, target, data):
    manifest = Path(manifest)
    m = json.loads(manifest.read_text(encoding='utf-8'))
    target = Path(target).resolve()
    item = next((x for x in m['entries'] if x['path']==str(target)),None)
    if not item:
        raise ValueError('target_not_snapshotted')
    current = digest(target.read_bytes()) if target.exists() else digest(b'')
    if current not in ([item['original'],item['installed']]+item.get('project_hashes',[])):
        raise ValueError('target_changed')
    # Record intended hash first: rollback can recover a crash after replacement.
    item['project_hashes']=list(set(item.get('project_hashes',[])+[h for h in [item['installed'],digest(data)] if h]))
    item['installed'] = digest(data)
    atomic_json(manifest,m)
    atomic_bytes(target,data)
    if os.name!='nt':
        os.chmod(target,item['mode'])


def rollback(root, manifest):
    root,manifest = Path(root),Path(manifest)
    # This kill switch is independent of DB health.
    cfg_path = root/'config.json'
    with config_guard(root):
        try:
            cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            cfg = dict(enabled=False,epoch=0,modules={})
        cfg['enabled'] = False
        cfg['epoch'] = int(cfg.get('epoch',0))+1
        atomic_json(cfg_path,cfg)
    m = json.loads(manifest.read_text(encoding='utf-8'))
    conflicts,restored = [],[]
    for item in reversed(m['entries']):
        if item['installed'] is None:
            continue
        p = Path(item['path'])
        backup = manifest.parent/item['backup']
        data = backup.read_bytes()
        if digest(data)!=item['original']:
            conflicts.append(dict(path=str(p),reason='backup_hash_mismatch'))
            continue
        current = digest(p.read_bytes()) if p.exists() else digest(b'')
        if current==item['original'] and p.exists()==item['existed']:
            continue
        if current not in ([item['installed']]+item.get('project_hashes',[])):
            conflicts.append(dict(path=str(p),reason='external_edit'))
            continue
        if item['existed']:
            atomic_bytes(p,data)
            if os.name!='nt':
                os.chmod(p,item['mode'])
        else:
            # Preserve generated index for recovery; remove only the installed path.
            archive = manifest.parent/('removed-'+item['backup'])
            os.replace(p,archive)
        restored.append(str(p))
    return dict(ok=not conflicts,enabled=False,restored=restored,conflicts=conflicts,
                database_preserved=True,native_cron='restore_via_Muse_tools_if_modified')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('op',choices=['snapshot','install','rollback'])
    parser.add_argument('--root',default=str(Path(__file__).resolve().parent))
    parser.add_argument('--manifest')
    parser.add_argument('--paths',nargs='*')
    parser.add_argument('--target')
    parser.add_argument('--source')
    args = parser.parse_args()
    try:
        if args.op=='snapshot':
            result = dict(ok=True,manifest=str(snapshot(args.root,args.paths or [])))
        elif args.op=='install':
            install(args.manifest,args.target,Path(args.source).read_bytes())
            result = dict(ok=True)
        else:
            result = rollback(args.root,args.manifest)
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['ok'] else 1
    except Exception as e:
        print(json.dumps(dict(ok=False,error=type(e).__name__)))
        return 1


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    sys.exit(main())
