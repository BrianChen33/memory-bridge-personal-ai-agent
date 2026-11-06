"""Run on the owner's computer; save only a recipient-encrypted session."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

import qrcode
from qrcode.image.pure import PyPNGImage
from mifit.auth.qr import login_qr
from mifit.errors import NotificationRequiredError
from handoff import seal_session, recipient_key, identifiers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-key', required=True)
    parser.add_argument('--transfer-id', required=True)
    parser.add_argument('--fingerprint', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    folder = Path(args.output_dir).resolve()
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    public = Path(args.public_key).read_bytes()
    identifiers(args.transfer_id, args.fingerprint)
    recipient_key(public, args.fingerprint)  # Refuse a wrong recipient before asking the user to scan.
    qr_path = folder / 'login-qr.png'

    def show(login_url, ignored):
        parsed = urlparse(login_url)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not (host == 'account.xiaomi.com' or host.endswith('.account.xiaomi.com')):
            raise ValueError('unexpected_login_host')
        code = qrcode.QRCode(box_size=8, border=4, image_factory=PyPNGImage)
        code.add_data(login_url)
        code.make(fit=True)
        with qr_path.open('wb') as stream:
            code.make_image().save(stream)
        print(json.dumps({'status': 'waiting_for_phone', 'qr_file': str(qr_path)}), flush=True)

    try:
        # The session including renewal credentials is never written in plaintext.
        session = login_qr(on_qr=show)
        session.region = 'cn'
        envelope = seal_session(session, public, args.transfer_id, args.fingerprint)
        target = folder / 'muse-mi-fitness-session.sealed.json'
        with target.open('x', encoding='utf-8') as out:
            json.dump(envelope, out, separators=(',', ':'))
        print(json.dumps({'status': 'sealed', 'file': str(target), 'credentials_saved_in_plaintext': False}), flush=True)
    finally:
        if qr_path.exists():
            qr_path.unlink()


if __name__ == '__main__':
    try:
        main()
    except NotificationRequiredError:
        print(json.dumps({'ok': False, 'status': 'phone_security_confirmation_required'}), flush=True)
        raise SystemExit(2) from None
    except Exception as exc:
        print(json.dumps({'ok': False, 'status': 'local_login_failed', 'error_type': type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
