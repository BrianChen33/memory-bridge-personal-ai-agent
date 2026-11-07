"""Hash-addressed private art. Original references always retain their quota."""
import hashlib
import json
from pathlib import Path
import re

from . import store

CATEGORIES = ('characters', 'outfits', 'scenes', 'props')


def text(value, limit, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('invalid_camera_text')
    return value.strip()


def image_bytes(source):
    path = Path(source).expanduser().absolute()
    if any(part.is_symlink() for part in (path, *path.parents)) or not path.is_file():
        raise ValueError('camera_reference_regular_file_required')
    if not 16 <= path.stat().st_size <= 12 * 1024 * 1024:
        raise ValueError('camera_reference_size_limit')
    data = path.read_bytes()
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return data, '.png'
    if data.startswith(b'\xff\xd8\xff'):
        return data, '.jpg'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return data, '.webp'
    raise ValueError('camera_reference_png_jpeg_webp_required')


def keep_image(b, source, collection='references'):
    from muse_ext.plugins import copy_bytes
    data, suffix = image_bytes(source)
    digest = hashlib.sha256(data).hexdigest()
    relative = f'assets/life-camera/{collection}/{digest}{suffix}'
    target = b.root / relative
    if any(part.is_symlink() for part in (target, *target.parents)):
        raise ValueError('camera_reference_symlink_refused')
    if not target.exists():
        copy_bytes(Path(source).expanduser().absolute(), target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError('camera_reference_changed_during_copy')
    return dict(file=relative, sha256=digest, bytes=len(data))


def verified(b, image):
    relative = Path(image['file'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('camera_reference_path_refused')
    target = b.root / relative
    data, _ = image_bytes(target)
    if hashlib.sha256(data).hexdigest() != image['sha256']:
        raise ValueError('camera_reference_hash_mismatch')
    return dict(path=str(target.absolute()), sha256=image['sha256'])


def put(b, q):
    category, identity = q.get('category'), q.get('id')
    if (q.get('authorized') is not True or category not in CATEGORIES or
            not isinstance(identity, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', identity)):
        raise ValueError('authorized_camera_asset_required')
    paths = q.get('images')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 4 or not all(isinstance(p, str) for p in paths):
        raise ValueError('camera_asset_images_required')
    payload = dict(category=category, id=identity, name=text(q.get('name'), 100),
                   description=text(q.get('description', ''), 1600, False),
                   images=[keep_image(b, p) for p in paths])
    payload['revision'] = hashlib.sha256(store.encode(payload).encode()).hexdigest()
    with b.db:
        b.db.execute('INSERT OR REPLACE INTO lc_asset VALUES(?,?,?)', (category, identity, store.encode(payload)))
    return dict(ok=True, id=identity, revision=payload['revision'], images=len(paths))


def get(b, category, identity):
    row = b.db.execute('SELECT payload FROM lc_asset WHERE category=? AND id=?', (category, identity)).fetchone()
    if not row:
        raise ValueError('camera_reference_not_found')
    return json.loads(row[0])


def listing(b, q):
    category = q.get('category')
    if category is not None and category not in CATEGORIES:
        raise ValueError('camera_asset_category_required')
    query = text(q.get('query', ''), 100, False).casefold()
    rows = b.db.execute('SELECT payload FROM lc_asset WHERE (? IS NULL OR category=?) ORDER BY category,id LIMIT 100',
                        (category, category))
    result = []
    for row in rows:
        item = json.loads(row[0])
        if query and query not in (item['name'] + ' ' + item['description']).casefold():
            continue
        item['images'] = [verified(b, image) for image in item['images']]
        result.append(item)
        if len(result) == 20:
            break
    return dict(ok=True, items=result)


def compose(b, q, source):
    config = store.settings(b)
    character = get(b, 'characters', config['character_id'])
    promised = source.get('promised_camera')
    if promised and q.get('camera', promised) != promised:
        raise ValueError('camera_explicit_promise_camera_conflict')
    camera = q.get('camera', promised or config['camera_preference'])
    if camera not in ('selfie', 'rear', 'mirror'):
        raise ValueError('model_camera_choice_required')
    frame = text(q.get('prompt'), 1400)
    caption = text(q.get('caption', ''), 180, False)
    parts = [
        'Use the attached original three-view character artwork as the canonical identity and drawing-style reference.',
        'Match its face, eyes, hair, proportions, distinctive anatomy, costume and linework. Compose one new illustrated scene.',
        'Released life stage: ' + source['description'],
        'Scene: ' + frame,
        'Character appearance: ' + character['description'],
    ]
    views = dict(
        selfie='An arm-length casual front-camera selfie. The phone is outside the frame. One character, with physically possible hands.',
        rear='A rear-camera POV of the objects ahead, using the reference drawing style. Only explicitly requested body parts enter the frame. The camera holder stays behind the camera.',
        mirror='A mirror selfie with one real mirror in the scene and one consistent reflected character. Specify the phone and reflection direction.')
    parts.append(views[camera])
    for field in ('expression', 'pose', 'light'):
        value = text(q.get(field, ''), 240, False)
        if value:
            parts.append(field + ': ' + value)
    parts.append('Use the present emotion for expression. Clothing and scene follow this released event. Render a single image, without sheet panels or copied reference labels.')
    refs = []
    # The first image is always the owner's original character sheet.
    for image in character['images'][:2]:
        refs.append(dict(role='identity_style', **verified(b, image)))
    continuity = q.get('continuity_job')
    if continuity:
        old = store.get_job(b, continuity)
        old_plan = json.loads(old['plan'])
        if old['status'] != 'accepted' or old_plan['identity_revision'] != character['revision']:
            raise ValueError('camera_continuity_requires_delivered_same_identity')
        outputs = json.loads(old['generation']).get('images', [])
        if outputs:
            refs.append(dict(role='scene_continuity_only', **verified(b, outputs[0])))
            parts.append('The continuity photo supplies setting/layout only. The original character sheet determines identity.')
    selected = [('outfits', q.get('outfit')), ('scenes', q.get('scene'))]
    props = q.get('props', [])
    if not isinstance(props, list) or len(props) > 3 or not all(isinstance(p, str) for p in props):
        raise ValueError('invalid_camera_props')
    selected.extend(('props', p) for p in props)
    for category, identity in selected:
        if not identity:
            continue
        asset = get(b, category, identity)
        parts.append(category + ': ' + asset['description'])
        if len(refs) < config['max_references']:
            refs.append(dict(role=category, **verified(b, asset['images'][0])))
    refs = refs[:config['max_references']]
    return dict(camera=camera, caption=caption, prompt='\n'.join(parts), references=refs,
                aspect='3:4' if camera != 'rear' else '4:3', identity_revision=character['revision'],
                character_id=character['id'], source=source, count=1, origin='generated_virtual_illustration')


def validate_plan(b, plan):
    character = get(b, 'characters', store.settings(b)['character_id'])
    if character['revision'] != plan['identity_revision']:
        raise ValueError('camera_reference_revision_changed')
    for image in plan['references']:
        # Stored paths were produced from private, hash-addressed files.
        data, _ = image_bytes(image['path'])
        if hashlib.sha256(data).hexdigest() != image['sha256']:
            raise ValueError('camera_reference_hash_mismatch')
