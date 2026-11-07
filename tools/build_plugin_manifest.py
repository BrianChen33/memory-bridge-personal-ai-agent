"""Seal explicitly shipped optional plugin files; no credentials or runtime data."""
import hashlib
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plugin', choices=['social-reading', 'life-camera'], default='social-reading')
    args = parser.parse_args()
    folder = ROOT / 'plugins' / args.plugin
    paths = sorted(p for p in folder.iterdir() if p.is_file() and p.name != 'manifest.json')
    camera = args.plugin == 'life-camera'
    data = dict(id=args.plugin, name='生活相机' if camera else '阅读与成长',
                version='0.1.0' if camera else '0.4.0', api=1,
                source='https://github.com/aa1355721445-lgtm/dsh-image-studio' if camera else 'https://github.com/referiw/dsh-plugin-tieba',
                reference_commit='fbd8f662f29546c2574a21f8c17ae1bc68c9498a' if camera else '568cc4d75dc92984ec3cf625241e47a7f9c244d4',
                files={p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest() for p in paths})
    (folder / 'manifest.json').write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())
    print('Sealed', args.plugin, ':', len(paths), 'files; optional, not bundled into the core wheel.')


if __name__ == '__main__':
    main()
