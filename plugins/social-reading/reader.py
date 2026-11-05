"""Native-browser receipt adapter, not a browser driver or HTTP scraper."""
import hashlib
import json
import math
import re
import time
import uuid
from . import sources, store


def plan(b, q):
    p = store.settings(b)
    manual = q.get('manual') is True
    if not b.available('input') or not b.available('memory') or not b.feature('reading'):
        return dict(ok=True, action='disabled_by_core')
    from muse_ext.companion import quiet
    quiet_now = quiet()
    if not manual and not p['auto_browse']:
        return dict(ok=True, action='paused')
    rows = list(b.db.execute('SELECT * FROM sr_source WHERE active=1 ORDER BY last_read,verified_at'))
    allowed = [r for r in rows if r['status'] == 'verified']
    if not rows:
        return dict(ok=True, action='awaiting_sources', onboarding_required=True)
    if not allowed:
        return dict(ok=True, action='awaiting_verification', onboarding_required=False)
    job = sources.text(q.get('job_id'), 200, True)
    now = time.time()
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        if b.db.execute("SELECT 1 FROM sr_lease WHERE status='claimed' AND deadline>?", (now,)).fetchone():
            return dict(ok=True, action='busy')
        if b.db.execute('SELECT count(*) FROM sr_lease WHERE job=?', (job,)).fetchone()[0] >= p['max_threads']:
            return dict(ok=True, action='run_budget_used')
        selected = next((r for r in allowed if r['id'] == q.get('source_id')), None)
        if q.get('source_id') and selected is None:
            raise ValueError('requested_source_not_allowed')
        selected = selected or allowed[0]
        lease = uuid.uuid4().hex
        b.db.execute('INSERT INTO sr_lease VALUES(?,?,?,?,?,?,?,?)',
                     (lease, selected['id'], 'claimed', now, now + p['budget_seconds'], int(manual),
                      json.dumps(p), job))
    previous = b.db.execute('SELECT url,payload,status FROM sr_document WHERE source=? ORDER BY created DESC LIMIT 1', (selected['id'],)).fetchone()
    resume = None
    if previous and previous['status'] == 'partial':
        saved = json.loads(previous['payload'])
        resume = dict(url=previous['url'], coverage=saved.get('coverage', {}), receipt=saved.get('receipt'))
    return dict(ok=True, action='browse', lease_id=lease, source_id=selected['id'], url=selected['url'], resume=resume,
                provider='tieba', budget=p, quiet_hours=quiet_now, browser='host_native_browser_only',
                instruction='Read permitted visible content only. Stop at login/CAPTCHA. Return actual task receipt, '
                            'forum identity, floors/replies/image observation states and explicit page coverage. '
                            'A planner narrative must be normalized by the same host model; it is not a DOM API.')


def lease(b, q):
    if not b.available('input') or not b.available('memory') or not b.feature('reading'):
        raise ValueError('reading_disabled_by_core')
    row = b.db.execute('SELECT * FROM sr_lease WHERE id=?', (q.get('lease_id'),)).fetchone()
    if not row or row['status'] != 'claimed' or time.time() > row['deadline']:
        raise ValueError('invalid_or_expired_reading_lease')
    source = sources.active(b, row['source'])
    if not row['manual'] and not store.settings(b)['auto_browse']:
        raise ValueError('autonomous_reading_paused')
    return row, source, json.loads(row['settings'])


def thread_url(value):
    p = sources.official_url(value)
    match = re.fullmatch(r'/p/(\d{1,24})/?', p.path)
    if not match:
        raise ValueError('actual_thread_url_required')
    return 'https://tieba.baidu.com/p/' + match[1]


def discover(b, q):
    row, source, policy = lease(b, q)
    receipt = sources.text(q.get('receipt'), 200, True)
    items = q.get('threads')
    if not isinstance(items, list) or len(items) > 50:
        raise ValueError('bounded_native_thread_list_required')
    result, seen = [], set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError('thread_list_item_required')
        url = thread_url(item.get('url'))
        if url in seen:
            continue
        seen.add(url)
        result.append(dict(url=url, tid=url.rsplit('/', 1)[1], title=sources.text(item.get('title'), 200, True),
                           author=sources.optional_text(item.get('author'), 100) or None,
                           is_top=item.get('is_top') is True,
                           replies=item.get('replies') if type(item.get('replies')) is int and item['replies'] >= 0 else None))
    return dict(ok=True, source_id=source['id'], receipt=receipt, threads=result,
                status='observed_list' if result else 'empty_unconfirmed',
                authority='native browser report; list discovery is not a completed reading or emotional event')


def normalize(q, source, policy):
    data = q.get('observation')
    if not isinstance(data, dict) or data.get('provider') != 'tieba' or data.get('schema') != 'social-observation-v1':
        raise ValueError('tieba_observation_v1_required')
    if len(json.dumps(data, ensure_ascii=False).encode()) > 50000:
        raise ValueError('observation_packet_too_large')
    receipt = sources.text(data.get('receipt'), 200, True)
    if data.get('tool') != 'browser.browse':
        raise ValueError('native_live_browser_receipt_required')
    forum = sources.canonical(data.get('forum_url'))
    if forum['key'] != sources.canonical(source['url'])['key']:
        raise ValueError('observation_forum_not_allowed')
    status = data.get('status')
    if status in ('blocked', 'login_required', 'unavailable', 'failed'):
        return dict(status=status, receipt=receipt, title=sources.text(data.get('title', ''), 200))
    if status not in ('ok', 'partial'):
        raise ValueError('explicit_reading_status_required')
    title = sources.text(data.get('title'), 200, True)
    if any(x in title for x in ('安全验证', '验证码', '登录百度')):
        raise ValueError('verification_page_is_not_content')
    url = thread_url(data.get('url'))
    raw = data.get('floors')
    if not isinstance(raw, list) or not 1 <= len(raw) <= 120:
        raise ValueError('nonempty_observed_floors_required')
    floors, seen = [], set()
    for i, f in enumerate(raw):
        if not isinstance(f, dict):
            raise ValueError('floor_object_required')
        content = sources.optional_text(f.get('text'), 8000)
        pid = sources.optional_text(f.get('pid'), 100) or None
        number = f.get('floor')
        if number is not None and (type(number) is not int or number < 1):
            raise ValueError('invalid_observed_floor_number')
        key = pid or 'fallback:' + hashlib.sha256(json.dumps([number, f.get('author'), content], ensure_ascii=False).encode()).hexdigest()
        if key in seen:
            continue
        seen.add(key)
        replies = f.get('replies', [])
        images = f.get('images', [])
        if not isinstance(replies, list) or len(replies) > 30 or not isinstance(images, list) or len(images) > 12:
            raise ValueError('bounded_replies_and_images_required')
        rr, ii = [], []
        for r in replies:
            if not isinstance(r, dict):
                raise ValueError('reply_object_required')
            rr.append(dict(author=sources.optional_text(r.get('author'), 100) or None,
                           text=sources.text(r.get('text'), 1600, True)))
        for im in images:
            if not isinstance(im, dict):
                raise ValueError('image_object_required')
            p = sources.official_url(im.get('url'), ('tiebapic.baidu.com', 'imgsrc.baidu.com'))
            if im.get('quality', 'unknown') not in ('thumb', 'original', 'unknown') or im.get('observation') not in ('viewed', 'url_only'):
                raise ValueError('explicit_image_observation_required')
            ii.append(dict(url=p.geturl(), quality=im.get('quality', 'unknown'), observation=im['observation'],
                           caption=sources.text(im.get('caption', ''), 400) if im['observation'] == 'viewed' else '',
                           downloaded=False))
        if not content and not ii:
            continue
        floors.append(dict(pid=pid, floor=number, position=i + 1,
                           author=sources.optional_text(f.get('author'), 100) or None,
                           is_op=f.get('is_op') is True, text=content, replies=rr, images=ii,
                           posted_at=sources.optional_text(f.get('posted_at'), 100) or None,
                           replies_complete=f.get('replies_complete') is True))
    if not floors:
        raise ValueError('no_actual_reading_content')
    coverage = data.get('coverage', {})
    if not isinstance(coverage, dict):
        raise ValueError('coverage_object_required')
    pages = coverage.get('pages_seen', [])
    total = coverage.get('total_pages')
    if (not isinstance(pages, list) or not pages or len(pages) > policy['max_pages'] or
            any(type(x) is not int or x < 1 for x in pages) or len(set(pages)) != len(pages) or
            (total is not None and (type(total) is not int or total < max(pages)))):
        raise ValueError('actual_bounded_page_coverage_required')
    complete = (status == 'ok' and total is not None and len(pages) == total and
                set(pages) == set(range(1, total + 1)) and coverage.get('ended') is True and
                coverage.get('all_visible_floors') is True)
    next_url = coverage.get('next_url')
    if next_url is not None and thread_url(next_url) != url:
        raise ValueError('next_page_outside_current_thread')
    return dict(provider='tieba', schema='social-observation-v1', url=url, title=title,
                forum_url=forum['url'], receipt=receipt, tool='browser.browse',
                status='complete' if complete else 'partial', floors=floors,
                coverage=dict(pages_seen=pages, total_pages=total, ended=coverage.get('ended') is True,
                              all_visible_floors=coverage.get('all_visible_floors') is True, next_url=next_url),
                media_policy='URL-only is not image inspection; images are not downloaded by this adapter')


def content_fingerprint(value):
    meaningful = {k: value[k] for k in ('provider', 'url', 'forum_url', 'title')}
    meaningful['floors'] = [{k: v for k, v in floor.items() if k != 'position'} for floor in value['floors']]
    return hashlib.sha256(json.dumps(meaningful, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def ensure_observed(b, event):
    return (b.dispatch(dict(op='companion_observe', scope='owner-private', source_event=event))
            if b.available('life') else {'disabled': True})


def observe(b, q):
    # Terminal leases may replay their exact receipt, never append new content.
    old_lease = b.db.execute('SELECT * FROM sr_lease WHERE id=?', (q.get('lease_id'),)).fetchone()
    if old_lease and old_lease['status'].startswith('done:'):
        source = sources.active(b, old_lease['source'])
        value = normalize(q, source, json.loads(old_lease['settings']))
        fingerprint = content_fingerprint(value)
        doc = b.db.execute('SELECT * FROM sr_document WHERE id=?', (old_lease['status'][5:],)).fetchone()
        if doc:
            if fingerprint != doc['fingerprint']:
                raise ValueError('reading_lease_content_conflict')
            return dict(ok=True, replayed=True, document_id=doc['id'], source_event=doc['event'], status=doc['status'],
                        observed=ensure_observed(b, doc['event']))
    row, source, policy = lease(b, q)
    value = normalize(q, source, policy)
    if value['status'] in ('blocked', 'login_required', 'unavailable', 'failed'):
        with b.db:
            b.db.execute('UPDATE sr_lease SET status=? WHERE id=?', (value['status'], row['id']))
            b.db.execute('UPDATE sr_source SET status=?,proof=? WHERE id=?',
                         (value['status'], json.dumps(value, ensure_ascii=False), source['id']))
        return dict(ok=True, reading_saved=False, **value)
    fingerprint = content_fingerprint(value)
    did = hashlib.sha256((source['id'] + ':' + fingerprint).encode()).hexdigest()
    previous = b.db.execute('SELECT * FROM sr_document WHERE id=?', (did,)).fetchone()
    if previous:
        status = 'complete' if previous['status'] == 'complete' else value['status']
        with b.db:
            b.db.execute('UPDATE sr_lease SET status=? WHERE id=?', ('done:' + did, row['id']))
            if previous['status'] != 'complete' or value['status'] == 'complete':
                b.db.execute('UPDATE sr_document SET payload=?,status=?,last_seen=? WHERE id=?',
                             (json.dumps(value, ensure_ascii=False), status, time.time(), did))
            b.db.execute('UPDATE sr_source SET last_read=? WHERE id=?', (time.time(), source['id']))
        return dict(ok=True, replayed=True, document_id=did, source_event=previous['event'], status=status,
                    observed=ensure_observed(b, previous['event']))
    quote = '\n'.join(f['text'] + '\n' + '\n'.join(r['text'] for r in f['replies']) for f in value['floors'])[:6000]
    if not quote.strip():
        quote = '\n'.join(im['caption'] for f in value['floors'] for im in f['images'] if im['observation'] == 'viewed')
    if not quote.strip():
        raise ValueError('image_urls_alone_are_not_reading')
    now = time.time()
    event = b.dispatch(dict(op='capture', scope='owner-private', actor='article', person_id='owner',
                            source='plugin:social-reading:' + value['url'], event_id='social:' + did,
                            occurred_at=now, text=quote))['event']['id']
    mid = b._remember(dict(scope='owner-private', source='reading:' + value['url'], event_id='social:' + did,
                           occurred_at=now, text=quote, kind='episode', evidence='observed', importance=.4))
    with b.db:
        b.db.execute('INSERT INTO sr_document VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                     (did, source['id'], value['url'], value['title'], fingerprint,
                      json.dumps(value, ensure_ascii=False), quote, event, mid, now, now, value['status']))
        b.db.execute('UPDATE sr_lease SET status=? WHERE id=?', ('done:' + did, row['id']))
        b.db.execute('UPDATE sr_source SET last_read=? WHERE id=?', (now, source['id']))
        # Keep at most50 full packets. Compact evidence/quotes remain traceable.
        b.db.execute("UPDATE sr_document SET payload='{}' WHERE id NOT IN (SELECT id FROM sr_document ORDER BY created DESC LIMIT 50)")
    observed = ensure_observed(b, event)
    from muse_ext.emotion_full48 import template
    return dict(ok=True, document_id=did, source_event=event, quote_id=mid, status=value['status'],
                observed=observed, emotion_template=template(),
                next='same host model reflects and evaluates the registered observed event; no extra emotion model')


def read(b, q):
    row = b.db.execute('SELECT * FROM sr_document WHERE id=?', (q.get('document_id'),)).fetchone()
    if not row:
        raise ValueError('reading_document_not_found')
    data = json.loads(row['payload'])
    if not data:
        return dict(ok=True, status='cache_evicted', title=row['title'], quote=row['quote'], source_event=row['event'])
    p = store.settings(b)
    mode = q.get('sample_mode', p['sample_mode'])
    total = len(data['floors'])
    if mode == 'all':
        want = total
    elif mode == 'fixed':
        want = p['sample_fixed']
    elif mode == 'ratio':
        want = round(total * p['sample_ratio'])
    elif mode == 'dynamic':
        n = total if total <= p['sample_min'] else p['sample_min'] + (total - p['sample_min']) * .3 if total <= 300 else 125 + (total - 300) * .15
        want = max(p['sample_min'], min(p['sample_max'], round(n)))
    else:
        raise ValueError('invalid_sample_mode')
    want = max(1, min(total, want))
    picked = {round(k * (total - 1) / (want - 1)) for k in range(want)} if want > 1 else {0}
    picked.update(i for i, f in enumerate(data['floors']) if f['is_op'])
    floors = []
    for i in sorted(picked):
        f = dict(data['floors'][i])
        f['text_length'] = len(f['text'])
        f['truncated'] = len(f['text']) > p['max_text_chars']
        f['text'] = f['text'][:p['max_text_chars']]
        floors.append(f)
    return dict(ok=True, document_id=row['id'], url=row['url'], title=row['title'], status=row['status'],
                coverage=data['coverage'], observed_floors=total, returned_floors=len(floors), floors=floors,
                cache_age_seconds=round(time.time() - row['last_seen']),
                cache_fresh=time.time() - row['last_seen'] <= p['cache_ttl_seconds'],
                policy='sampling applies only to observed floors; never claims unseen OP floors were filled')
