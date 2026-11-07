"""Durable host-native work and delivery. This module never calls a model or sends."""
import json
import hashlib
import uuid

from . import library, store


def source(b, q):
    from muse_ext.companion import _get
    from muse_ext.presentation import _completion
    event_id, life_id = q.get('source_event'), q.get('life_id')
    promised_camera = None
    if event_id is not None:
        if type(event_id) is not int:
            raise ValueError('camera_real_owner_source_required')
        event = b.db.execute("SELECT id FROM source_events WHERE id=? AND scope='owner-private' AND actor='user' AND status='active'",
                             (event_id,)).fetchone()
        if not event:
            raise ValueError('camera_real_owner_source_required')
        promise = next((p for p in _get(b, 'life_photo_requests', []) if p.get('source_event') == event_id), None)
        if promise:
            promised_camera = promise['camera']
            if promise['status'] != 'pending':
                previous = b.db.execute('SELECT plan FROM lc_job WHERE binding=?', ('user:' + str(event_id),)).fetchone()
                if previous:
                    return json.loads(previous['plan'])['source']
                raise ValueError('camera_photo_promise_already_settled')
            if promise['when'] == 'completed':
                started = b.db.execute('SELECT * FROM ct_life WHERE id=?', (promise['activity_id'],)).fetchone()
                completed = _completion(b, started) if started else None
                if completed is None:
                    raise ValueError('camera_photo_stage_not_ready')
                life_id = completed['id']
            else:
                life_id = promise['activity_id']
    elif not life_id:
        raise ValueError('camera_released_life_source_required')
    result = dict(source_event=event_id, life_id=life_id,
                  description='An explicit owner photo request, using the current visible scene.')
    if promised_camera:
        result['promised_camera'] = promised_camera
    if life_id:
        life = b.db.execute('SELECT * FROM ct_life WHERE id=? AND occurred<=?', (life_id, store.now())).fetchone()
        if not life:
            raise ValueError('camera_released_life_source_required')
        if event_id is None and not life['appraised']:
            raise ValueError('camera_appraised_life_source_required')
        result.update(description=life['description'], activity=life['activity'], stage=life['stage'],
                      origin=life['origin'], occurred=life['occurred'])
    return result


def valid(b, row):
    plan = json.loads(row['plan'])
    library.validate_plan(b, plan)
    original = plan['source']
    # Legacy promises may already be settled after a crash following actual delivery.
    if row['manual']:
        event = b.db.execute("SELECT 1 FROM source_events WHERE id=? AND scope='owner-private' AND actor='user' AND status='active'",
                             (original['source_event'],)).fetchone()
        if not event:
            raise ValueError('camera_source_retired')
    elif not store.settings(b)['automatic'] or store.settings(b)['mode'] == 'manual':
        raise ValueError('camera_automatic_disabled')
    if row['expires'] and row['expires'] < store.now():
        raise ValueError('camera_scene_expired')
    if original.get('life_id'):
        life = b.db.execute('SELECT source_event FROM ct_life WHERE id=? AND occurred<=?',
                            (original['life_id'], store.now())).fetchone()
        if not life or not b.db.execute("SELECT 1 FROM source_events WHERE id=? AND status='active'",
                                        (life['source_event'],)).fetchone():
            raise ValueError('camera_source_retired')
    return plan


def plan(b, q):
    original = source(b, q)
    manual = original['source_event'] is not None
    binding = ('user:' + str(original['source_event'])) if manual else ('life:' + original['life_id'])
    previous = b.db.execute('SELECT * FROM lc_job WHERE binding=?', (binding,)).fetchone()
    if previous:
        return dict(ok=True, replayed=True, job=store.public_job(previous))
    config = store.settings(b)
    if not manual and (not config['automatic'] or config['mode'] == 'manual'):
        return dict(ok=True, status='automatic_disabled', job=None)
    if not manual and store.cooldown(b):
        return dict(ok=True, status='cooldown', job=None, seconds=round(store.cooldown(b)))
    expiry = None if manual else store.scene_expiry(original['occurred'])
    if expiry is not None and expiry < store.now():
        return dict(ok=True, status='scene_expired', job=None)
    frame = library.compose(b, q, original)
    at = store.now()
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        previous = b.db.execute('SELECT * FROM lc_job WHERE binding=?', (binding,)).fetchone()
        if previous:
            return dict(ok=True, replayed=True, job=store.public_job(previous))
        identity = 'photo-' + uuid.uuid4().hex
        b.db.execute('INSERT INTO lc_job(id,binding,life_id,manual,status,created,updated,expires,plan) VALUES(?,?,?,?,?,?,?,?,?)',
                     (identity, binding, original['life_id'], int(manual), 'queued', at, at, expiry, store.encode(frame)))
    return dict(ok=True, job=store.public_job(store.get_job(b, identity)),
                scheduler='existing_host_background_runner', generation_started=False)


def reconcile(b):
    from muse_ext.companion import _set
    at = store.now()
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        generation = b.db.execute("UPDATE lc_job SET status='generation_unknown',updated=? WHERE status IN ('claimed','generating') AND updated<?",
                                  (at, at - 900)).rowcount
        sending = b.db.execute("UPDATE lc_job SET status='unknown',updated=? WHERE status='sending' AND updated<?",
                               (at, at - 300)).rowcount
        if sending:
            _set(b, 'life_camera_last_photo', dict(at=at, outcome='unknown'))
    return dict(ok=True, generation_unknown=generation, delivery_unknown=sending,
                replay=False, policy='Reconcile real native receipts. Unknown jobs never auto-retry.')


def work(b):
    reconcile(b)
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        active = b.db.execute("SELECT * FROM lc_job WHERE status IN ('claimed','generating') ORDER BY created LIMIT 1").fetchone()
        if active:
            generation = json.loads(active['generation'])
            return dict(ok=True, status='busy', job=store.public_job(active),
                        native_task_id=generation.get('native_task_id'), generation_started=False)
        queued = b.db.execute("SELECT * FROM lc_job WHERE status='queued' ORDER BY manual DESC,created LIMIT 20").fetchall()
        deferred = None
        for row in queued:
            try:
                frame = valid(b, row)
            except (ValueError, OSError):
                b.db.execute("UPDATE lc_job SET status='stale',updated=? WHERE id=?", (store.now(), row['id']))
                continue
            if not row['manual'] and (store.quiet() or store.cooldown(b)):
                deferred = 'quiet' if store.quiet() else 'cooldown'
                continue
            claim = uuid.uuid4().hex
            generation = dict(claim=claim, claimed_at=store.now())
            b.db.execute("UPDATE lc_job SET status='claimed',generation=?,updated=? WHERE id=?",
                         (store.encode(generation), store.now(), row['id']))
            return dict(ok=True, status='claimed', job=store.public_job(store.get_job(b, row['id'])),
                        claim=claim, request=frame, generation_started=False,
                        next='Bind the actual background task, then invoke the host image tool once with these image inputs.')
    return dict(ok=True, status=deferred or 'empty', job=None)


def claimed(b, q):
    row = store.get_job(b, q.get('id'))
    generation = json.loads(row['generation'])
    if not q.get('claim') or generation.get('claim') != q['claim']:
        raise ValueError('camera_generation_claim_required')
    return row, generation


def bind(b, q):
    worker = library.text(q.get('native_task_id'), 300)
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        row, generation = claimed(b, q)
        previous = generation.get('native_task_id')
        if previous:
            if previous != worker:
                raise ValueError('camera_native_task_conflict')
            return dict(ok=True, replayed=True, job=store.public_job(row))
        if row['status'] != 'claimed':
            raise ValueError('camera_job_not_claimed')
        generation['native_task_id'] = worker
        b.db.execute("UPDATE lc_job SET status='generating',generation=?,updated=? WHERE id=?",
                     (store.encode(generation), store.now(), row['id']))
    return dict(ok=True, job=store.public_job(store.get_job(b, row['id'])))


def rendered(b, q):
    receipt = library.text(q.get('receipt'), 1000)
    row, generation = claimed(b, q)
    if not generation.get('native_task_id') or generation['native_task_id'] != q.get('native_task_id'):
        raise ValueError('camera_native_task_receipt_required')
    if generation.get('receipt'):
        if generation['receipt'] != receipt:
            raise ValueError('camera_generation_receipt_conflict')
        return dict(ok=True, replayed=True, job=store.public_job(row))
    if row['status'] not in ('generating', 'generation_unknown'):
        raise ValueError('camera_generation_not_pending')
    paths = q.get('files')
    if not isinstance(paths, list) or len(paths) != 1 or not isinstance(paths[0], str):
        raise ValueError('camera_one_output_image_required')
    image = library.keep_image(b, paths[0], 'photos')
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        row, generation = claimed(b, q)
        if generation.get('receipt'):
            if generation['receipt'] != receipt:
                raise ValueError('camera_generation_receipt_conflict')
            return dict(ok=True, replayed=True, job=store.public_job(row))
        generation.update(receipt=receipt, images=[image])
        frame = json.loads(row['plan'])
        frame['prompt_sha256'] = hashlib.sha256(frame.pop('prompt').encode()).hexdigest()
        b.db.execute("UPDATE lc_job SET status='ready',generation=?,plan=?,updated=? WHERE id=?",
                     (store.encode(generation), store.encode(frame), store.now(), row['id']))
    return dict(ok=True, job=store.public_job(store.get_job(b, row['id'])), delivered=False)


def failed(b, q):
    receipt = library.text(q.get('receipt'), 1000)
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        row, generation = claimed(b, q)
        if generation.get('native_task_id') != q.get('native_task_id') or not generation.get('native_task_id'):
            raise ValueError('camera_native_task_receipt_required')
        if row['status'] not in ('generating', 'generation_unknown'):
            raise ValueError('camera_generation_not_pending')
        generation.update(receipt=receipt, error=library.text(q.get('error'), 500))
        b.db.execute("UPDATE lc_job SET status='failed',generation=?,updated=? WHERE id=?",
                     (store.encode(generation), store.now(), row['id']))
    return dict(ok=True, job=store.public_job(store.get_job(b, row['id'])))


def send_work(b):
    reconcile(b)
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        if b.db.execute("SELECT 1 FROM lc_job WHERE status='sending' LIMIT 1").fetchone():
            return dict(ok=True, job=None, status='sending')
        rows = b.db.execute("SELECT * FROM lc_job WHERE status='ready' ORDER BY manual DESC,created LIMIT 20").fetchall()
        deferred = None
        for row in rows:
            try:
                frame = valid(b, row)
                images = [library.verified(b, image) for image in json.loads(row['generation'])['images']]
            except (ValueError, OSError):
                b.db.execute("UPDATE lc_job SET status='stale',updated=? WHERE id=?", (store.now(), row['id']))
                continue
            if not row['manual'] and (store.quiet() or store.cooldown(b)):
                deferred = 'quiet' if store.quiet() else 'cooldown'
                continue
            claim = uuid.uuid4().hex
            delivery = dict(claim=claim, started_at=store.now())
            b.db.execute("UPDATE lc_job SET status='sending',delivery=?,updated=? WHERE id=?",
                         (store.encode(delivery), store.now(), row['id']))
            return dict(ok=True, job=store.public_job(store.get_job(b, row['id'])),
                        claim=claim, images=images, caption=frame['caption'], source=frame['source'],
                        next='Send once through the existing owner main-chat route. Settle using its actual receipt.')
    return dict(ok=True, status=deferred or 'empty', job=None)


def settle(b, q):
    from muse_ext.companion import _get, _set
    outcome = q.get('outcome')
    if outcome not in ('accepted', 'unknown', 'failed'):
        raise ValueError('camera_delivery_outcome_required')
    if not isinstance(q.get('receipt'), str) or not q['receipt'].strip():
        raise ValueError('camera_delivery_receipt_required')
    receipt = library.text(q.get('receipt'), 1000)
    replayed = False
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        row = store.get_job(b, q.get('id'))
        delivery = json.loads(row['delivery'])
        if not q.get('claim') or delivery.get('claim') != q['claim']:
            raise ValueError('camera_delivery_claim_required')
        if row['status'] in ('accepted', 'unknown', 'failed') and delivery.get('receipt'):
            if row['status'] == outcome and delivery['receipt'] == receipt:
                replayed = True
            elif row['status'] == 'unknown' and outcome in ('accepted', 'failed'):
                delivery['previous_unknown_receipt'] = delivery['receipt']
            else:
                raise ValueError('camera_delivery_receipt_conflict')
        elif row['status'] not in ('sending', 'unknown'):
            raise ValueError('camera_delivery_not_pending')
        if not replayed:
            delivery.update(receipt=receipt, settled_at=store.now(), outcome=outcome)
            b.db.execute('UPDATE lc_job SET status=?,delivery=?,updated=? WHERE id=?',
                         (outcome, store.encode(delivery), store.now(), row['id']))
            if outcome in ('accepted', 'unknown'):
                _set(b, 'life_camera_last_photo', dict(at=store.now(), outcome=outcome))
    # Retry after a crash completes this compatibility receipt without another send.
    original = json.loads(row['plan'])['source']
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        promises = _get(b, 'life_photo_requests', [])
        promise = next((p for p in promises if p.get('source_event') == original.get('source_event')), None)
        if promise and promise['status'] in ('pending', 'unknown'):
            promise.update(status=outcome, settled_at=store.now(), receipt=receipt,
                           photo_job_id=row['id'], receipt_evidence='camera_job_verified_host_receipt')
            _set(b, 'life_photo_requests', promises)
    return dict(ok=True, replayed=replayed, job=store.public_job(store.get_job(b, row['id'])))
