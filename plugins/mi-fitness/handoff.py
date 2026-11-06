"""Authenticated, recipient-bound one-time credential handoff; no network."""
import base64
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import secrets
import time

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALLOWED = ['sleep', 'steps', 'activity_daily', 'workouts']
FORMAT = 'muse-mi-fitness-handoff-v1'


def fingerprint(key):
    return hashlib.sha256(key.public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)).hexdigest()


def identifiers(transfer_id, expected):
    if not re.fullmatch('[a-f0-9]{32}', transfer_id or '') or not re.fullmatch('[a-f0-9]{64}', expected or ''):
        raise ValueError('invalid_handoff_identifiers')


def recipient_key(public_pem, expected):
    key = serialization.load_pem_public_key(public_pem)
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072 or fingerprint(key) != expected:
        raise ValueError('recipient_key_mismatch')
    return key


def seal_session(session, public_pem, transfer_id, expected, now=None):
    identifiers(transfer_id, expected)
    key = recipient_key(public_pem, expected)
    now = time.time() if now is None else now
    value = {'schema': FORMAT, 'scope': 'owner-private', 'allowed': ALLOWED,
             'created_at': now, 'expires_at': now + 3600,
             'session': asdict(session) if not isinstance(session, dict) else session}
    aes, iv = secrets.token_bytes(32), secrets.token_bytes(12)
    aad = f'{FORMAT}:{transfer_id}:{expected}'.encode()
    ciphertext = AESGCM(aes).encrypt(iv, json.dumps(value, separators=(',', ':')).encode(), aad)
    wrapped = key.encrypt(aes, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return {'version': 1, 'algorithm': 'RSA-OAEP-SHA256+AES-256-GCM',
            'transfer_id': transfer_id, 'recipient_sha256': expected,
            'encrypted_key': base64.b64encode(wrapped).decode(),
            'iv': base64.b64encode(iv).decode(), 'ciphertext': base64.b64encode(ciphertext).decode()}


def unseal(envelope, private_pem, transfer_id, expected, now=None):
    identifiers(transfer_id, expected)
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < 3072 or fingerprint(key.public_key()) != expected:
        raise ValueError('recipient_key_mismatch')
    if (envelope.get('version') != 1 or envelope.get('algorithm') != 'RSA-OAEP-SHA256+AES-256-GCM'
            or envelope.get('transfer_id') != transfer_id or envelope.get('recipient_sha256') != expected):
        raise ValueError('handoff_binding_mismatch')
    unwrap = lambda name: base64.b64decode(envelope[name], validate=True)
    aes = key.decrypt(unwrap('encrypted_key'), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    aad = f'{FORMAT}:{transfer_id}:{expected}'.encode()
    value = json.loads(AESGCM(aes).decrypt(unwrap('iv'), unwrap('ciphertext'), aad))
    now = time.time() if now is None else now
    if (value.get('schema') != FORMAT or value.get('scope') != 'owner-private' or value.get('allowed') != ALLOWED
            or not isinstance(value.get('created_at'), (int, float))
            or not value['created_at'] - 60 <= now <= value.get('expires_at', 0)
            or value['expires_at'] - value['created_at'] > 3600):
        raise ValueError('expired_or_invalid_handoff')
    session = value['session']
    fields = {'user_id', 'c_user_id', 'service_token', 'ssecurity', 'region', 'created_at',
              'extra_cookies', 'pass_token', 'device_id', 'renewed_at'}
    if (not isinstance(session, dict) or set(session) - fields or session.get('region') != 'cn'
            or not all(isinstance(session.get(k), str) and session[k].strip()
                       for k in ('user_id', 'c_user_id', 'service_token', 'ssecurity', 'created_at'))):
        raise ValueError('invalid_health_session')
    return session


def import_envelope(root, envelope_path, key_path, transfer_id, expected):
    from bridge import atomic
    identifiers(transfer_id, expected)
    receipt = root / 'import-receipt.json'
    if receipt.exists() and json.loads(receipt.read_text())['transfer_id'] == transfer_id:
        return {'ok': True, 'status': 'already_imported', 'credentials_emitted': False}
    source, private = Path(envelope_path), Path(key_path)
    if source.is_symlink() or private.is_symlink() or source.stat().st_size > 65536:
        raise ValueError('invalid_handoff_file')
    session = unseal(json.loads(source.read_text(encoding='utf-8')), private.read_bytes(), transfer_id, expected)
    atomic(root / 'session.json', session)
    atomic(receipt, {'transfer_id': transfer_id, 'recipient_sha256': expected, 'imported_at': time.time()})
    private.unlink()  # Owned, one-time key; the session is already written atomically.
    return {'ok': True, 'status': 'imported', 'allowed': ALLOWED,
            'credentials_emitted': False, 'one_time_key_removed': True}
