"""Official source identities; authorization never comes from a webpage."""
import hashlib
import json
import re
import time
import unicodedata
from urllib.parse import parse_qs, quote, unquote, urlsplit

PROVIDERS = {
    'tieba': dict(state='implemented_native_browser_adapter', hosts=['tieba.baidu.com'],
                  features=['bar_list', 'floors', 'replies', 'image_references', 'sampling', 'cache']),
    'bilibili': dict(state='planned_not_enabled', hosts=['www.bilibili.com', 'space.bilibili.com'],
                     evidence=['metadata', 'subtitles', 'observed_video_spans', 'observed_audio_spans']),
    'douyin': dict(state='planned_not_enabled', hosts=['www.douyin.com'],
                   evidence=['metadata', 'subtitles', 'observed_video_spans', 'observed_audio_spans']),
}


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('invalid_bounded_text')
    return value.strip()


def optional_text(value, limit):
    return text('' if value is None else value, limit)


def official_url(value, hosts=('tieba.baidu.com',)):
    value = text(value, 1600, True)
    p = urlsplit(value)
    if (p.scheme != 'https' or p.hostname not in hosts or p.username or p.password or
            p.port not in (None, 443) or any(c in value for c in ('\r', '\n', '\\'))):
        raise ValueError('official_https_url_required')
    return p


def name_key(value):
    value = unicodedata.normalize('NFKC', value).strip()
    return value.casefold().strip()


def canonical(value):
    value = text(value, 1600, True)
    if '://' in value:
        p = official_url(value)
        if p.path not in ('/f', '/f/'):
            raise ValueError('forum_link_required_not_thread_link')
        params = parse_qs(p.query)
        if len(params.get('kw', [])) != 1:
            raise ValueError('single_forum_name_required')
        name = params['kw'][0]
    else:
        if any(c in value for c in '/?&#:@\\'):
            raise ValueError('invalid_forum_name')
        name = value[:-1] if value.endswith('吧') else value
    name = unicodedata.normalize('NFKC', text(name, 80, True))
    if any(ord(c) < 32 or c == '\ufffd' for c in name):
        raise ValueError('invalid_forum_name_encoding')
    return dict(name=name, key=name_key(name), url='https://tieba.baidu.com/f?kw=' + quote(name) + '&ie=utf-8')


def owner_event(b, q, input_value=None):
    if type(q.get('owner_event')) is not int or q.get('authorized') is not True:
        raise ValueError('explicit_owner_authorization_source_required')
    event = b.db.execute("SELECT * FROM source_events WHERE id=? AND actor='user' AND scope='owner-private' AND status='active'",
                         (q['owner_event'],)).fetchone()
    if not event or event['text'].lstrip().startswith('［Codex调试］'):
        raise ValueError('real_owner_message_required')
    if input_value and input_value.casefold() not in event['text'].casefold():
        raise ValueError('source_input_not_in_owner_message')
    return event


def add(b, q):
    value = text(q.get('input'), 1600, True)
    event = owner_event(b, q, value)
    c = canonical(value)
    sid = hashlib.sha256(('tieba:' + c['key']).encode()).hexdigest()[:24]
    old = b.db.execute('SELECT * FROM sr_source WHERE id=?', (sid,)).fetchone()
    if old and old['active']:
        return dict(ok=True, replayed=True, source=dict(old))
    with b.db:
        b.db.execute('INSERT OR REPLACE INTO sr_source VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                     (sid, 'tieba', c['name'], c['url'], event['id'], 1, 'pending', '{}', time.time(), 0, 0))
    return dict(ok=True, source=dict(b.db.execute('SELECT * FROM sr_source WHERE id=?', (sid,)).fetchone()),
                next='verify exact forum identity in the native browser before scheduling reads')


def verify(b, q):
    row = active(b, q.get('source_id'), verified=False)
    status = q.get('status')
    if status not in ('verified', 'blocked', 'login_required', 'unavailable', 'failed'):
        raise ValueError('invalid_source_verification_status')
    proof = dict(url=text(q.get('url', row['url']), 1600, True), title=text(q.get('title', ''), 200),
                 receipt=text(q.get('receipt'), 200, True), tool='browser.browse', at=time.time())
    if status == 'verified':
        c = canonical(proof['url'])
        observed = text(q.get('observed_name'), 80, True)
        if (c['key'] != canonical(row['url'])['key'] or name_key(observed) not in (c['key'], c['key'] + '吧') or
                not proof['title'] or any(x in proof['title'] for x in ('安全验证', '验证码', '登录百度'))):
            raise ValueError('actual_forum_identity_not_verified')
        proof['observed_name'] = observed
    with b.db:
        b.db.execute('UPDATE sr_source SET status=?,proof=?,verified_at=? WHERE id=?',
                     (status, json.dumps(proof, ensure_ascii=False), time.time() if status == 'verified' else 0, row['id']))
    return dict(ok=True, source_id=row['id'], status=status, evidence='host_reported_native_browser_result')


def active(b, sid, verified=True):
    if not isinstance(sid, str):
        raise ValueError('source_id_required')
    row = b.db.execute('SELECT * FROM sr_source WHERE id=? AND active=1', (sid,)).fetchone()
    if not row or (verified and row['status'] != 'verified'):
        raise ValueError('source_not_allowed_or_not_verified')
    return row


def revoke(b, q):
    owner_event(b, q)
    row = active(b, q.get('source_id'), verified=False)
    with b.db:
        b.db.execute("UPDATE sr_source SET active=0,status='revoked' WHERE id=?", (row['id'],))
        b.db.execute("UPDATE sr_lease SET status='revoked' WHERE source=? AND status='claimed'", (row['id'],))
    return dict(ok=True, revoked=row['id'], learned_history='retained; use habit feedback to reject a learned habit')
