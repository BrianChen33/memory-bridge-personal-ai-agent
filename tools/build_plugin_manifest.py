"""Seal explicitly shipped optional plugin files; no credentials or runtime data."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / 'plugins/social-reading'
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.name != 'manifest.json')
    data = dict(id='social-reading', name='阅读与成长', version='0.1.0', api=1,
                source='https://github.com/referiw/dsh-plugin-tieba',
                reference_commit='568cc4d75dc92984ec3cf625241e47a7f9c244d4',
                files={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (folder / 'manifest.json').write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
    print('Sealed social-reading:', len(paths), 'files; optional, not bundled into the core wheel.')


if __name__ == '__main__':
    main()
