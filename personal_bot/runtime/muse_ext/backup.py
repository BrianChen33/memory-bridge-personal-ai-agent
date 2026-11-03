"""Verified full cognitive snapshots; private data never leaves the local host.

File sources are an explicit deployment allowlist. This module never scans the
user's home or copies credentials. Restores only materialize into a fresh tree;
activating restored native schedules remains the Muse scheduler's responsibility.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath

from brain import atomic_json, config_guard

SCHEMA = 'muse-full-backup-v2'
BJ = timezone(timedelta(hours=8))


def _safe_name(name):
    if not isinstance(name, str) or '\\' in name or '\0' in name or ':' in name:
        raise ValueError('unsafe_backup_path')
    p = PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or not p.parts or p.parts[0] not in ('project', 'native', 'scheduler'):
        raise ValueError('unsafe_backup_path')
    if any(x.lower() in ('secrets', 'credentials', 'vault') or x.lower().startswith('.env') for x in p.parts):
        raise ValueError('credential_backup_refused')
    return p.as_posix()


def _not_symlink(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('backup_symlink_refused')
    return path


def _hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def _db_check(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    try:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('backup_database_integrity')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'memories', 'mood', 'emotion', 'candidates'} <= tables:
            raise ValueError('backup_database_schema')
    finally:
        db.close()


def default_sources(root):
    """Only own project files plus the native deployment's explicit registry."""
    root = Path(root).resolve()
    registry = root/'backup-sources.json'
    if not registry.is_file():
        raise ValueError('backup_source_registry_required')
    data = json.loads(registry.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('sources'), list):
        raise ValueError('invalid_backup_source_registry')
    sources = {}
    patterns = ('*.py', '*.mjs', '*.md', '*.json', 'muse_ext/**/*.py',
                'templates/**/*.md', 'state/**/*.json', 'state/**/*.jsonl', 'state/**/*.txt',
                'library/**/*.md', 'library/**/*.txt')
    for pattern in patterns:
        for p in root.glob(pattern):
            if p.is_file():
                name = 'project/'+p.relative_to(root).as_posix()
                sources[name] = {'name': name, 'path': str(p), 'required': True}
    for entry in data['sources']:
        name = _safe_name(entry.get('name'))
        if name in sources and Path(entry['path']).resolve() != Path(sources[name]['path']).resolve():
            raise ValueError('conflicting_backup_source')
        sources[name] = entry
    # The deployment journal references executable host-file rollback originals.
    # Copy only those owned manifests and their validated original blobs; do not
    # scan arbitrary snapshots or follow their external target paths.
    journal=root/'state/deployment.json'
    if journal.is_file():
        deployment=json.loads(journal.read_text(encoding='utf-8'))
        manifests=deployment.get('host_manifests',[])
        if not isinstance(manifests,list) or len(manifests)>100:
            raise ValueError('invalid_host_manifest_registry')
        for ref in manifests:
            raw=ref.get('path') if isinstance(ref,dict) else ref
            manifest=_not_symlink(raw).resolve()
            if not manifest.is_relative_to(root/'snapshots') or manifest.name!='manifest.json' or not manifest.parent.name.isdigit():
                raise ValueError('unsafe_host_manifest')
            doc=json.loads(manifest.read_text(encoding='utf-8'))
            if doc.get('version')!=1 or not isinstance(doc.get('entries'),list):
                raise ValueError('invalid_host_manifest')
            selected=[manifest]
            for item in doc['entries']:
                parts=re.split(r'[/\\]',str(item.get('path','')))
                if any(x.lower().startswith('.env') or x.lower() in ('credentials','secrets','vault') for x in parts):
                    raise ValueError('credential_backup_refused')
                name=item.get('backup','')
                if not re.fullmatch(r'[0-9]+\.bin',name):
                    raise ValueError('unsafe_host_backup_blob')
                blob=_not_symlink(manifest.parent/name)
                if not blob.is_file() or _hash(blob)!=item.get('original'):
                    raise ValueError('host_original_hash_mismatch')
                selected.append(blob)
            for path in selected:
                name='project/'+path.relative_to(root).as_posix()
                sources[name]={'name':_safe_name(name),'path':str(path),'required':True}
    for tree in data.get('trees', []):
        folder = _not_symlink(tree['path'])
        prefix = _safe_name(tree['name'])
        # These are narrowly owned document/state directories, never a home
        # directory or arbitrary filesystem subtree.
        if folder.name not in ('memory', 'companion', 'definitions', 'library'):
            raise ValueError('invalid_backup_tree')
        if not folder.is_dir():
            if tree.get('required'):
                raise ValueError('required_backup_tree_missing')
            continue
        for p in folder.rglob('*'):
            _not_symlink(p)
            if p.is_file() and p.suffix.lower() in ('.md', '.txt', '.json', '.jsonl'):
                name = prefix+'/'+p.relative_to(folder).as_posix()
                sources[name] = {'name': _safe_name(name), 'path': str(p), 'required': True}
    return list(sources.values())


def verify_snapshot(snapshot):
    folder = _not_symlink(snapshot).resolve()
    mpath = folder/'manifest.json'
    _not_symlink(mpath)
    m = json.loads(mpath.read_text(encoding='utf-8'))
    if m.get('schema') != SCHEMA or not re.fullmatch('[a-f0-9]{32}', m.get('id', '')):
        raise ValueError('invalid_backup_manifest')
    files = m.get('files')
    if not isinstance(files, dict) or 'project/data/brain.sqlite' not in files:
        raise ValueError('invalid_backup_manifest')
    for name, meta in files.items():
        safe = _safe_name(name)
        p = _not_symlink(folder/safe)
        if not p.is_file() or p.stat().st_size != meta['size'] or _hash(p) != meta['sha256']:
            raise ValueError('backup_hash_mismatch')
    _db_check(folder/'project/data/brain.sqlite')
    return m


def _remove_owned(folder, parent, snapshot_id):
    """Never recursively remove a computed path without ownership/path checks."""
    if not re.fullmatch('[a-f0-9]{32}', snapshot_id):
        raise ValueError('invalid_backup_id')
    folder = _not_symlink(folder)
    if folder.resolve().parent != Path(parent).resolve() or folder.name != snapshot_id:
        raise ValueError('unsafe_backup_cleanup_path')
    m = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if m.get('schema') != SCHEMA or m.get('id') != snapshot_id:
        raise ValueError('backup_cleanup_ownership')
    shutil.rmtree(folder)


def create_snapshot(root, sources=None, daily=True, now=None):
    root = _not_symlink(root).resolve()
    supplied = default_sources(root) if sources is None else sources
    if not isinstance(supplied, list):
        raise ValueError('invalid_backup_sources')
    checked, missing, names = [], [], {'project/data/brain.sqlite'}
    for entry in supplied:
        name = _safe_name(entry.get('name'))
        if name in names:
            raise ValueError('duplicate_backup_path')
        names.add(name)
        p = _not_symlink(entry['path'])
        if any(x.lower() in ('credentials', 'secrets', 'vault') or x.lower().startswith('.env') for x in p.parts):
            raise ValueError('credential_backup_refused')
        if not p.is_file():
            if entry.get('required', False):
                raise ValueError('required_backup_source_missing')
            missing.append(name)
            continue
        checked.append((name, p))
    db_source = _not_symlink(root/'data/brain.sqlite')
    if not db_source.is_file():
        raise ValueError('required_backup_database_missing')
    base = root/'backups/full'
    _not_symlink(base)
    base.mkdir(parents=True, exist_ok=True)
    if os.name != 'nt':
        os.chmod(base, 0o700)
    moment = now or datetime.now(tz=BJ)
    date = moment.astimezone(BJ).date().isoformat()
    with config_guard(base):
        index_path = base/'index.json'
        index = json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else {'version': 1, 'daily': {}, 'manual': []}
        if daily and date in index['daily']:
            old = base/'snapshots'/index['daily'][date]
            m = verify_snapshot(old)
            return dict(ok=True, snapshot=str(old), date=date, reused=True,
                        files=len(m['files']), missing_optional=m.get('missing_optional', []))
        snapshot_id = uuid.uuid4().hex
        parent = base/'snapshots'
        parent.mkdir(exist_ok=True)
        stage = parent/('.'+snapshot_id+'.tmp')
        final = parent/snapshot_id
        stage.mkdir(mode=0o700)
        # Freeze expected file versions before the SQLite online snapshot. A
        # cursor/config/native file changed during capture must not be mixed
        # silently with an earlier database point in time.
        initial_hashes = {name: _hash(p) for name, p in checked}
        db_target = stage/'project/data/brain.sqlite'
        db_target.parent.mkdir(parents=True)
        src = sqlite3.connect(db_source.as_uri()+'?mode=ro', uri=True)
        dst = sqlite3.connect(db_target)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        manifest = {'schema': SCHEMA, 'id': snapshot_id, 'date': date, 'daily': bool(daily),
                    'created_at': time.time(), 'files': {}, 'missing_optional': missing}
        for name, p in checked:
            before = initial_hashes[name]
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(p, target)
            if before != _hash(p) or before != _hash(target):
                raise ValueError('backup_source_changed_retry')
        if any(_hash(p) != initial_hashes[name] for name, p in checked):
            raise ValueError('backup_source_changed_retry')
        for p in stage.rglob('*'):
            if p.is_file():
                if os.name != 'nt':
                    os.chmod(p, 0o600)
                manifest['files'][p.relative_to(stage).as_posix()] = {
                    'sha256': _hash(p), 'size': p.stat().st_size, 'mode': 0o600,
                }
        atomic_json(stage/'manifest.json', manifest)
        verify_snapshot(stage)
        os.replace(stage, final)
        retired = []
        if daily:
            index['daily'][date] = snapshot_id
            for old_date in sorted(index['daily'])[:-7]:
                retired.append(index['daily'].pop(old_date))
        else:
            index['manual'].append(snapshot_id)
        atomic_json(index_path, index)
        cleanup_warnings = []
        for old_id in retired:
            try:
                _remove_owned(parent/old_id, parent, old_id)
            except (OSError, ValueError, KeyError):
                cleanup_warnings.append(old_id)
        return dict(ok=True, snapshot=str(final), date=date, reused=False,
                    files=len(manifest['files']), missing_optional=missing,
                    cleanup_warnings=cleanup_warnings)


def restore_snapshot(snapshot, destination):
    manifest = verify_snapshot(snapshot)
    destination = _not_symlink(destination)
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError('restore_destination_must_be_empty')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = Path(snapshot).resolve()
    for name, meta in manifest['files'].items():
        target = destination/_safe_name(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source/name, target)
        if _hash(target) != meta['sha256']:
            raise ValueError('restore_hash_mismatch')
        if os.name != 'nt':
            os.chmod(target, meta.get('mode', 0o600))
    _db_check(destination/'project/data/brain.sqlite')
    return dict(ok=True, destination=str(destination), files=len(manifest['files']),
                native_schedules='saved_definitions_only_restore_via_native_tools')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('op', choices=('create', 'verify', 'restore'))
    parser.add_argument('--root', default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument('--snapshot')
    parser.add_argument('--destination')
    parser.add_argument('--manual', action='store_true')
    args = parser.parse_args()
    try:
        if args.op == 'create':
            result = create_snapshot(args.root, daily=not args.manual)
        elif args.op == 'verify':
            m = verify_snapshot(args.snapshot)
            result = dict(ok=True, files=len(m['files']), date=m['date'])
        else:
            result = restore_snapshot(args.snapshot, args.destination)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as e:
        print(json.dumps({'ok': False, 'error': type(e).__name__, 'reason': str(e)[:100]}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
