"""One-time panel-only animated WebP conversion; requires ffmpeg, not a chat hook.

Private artwork stays in STATE/assets/panel. The original chat sticker library
is never read or modified. Refreshing the HTML needs no ffmpeg or image package.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid


KEYS = ('happy', 'curious', 'relaxed', 'sad', 'angry', 'tired', 'affection', 'reading')


def compact(root, side=160, fps=8, quality=55):
    if not 64 <= side <= 512 or not 1 <= fps <= 30 or not 1 <= quality <= 100:
        raise ValueError('invalid_panel_encoding_options')
    binary = shutil.which('ffmpeg')
    if not binary:
        raise RuntimeError('ffmpeg_required_for_one_time_panel_conversion')
    folder = (Path(root) / 'assets' / 'panel').resolve()
    manifest = folder / 'manifest.json'
    config = json.loads(manifest.read_text(encoding='utf-8'))
    encoding = {'format': 'webp', 'max_side': side, 'fps': fps, 'quality': quality}
    before = after = updated = 0
    for key in KEYS:
        entry = config.get('items', {}).get(key)
        if entry is None:
            continue
        source = (folder / entry['file']).resolve()
        if not source.is_relative_to(folder) or source == folder:
            raise ValueError('panel_art_outside_root')
        original = source.read_bytes()
        digest = hashlib.sha256(original).hexdigest()
        if entry.get('sha256') and digest != entry['sha256']:
            raise ValueError('panel_art_hash_mismatch')
        before += len(original)
        if entry.get('panel_encoding') == encoding and original[:4] == b'RIFF' and original[8:12] == b'WEBP':
            after += len(original)
            continue
        destination = folder / (key + '.webp')
        temp = folder / ('.' + key + '.' + uuid.uuid4().hex + '.webp')
        try:
            subprocess.run([
                binary, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
                '-vf', f'fps={fps},scale={side}:{side}:force_original_aspect_ratio=decrease:flags=lanczos',
                '-an', '-c:v', 'libwebp_anim', '-lossless', '0', '-q:v', str(quality),
                '-compression_level', '4', '-loop', '0', str(temp),
            ], check=True, capture_output=True, timeout=120)
            data = temp.read_bytes()
            if data[:4] != b'RIFF' or data[8:12] != b'WEBP' or len(data) > 3_000_000:
                raise ValueError('invalid_compact_panel_art')
            os.chmod(temp, 0o600)
            os.replace(temp, destination)
        finally:
            if temp.exists():
                temp.unlink()
        entry.setdefault('source_sha256', digest)
        entry.update(file=destination.name, sha256=hashlib.sha256(data).hexdigest(), panel_encoding=encoding)
        after += len(data)
        updated += 1
    temp = folder / ('.manifest.' + uuid.uuid4().hex + '.json')
    try:
        temp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chmod(temp, 0o600)
        os.replace(temp, manifest)
    finally:
        if temp.exists():
            temp.unlink()
    return {'ok': True, 'updated': updated, 'before_bytes': before, 'after_bytes': after,
            'saved_percent': round(100 * (1 - after / before), 1) if before else 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--side', type=int, default=160)
    parser.add_argument('--fps', type=int, default=8)
    parser.add_argument('--quality', type=int, default=55)
    args = parser.parse_args()
    print(json.dumps(compact(args.root, args.side, args.fps, args.quality), ensure_ascii=False))
