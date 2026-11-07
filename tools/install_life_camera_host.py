"""Install an owner-authorized, verified camera payload into an existing host.

No network, model calls, native task creation, credentials or message sending.
The owner/host verifies the outer archive against the supplied release SHA first.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path):
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError('regular_file_required:' + path.name)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--expected-commit', required=True)
    args = parser.parse_args()
    payload = args.payload.expanduser().absolute()
    runtime = args.runtime_root.expanduser().absolute()
    state = args.state_root.expanduser().absolute()
    manifest = json.loads(regular(payload/'deploy-manifest.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'[a-f0-9]{40}', args.expected_commit) or manifest['commit'] != args.expected_commit:
        raise ValueError('fixed_architecture_commit_required')
    regular(state/'data/brain.sqlite')
    allowed = {'muse_ext/presentation.py', 'muse_ext/companion.py', 'muse_ext/companion_io.py',
               'muse_ext/companion_panel.html', 'tools/github_vault.py',
               'docs/HOME_PANEL.md', 'docs/HOST_TASKS.md', 'docs/INHERITANCE.md',
               'docs/VOICE_AND_LIFE_CAMERA.md'}
    updates = []
    for entry in manifest['files']:
        relative = Path(entry['source'])
        if relative.is_absolute() or '..' in relative.parts or '\\' in entry['source']:
            raise ValueError('unsafe_payload_path')
        source = regular(payload/relative)
        if sha(source) != entry['sha256']:
            raise ValueError('payload_hash_mismatch:' + relative.name)
        target_name = entry.get('target')
        if target_name:
            if target_name not in allowed:
                raise ValueError('unexpected_host_target')
            target = regular(runtime/target_name)
            if sha(target) not in (entry['previous_sha256'], entry['sha256']):
                raise ValueError('independent_host_customization_requires_diff:' + target_name)
            updates.append((source, target))
    reference = json.loads(regular(payload/'character/reference.json').read_text(encoding='utf-8'))
    art = regular(payload/'character/three-view.jpg')
    if sha(art) != reference['sha256']:
        raise ValueError('original_reference_hash_mismatch')
    # Preflight every target before mutating one. Each write is atomic and rerunnable.
    from importlib.util import spec_from_file_location, module_from_spec
    helper = regular(payload/'portable/personal_bot/runtime/muse_ext/plugins.py')
    spec = spec_from_file_location('_camera_copy_helper', helper)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    for source, target in updates:
        module.copy_bytes(source, target)
    sys.path.insert(0, str(runtime))
    from brain import Brain
    brain = Brain(state)
    try:
        brain.dispatch(dict(op='plugin_manage', scope='owner-private', action='install',
                            source_dir=str(payload/'plugins/life-camera')))
        brain.dispatch(dict(op='plugin_manage', scope='owner-private', action='enable', plugin='life-camera'))
        request = dict(op='plugin_call', scope='owner-private', plugin='life-camera')
        brain.dispatch(dict(request, action='asset_put', authorized=True, category='characters',
                            id=reference['id'], name=reference['name'],
                            description=reference['description'], images=[str(art)]))
        brain.dispatch(dict(request, action='configure', authorized=True, patch={'character_id': reference['id']}))
        status = brain.dispatch(dict(request, action='status'))
        print(json.dumps(dict(ok=True, plugin='life-camera', version='0.1.0',
                              reference_sha256=reference['sha256'], status=status['status'],
                              next='Verify real host capabilities, bind_host, wire existing life tasks, then update version lock and private snapshot.'),
                         ensure_ascii=False))
    finally:
        brain.close()


if __name__ == '__main__':
    main()
