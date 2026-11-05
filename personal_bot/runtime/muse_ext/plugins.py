"""Explicit local plugin installation. No discovery downloads or host API claims."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import uuid

API = 1
_loaded = {}


def read_registry(b):
    p = b.root / 'plugins.json'
    if not p.exists():
        return {'version': 1, 'plugins': {}}
    if p.is_symlink() or p.stat().st_size > 65536:
        raise ValueError('invalid_plugin_registry')
    data = json.loads(p.read_text(encoding='utf-8'))
    if data.get('version') != 1 or not isinstance(data.get('plugins'), dict):
        raise ValueError('invalid_plugin_registry')
    return data


def write_registry(b, value):
    from muse_ext.companion_io import atomic
    atomic(b.root / 'plugins.json', json.dumps(value, ensure_ascii=False, indent=2))


def copy_bytes(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name('.' + target.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(source.read_bytes())
        os.chmod(temporary, 0o600)
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()


def safe_file(folder, name):
    rel = PurePosixPath(name)
    if rel.is_absolute() or '..' in rel.parts or '\\' in name or ':' in name or not rel.parts:
        raise ValueError('unsafe_plugin_path')
    p = folder.joinpath(*rel.parts)
    if not p.resolve().is_relative_to(folder.resolve()) or any(x.is_symlink() for x in (p, *p.parents)):
        raise ValueError('unsafe_plugin_path')
    return p


def manifest(folder):
    p = safe_file(folder, 'manifest.json')
    if p.stat().st_size > 16384:
        raise ValueError('plugin_manifest_too_large')
    data = json.loads(p.read_text(encoding='utf-8'))
    if (not re.fullmatch(r'[a-z][a-z0-9-]{1,40}', str(data.get('id', ''))) or
            data.get('api') != API or not isinstance(data.get('files'), dict) or
            not 1 <= len(data['files']) <= 32 or '__init__.py' not in data['files']):
        raise ValueError('invalid_plugin_manifest')
    total = 0
    for name, expected in data['files'].items():
        file = safe_file(folder, name)
        if file.suffix not in ('.py', '.json', '.md', '.txt') or not re.fullmatch(r'[a-f0-9]{64}', str(expected)):
            raise ValueError('invalid_plugin_file')
        total += file.stat().st_size
        if total > 1_000_000 or hashlib.sha256(file.read_bytes()).hexdigest() != expected:
            raise ValueError('plugin_source_hash_mismatch')
    return data


def install(b, source):
    if not isinstance(source, str) or not source:
        raise ValueError('trusted_local_plugin_source_required')
    source = Path(source).expanduser().absolute()
    data = manifest(source)
    target = safe_file(b.root, 'extensions/' + data['id'])
    if target == source.resolve() or source.resolve().is_relative_to(target):
        raise ValueError('plugin_source_is_install_target')
    if target.exists() and any(target.iterdir()):
        old = target / 'manifest.json'
        if not old.is_file() or json.loads(old.read_text(encoding='utf-8')).get('id') != data['id']:
            raise ValueError('nonowned_plugin_directory')
    registry = read_registry(b)
    registry['plugins'][data['id']] = dict(id=data['id'], name=str(data.get('name', data['id']))[:80],
                                          version=str(data.get('version', ''))[:40], enabled=False)
    write_registry(b, registry)  # A failed update remains disabled, never half-active.
    for name in data['files']:
        copy_bytes(safe_file(source, name), safe_file(target, name))
    copy_bytes(source / 'manifest.json', target / 'manifest.json')
    return dict(ok=True, installed=data['id'], version=data['version'], enabled=False,
                next='enable explicitly; the host bot then asks the owner for permitted sources')


def load(b, pid):
    folder = safe_file(b.root, 'extensions/' + pid)
    data = manifest(folder)
    key = (str(folder), json.dumps(data['files'], sort_keys=True))
    if key not in _loaded:
        name = '_companion_plugin_' + hashlib.sha256(str(folder).encode()).hexdigest()[:24]
        for old in list(sys.modules):
            if old == name or old.startswith(name + '.'):
                del sys.modules[old]
        spec = importlib.util.spec_from_file_location(name, folder / '__init__.py', submodule_search_locations=[str(folder)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        if getattr(module, 'API', None) != API:
            raise ValueError('plugin_runtime_api_mismatch')
        _loaded[key] = module
    return _loaded[key]


def dispatch(b, q):
    if q.get('scope', 'owner-private') != 'owner-private':
        raise ValueError('plugin_owner_admin_only')
    registry = read_registry(b)
    if q['op'] == 'plugin_manage':
        action, pid = q.get('action', 'list'), q.get('plugin')
        if action == 'list':
            return dict(ok=True, plugins=list(registry['plugins'].values()), api=API)
        if action == 'install':
            return install(b, q.get('source_dir'))
        if action not in ('enable', 'disable') or pid not in registry['plugins']:
            raise ValueError('unknown_plugin_or_management_action')
        if action == 'enable':
            load(b, pid).initialize(b)
        registry['plugins'][pid]['enabled'] = action == 'enable'
        write_registry(b, registry)
        return dict(ok=True, plugin=registry['plugins'][pid], host_binding_required=True)
    pid = q.get('plugin')
    if pid not in registry['plugins']:
        return dict(ok=False, error='plugin_not_installed')
    if registry['plugins'][pid].get('enabled') is not True:
        return dict(ok=False, error='plugin_disabled')
    return load(b, pid).dispatch(b, q)


def context(b, q):
    if q.get('scope') != 'owner-private':
        return {}
    result = {}
    try:
        for pid, item in read_registry(b)['plugins'].items():
            if item.get('enabled'):
                try:
                    result[pid] = load(b, pid).context(b, q)
                except Exception as exc:
                    result[pid] = dict(status='unavailable', error=type(exc).__name__)
    except (OSError, ValueError):
        return {'status': 'registry_unavailable'}
    return result


def panel(b):
    result = []
    try:
        for pid, item in read_registry(b)['plugins'].items():
            status = dict(item)
            if item.get('enabled'):
                try:
                    status.update(load(b, pid).panel(b))
                except Exception as exc:
                    status.update(status='unavailable', error=type(exc).__name__)
            else:
                status['status'] = 'disabled'
            result.append(status)
    except (OSError, ValueError):
        return dict(api=API, status='registry_unavailable', items=[])
    return dict(api=API, items=result, optional=True)


def share_allowed(b, event_id):
    event = b.db.execute('SELECT source FROM source_events WHERE id=?', (event_id,)).fetchone()
    if not event or not event['source'].startswith('plugin:'):
        return True
    pid = event['source'].split(':', 2)[1]
    try:
        entry = read_registry(b)['plugins'].get(pid)
        return bool(entry and entry.get('enabled') and load(b, pid).allow_share(b, event_id))
    except Exception:
        return False
