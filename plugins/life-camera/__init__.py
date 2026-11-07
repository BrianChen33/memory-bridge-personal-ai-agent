"""Optional life-camera adapter. Actual image tools and delivery belong to the host."""
from pathlib import Path
from . import jobs, library, store

API = 1
VERSION = '0.1.0'


def initialize(b):
    store.initialize(b)


def panel(b):
    value = store.status(b)
    identity = store.settings(b)['character_id']
    reference = None
    if identity:
        try:
            asset = library.get(b, 'characters', identity)
            reference = dict(name=asset['name'], revision=asset['revision'], images=len(asset['images']))
        except ValueError:
            pass
    state = 'awaiting_reference' if not reference else 'ready' if store.host_binding(b) else 'awaiting_host_binding'
    return dict(status=state, version=VERSION,
                settings=value['settings'], reference=reference, recent=value['recent'], counts=value['counts'],
                backend='host-native', cooldown_seconds=value['cooldown_seconds'])


def camera(b, scope):
    from muse_ext.presentation import _legacy_camera
    if scope != 'owner-private':
        return dict(enabled=False)
    config = store.settings(b)
    baseline = _legacy_camera(b, scope, force_enabled=True)
    value = panel(b)
    baseline.update(enabled=value['status'] == 'ready', plugin='life-camera', status=value['status'],
                    settings=config, reference=value['reference'], jobs=value['counts'],
                    policy='The SAME host model may choose one life photo while appraising/replying. '
                           'Use only released current stages and present emotion/energy/relationship. '
                           'Call plan with a real owner source or appraised life_id, then let the existing '
                           'background runner claim work. Every selfie must attach the original character '
                           'sheet as actual image input. Keep ordinary text responsive. Actual native '
                           'generation and send receipts close the job. Quiet hours01–07 Shanghai apply '
                           'to autonomous photos. Sticker draws keep their independent existing entry.')
    # The plugin owns the reference index. Avoid echoing old full reference paths.
    baseline.pop('references', None)
    baseline['guide'] = str(Path(__file__).with_name('PROTOCOL.md'))
    baseline['recent_milestones'] = baseline.get('recent_milestones', [])[:3]
    return baseline


def context(b, q):
    return dict(status='routed_to_camera_context') if q.get('scope') == 'owner-private' else {}


def compat_photo(b, q):
    from muse_ext.presentation import _legacy_photo
    if q.get('scope') != 'owner-private':
        raise ValueError('camera_owner_private_only')
    if q.get('action', 'request') == 'settle':
        row = b.db.execute('SELECT id FROM lc_job WHERE binding=?', ('user:' + str(q.get('source_event')),)).fetchone()
        if not row:
            raise ValueError('camera_photo_job_required_for_settlement')
        return jobs.settle(b, {**q, 'id': row['id']})
    return _legacy_photo(b, q, force_enabled=True)


def dispatch(b, q):
    if q.get('scope') != 'owner-private':
        raise ValueError('camera_owner_private_only')
    action = q.get('action', 'status')
    if action == 'status':
        return dict(ok=True, **panel(b))
    if action == 'configure':
        return store.configure(b, q)
    if action == 'bind_host':
        return store.bind_host(b, q)
    if action == 'asset_put':
        return library.put(b, q)
    if action == 'assets':
        return library.listing(b, q)
    if action == 'context':
        return dict(ok=True, camera_context=camera(b, 'owner-private'))
    if action == 'plan':
        if not store.host_binding(b):
            return dict(ok=False, status='awaiting_host_binding', job=None)
        return jobs.plan(b, q)
    if action == 'work':
        if not store.host_binding(b):
            return dict(ok=False, status='awaiting_host_binding', job=None)
        return jobs.work(b)
    if action == 'bind':
        return jobs.bind(b, q)
    if action == 'rendered':
        return jobs.rendered(b, q)
    if action == 'generation_failed':
        return jobs.failed(b, q)
    if action == 'send_work':
        if not store.host_binding(b):
            return dict(ok=False, status='awaiting_host_binding', job=None)
        return jobs.send_work(b)
    if action == 'settle':
        return jobs.settle(b, q)
    if action == 'reconcile':
        return jobs.reconcile(b)
    raise ValueError('unknown_camera_action')


def allow_share(b, event_id):
    return False  # The photo ledger uses the existing owner-private host send route.
