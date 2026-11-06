"""Optional owner-private sleep/activity plugin; foreground never contacts Xiaomi."""
import json
import os
from pathlib import Path
import subprocess
import time

API = 1
VERSION = '0.1.0'
ALLOWED = ('sleep', 'steps', 'activity_daily', 'workouts')


def initialize(b):
    path = b.root / 'mi-fitness.json'
    if not path.exists():
        from muse_ext.companion_io import atomic
        private = Path.home() / '.config' / 'muse-health-bridge'
        atomic(path, json.dumps({'version': 1, 'private_dir': str(private),
                               'chat_summary_memory_allowed': False,
                               'worker_python': str(private / '.venv' / 'bin' / 'python')}))


def configuration(b):
    path = b.root / 'mi-fitness.json'
    if path.is_symlink() or path.stat().st_size > 4096:
        raise ValueError('invalid_health_configuration')
    value = json.loads(path.read_text(encoding='utf-8'))
    private = Path(value['private_dir']).expanduser().absolute()
    if private.resolve().is_relative_to(b.root.resolve()) or b.root.resolve().is_relative_to(private.resolve()):
        raise ValueError('health_storage_must_be_outside_brain')
    return value, private


def context(b, q):
    if q.get('scope') != 'owner-private':
        return {}
    try:
        config, private = configuration(b)
        if config.get('chat_summary_memory_allowed') is not True:
            return {'status': 'awaiting_summary_privacy_choice', 'allowed': list(ALLOWED)}
        path = private / 'context.json'
        if path.is_symlink() or not path.exists() or path.stat().st_size > 16384:
            return {'status': 'awaiting_sync', 'allowed': list(ALLOWED)}
        value = json.loads(path.read_text(encoding='utf-8'))
        if value.get('schema') != 'owner-sleep-activity-context-v1':
            return {'status': 'invalid_cache'}
        value['stale'] = time.time() - value['fetched_at'] > 21600
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return {'status': 'unavailable'}


def panel(b):
    value = context(b, {'scope': 'owner-private'})
    # Never copy health measurements into the offline panel or its artifacts.
    return {'status': value.get('status', 'awaiting_sync'), 'allowed': list(ALLOWED),
            'last_sync': value.get('fetched_at'), 'private_health_values_hidden': True}


def dispatch(b, q):
    if q.get('scope') != 'owner-private':
        raise ValueError('health_owner_private_only')
    action = q.get('action', 'status')
    if action == 'authorize_chat_summary_memory':
        if q.get('authorized') is not True or type(q.get('allowed')) is not bool:
            raise ValueError('explicit_owner_summary_privacy_choice_required')
        config, _ = configuration(b)
        config['chat_summary_memory_allowed'] = q['allowed']
        from muse_ext.companion_io import atomic
        atomic(b.root / 'mi-fitness.json', json.dumps(config))
        return {'ok': True, 'chat_summary_memory_allowed': q['allowed'], 'raw_health_backups': False}
    if action == 'status':
        return {'ok': True, **panel(b), 'version': VERSION}
    if action == 'context':
        return {'ok': True, 'health': context(b, q)}
    if action not in ('sync', 'history', 'care_work', 'care_settle'):
        raise ValueError('health_action_not_allowed')
    config, private = configuration(b)
    if action != 'sync' and config.get('chat_summary_memory_allowed') is not True:
        return {'ok': False, 'status': 'awaiting_summary_privacy_choice'}
    args = [config['worker_python'], str(Path(__file__).with_name('bridge.py')),
            '--private-dir', str(private), '--scope', 'owner-private', action]
    if action == 'history':
        days = q.get('days', 7)
        if isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 31:
            raise ValueError('health_history_days_out_of_range')
        args += ['--days', str(days)]
    if action == 'care_settle':
        args += ['--candidate', str(q.get('candidate', '')), '--outcome', str(q.get('outcome', '')),
                 '--receipt', str(q.get('receipt', ''))]
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=75,
                              encoding='utf-8', errors='replace',
                              env={**os.environ, 'TZ': 'Asia/Shanghai'})
        if len(done.stdout) > 150000:
            raise ValueError('health_worker_output_too_large')
        result = json.loads(done.stdout)
        if not isinstance(result, dict):
            raise ValueError('invalid_health_worker_output')
        return result
    except subprocess.TimeoutExpired:
        return {'ok': False, 'status': 'sync_timeout', 'cached_data_preserved': True}
    except (OSError, ValueError):
        return {'ok': False, 'status': 'worker_unavailable', 'cached_data_preserved': True}


def allow_share(b, event_id):
    return False  # Health care uses its own owner-private receipt ledger.
