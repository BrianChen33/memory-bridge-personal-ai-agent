"""Read-only home-panel enrichment. Artwork and persona stay in the private root."""
import base64
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import quote

from muse_ext.emotion_catalog import LABELS, schema

ART_KEYS = ('happy', 'curious', 'relaxed', 'sad', 'angry', 'tired', 'affection', 'reading')
PROFILE_KEYS = ('title', 'short_name', 'nickname', 'tagline', 'greeting', 'presence', 'room_hint')
FALLBACK = 'data:image/svg+xml,' + quote('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160"><circle cx="80" cy="80" r="65" fill="#e4ecd6"/><path d="M34 83c4-25 39-35 61-17 12 8 25 3 29-9 4 35-20 54-45 54-24 0-40-10-45-28Z" fill="#a7bb94"/><circle cx="55" cy="80" r="3" fill="#496343"/></svg>')


def read_json(path, limit=65536):
    path = Path(path)
    if not path.exists():
        return {}
    if path.stat().st_size > limit:
        raise ValueError('panel_configuration_too_large')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('panel_configuration_object_required')
    return data


def artwork(root):
    folder = (Path(root) / 'assets' / 'panel').resolve()
    config = read_json(folder / 'manifest.json')
    result = {'items': {}, 'attribution': config.get('attribution', {}), 'configured': False}
    entries = config.get('items', {})
    if not isinstance(entries, dict):
        raise ValueError('panel_art_items_object_required')
    total = 0
    for key in ART_KEYS:
        entry = entries.get(key)
        if entry is None:
            result['items'][key] = {'data_uri': FALLBACK, 'caption': '尚未配置这一类表情。'}
            continue
        if not isinstance(entry, dict) or not isinstance(entry.get('file'), str):
            raise ValueError('invalid_panel_art_entry')
        path = (folder / entry['file']).resolve()
        if not path.is_relative_to(folder) or path == folder:
            raise ValueError('panel_art_outside_root')
        if path.stat().st_size > 3_000_000:
            raise ValueError('panel_art_too_large')
        blob = path.read_bytes()
        total += len(blob)
        if total > 12_000_000:
            raise ValueError('panel_art_budget_exceeded')
        mime = ('image/gif' if blob[:6] in (b'GIF89a', b'GIF87a') else
                'image/png' if blob.startswith(b'\x89PNG\r\n\x1a\n') else
                'image/webp' if blob[:4] == b'RIFF' and blob[8:12] == b'WEBP' else None)
        if not mime:
            raise ValueError('unsupported_panel_art_type')
        if entry.get('sha256') and hashlib.sha256(blob).hexdigest() != entry['sha256']:
            raise ValueError('panel_art_hash_mismatch')
        result['items'][key] = {
            'data_uri': 'data:' + mime + ';base64,' + base64.b64encode(blob).decode('ascii'),
            'caption': str(entry.get('caption', ''))[:200],
            'source': str(entry.get('source', ''))[:500],
        }
        result['configured'] = True
    return result


def enrich(b, snapshot):
    """Project existing state only; never capture events, draw stickers, or appraise."""
    from muse_ext.plugins import panel
    snapshot['plugins'] = panel(b)
    from muse_ext.life_routine import settings as life_settings, pending as phone_pending
    snapshot['life_routine'] = life_settings(b)
    snapshot['phone'] = phone_pending(b)
    snapshot['formal_entry_health'] = read_json(b.root / 'state' / 'formal-entry-health.json')
    snapshot['reply_driver_health'] = read_json(b.root / 'state' / 'reply-driver-health.json')
    from muse_ext.feedback import status as feedback_status
    snapshot['feedback_health']=feedback_status(b)
    from muse_ext.life_projects import view as activity_view
    snapshot['activity_project']=activity_view(b)
    profile = read_json(b.root / 'panel-profile.json')
    snapshot['panel_profile'] = {k: profile[k][:200] for k in PROFILE_KEYS if isinstance(profile.get(k), str)}
    voice = profile.get('voice', {})
    snapshot['panel_profile']['voice'] = {k: voice[k][:200] for k in ART_KEYS if isinstance(voice, dict) and isinstance(voice.get(k), str)}
    snapshot['emotion_catalog'] = schema()
    from muse_ext.emotion_full48 import latest
    snapshot['emotion_assessment'] = latest(b,'owner-private')
    values = {}
    now = snapshot['generated_at']
    for row in b.db.execute('''SELECT e.label,e.intensity,e.at,c.half FROM emotion e
          LEFT JOIN ct_label c ON c.scope=e.scope AND c.label=e.label WHERE e.scope=?''', ('owner-private',)):
        if row['label'] not in LABELS:
            continue
        half = row['half'] if row['half'] is not None else .75
        if half <= 0 or not all(math.isfinite(v) for v in (row['intensity'], row['at'], half)):
            continue
        values[row['label']] = round(row['intensity'] * .5 ** (max(0, now-row['at'])/(half*3600)), 6)
    if snapshot['emotion_assessment']:
        for label in LABELS:
            values.setdefault(label, 0.0)  # full48 explicitly assessed the implicit-zero baseline
    snapshot['mood']['labels'] = sorted(
        [{'label': label, 'intensity': values.get(label)} for label in LABELS],
        key=lambda item: -(item['intensity'] if item['intensity'] is not None else -1))
    snapshot['panel_art'] = artwork(b.root)
    snapshot['preview'] = False
    snapshot['panel_schedule'] = read_json(b.root / 'state' / 'panel-update.json')
    schedule = snapshot['panel_schedule']
    if schedule.get('due_at'):
        schedule['next_at'] = schedule['due_at']+schedule.get('cadence_seconds',1800) if now >= schedule['due_at'] else schedule['due_at']
        schedule['next_estimated'] = now >= schedule['due_at']
    # An absent host policy remains unknown, rather than borrowing a demo probability.
    policy = read_json(b.root / 'state' / 'panel-sticker-policy.json') or read_json(b.root / 'expression-policy.json')
    snapshot['sticker_policy'] = {k: policy[k] for k in ('enabled', 'base_probability', 'maximum_probability') if k in policy}
    recent = b.db.execute('''SELECT a.payload FROM ct_appraisal a JOIN source_events e ON e.id=a.event
           WHERE e.scope=? AND e.status='active' ORDER BY a.at DESC LIMIT 1''', ('owner-private',)).fetchone()
    snapshot['reaction_note'] = '暂时没有本场景的情绪评估记录。'
    if recent:
        raw = json.loads(recent['payload'])
        feeling = (raw.get('appraisal') or {}).get('feeling', '')
        snapshot['reaction_note'] = str(feeling)[:160] if feeling else ('最近一轮有情绪变化。' if raw.get('changed') else '最近一轮评估没有新增情绪变化。')
    return snapshot
