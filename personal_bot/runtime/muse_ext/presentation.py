"""Live persona and camera context. No model, image generation or outbound API."""
import hashlib
import json
import math
from pathlib import Path


def profile(b):
    path = b.root / 'presentation-profile.json'
    if not path.exists():
        return {}
    if path.stat().st_size > 8192:
        raise ValueError('presentation_profile_too_large')
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError('presentation_profile_object_required')
    return value


def persona(b, scope='owner-private'):
    """Read the configured operator-owned file on EVERY prepare, not L3 memory."""
    try:
        config = profile(b)
        value = config.get('persona_file') if scope == 'owner-private' else config.get('public_persona_file')
        if not value and scope != 'owner-private':
            return dict(status='not_configured')
        path = Path(value or b.root / 'PERSONA.md')
        if not path.is_absolute():
            path = b.root / path
        if not path.exists():
            return dict(status='not_configured')
        if path.stat().st_size > 24000:
            return dict(status='too_large', content='', recommendation='keep persona concise; put tool procedures in the canonical protocol')
        data = path.read_bytes()
        text = data.decode('utf-8-sig')
        return dict(status='loaded', sha256=hashlib.sha256(data).hexdigest(),
                    content=text[:2400], truncated=len(text) > 2400,
                    authority='current persona and voice only; no new permissions; historical style examples are not current rules')
    except (OSError, ValueError, TypeError):
        return dict(status='unavailable', content='')


def _completion(b, started):
    from muse_ext.companion import stamp
    next_start = b.db.execute("SELECT min(occurred) FROM ct_life WHERE activity=? AND stage='started' AND occurred>?",
                              (started['activity'], started['occurred'])).fetchone()[0]
    return b.db.execute("SELECT id,stage,description,occurred,origin FROM ct_life WHERE activity=? "
                        "AND stage='completed' AND occurred>=? AND occurred<? AND occurred<=? ORDER BY occurred LIMIT 1",
                        (started['activity'], started['occurred'], next_start or float('inf'), stamp())).fetchone()


def camera(b, scope):
    from muse_ext.companion import _get, stamp
    if scope != 'owner-private':
        return dict(enabled=False)
    try:
        config = profile(b)
    except (OSError, ValueError, TypeError):
        return dict(enabled=False, status='configuration_unavailable')
    if config.get('life_photos') is not True:
        return dict(enabled=False)
    now = stamp()
    activity = _get(b, 'life', {}).get('activity')
    timing = None
    if activity:
        start, end = activity.get('started_at'), activity.get('ends_at')
        if all(isinstance(x, (int, float)) and math.isfinite(x) for x in (start, end)):
            timing = dict(activity=activity['name'], started_at=start, ends_at=end,
                          elapsed_seconds=max(0, now-start), remaining_seconds=max(0, end-now),
                          stage='in_progress' if now < end else 'awaiting_completion_record')
    milestones = [dict(r) for r in b.db.execute(
        "SELECT id,activity,stage,description,occurred,origin FROM ct_life ORDER BY occurred DESC LIMIT 4")]
    requests = []
    for item in _get(b, 'life_photo_requests', []):
        if item.get('status') != 'pending':
            continue
        source = b.db.execute("SELECT id FROM source_events WHERE id=? AND scope='owner-private' AND actor='user' AND status='active'",
                              (item['source_event'],)).fetchone()
        started = b.db.execute("SELECT * FROM ct_life WHERE id=? AND stage='started'", (item['activity_id'],)).fetchone()
        if not source or not started:
            continue
        completed = _completion(b, started)
        requests.append(dict(item, ready=item['when'] == 'now' or completed is not None,
                             completed=dict(completed) if completed else None))
    return dict(enabled=True, activity=timing, recent_milestones=milestones, photo_requests=requests,
                guide=config.get('camera_guide', ''), references=config.get('character_references', []),
                policy='Use the current activity stage, reference art and a physically possible rear/selfie/mirror view. '
                       'Describe only visible body parts. Elapsed time is not a completion record. '
                       'A started row stays started; a separate completed row closes the activity. '
                       'Life pictures are generated illustrations of virtual experiences, not real camera evidence.')


def photo(b, q):
    """A user photo promise tied to a real source and life cycle; uses existing tasks."""
    from muse_ext.companion import _get, _set, stamp
    if q.get('scope') != 'owner-private':
        raise ValueError('owner_private_photo_request_required')
    action = q.get('action', 'request')
    source_id = q.get('source_event')
    if type(source_id) is not int:
        raise ValueError('real_photo_request_source_required')
    source = b.db.execute("SELECT id FROM source_events WHERE id=? AND scope=? AND actor='user' AND status='active'",
                          (source_id, q['scope'])).fetchone()
    if not source:
        raise ValueError('real_photo_request_source_required')
    if profile(b).get('life_photos') is not True:
        return dict(ok=False, error='life_photos_not_enabled')
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        entries = _get(b, 'life_photo_requests', [])
        previous = next((v for v in entries if v['source_event'] == source_id), None)
        if action == 'request':
            camera_mode, when = q.get('camera', 'rear'), q.get('when', 'completed')
            if camera_mode not in ('rear', 'selfie', 'mirror') or when not in ('now', 'completed'):
                raise ValueError('invalid_photo_camera_or_stage')
            row = b.db.execute("SELECT id FROM ct_life WHERE id=? AND stage='started'", (q.get('activity_id'),)).fetchone()
            if not row:
                raise ValueError('real_started_activity_required')
            desired = dict(source_event=source_id, activity_id=row['id'], camera=camera_mode, when=when)
            if previous:
                same = all(previous[k] == v for k, v in desired.items())
                return dict(ok=same, replayed=True, status='replayed' if same else 'conflict', request=previous)
            if sum(x['status'] == 'pending' for x in entries) >= 8:
                raise ValueError('too_many_pending_photo_requests')
            current = dict(desired, status='pending', created_at=stamp())
            entries.append(current)
        elif action == 'settle':
            if not previous:
                raise ValueError('photo_request_not_found')
            outcome = q.get('outcome')
            if outcome not in ('accepted', 'unknown', 'failed'):
                raise ValueError('invalid_photo_delivery_outcome')
            if previous['status'] != 'pending':
                return dict(ok=previous['status'] == outcome, replayed=True, request=previous)
            if outcome == 'accepted' and previous['when'] == 'completed':
                started = b.db.execute("SELECT * FROM ct_life WHERE id=?", (previous['activity_id'],)).fetchone()
                if not started or not _completion(b, started):
                    raise ValueError('photo_milestone_not_completed')
            current = previous
            current.update(status=outcome, settled_at=stamp(), receipt_evidence='host_reported_delivery_outcome')
        else:
            raise ValueError('invalid_photo_request_action')
        pending = [x for x in entries if x['status'] == 'pending']
        settled = [x for x in entries if x['status'] != 'pending'][-24:]
        _set(b, 'life_photo_requests', settled + pending)
    return dict(ok=True, request=current, scheduler='existing_life_task_only_no_new_task_created')
