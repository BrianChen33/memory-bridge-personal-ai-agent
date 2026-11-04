"""Read-only cnmeme.wiki synchronization. Never sends chat text or submissions."""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sqlite3
import time
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen
import uuid

API = 'https://cnmeme.wiki/api/v1/public/memes'
USER_AGENT = 'PersonalAICompanionKit/0.6 (+https://github.com/BrianChen33/personal-ai-companion-kit)'
SEED_COMMIT = 'd6d2344663ab9ed60fb493e49b255c6f6d9bcadf'
SEED_SHA256 = '5d1d1857985b1d5602b886ed8ec79759a97b41451c1a855c354d7b2d9b820c4a'
SEED_URL = 'https://raw.githubusercontent.com/thawline/dsh-memewiki/' + SEED_COMMIT + '/data/memes.db'


class Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts = []; self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif tag in ('p', 'br', 'li', 'h2', 'h3', 'blockquote'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain(value):
    if not isinstance(value, str) or len(value) > 150000:
        raise ValueError('invalid_public_html')
    parser = Plain(); parser.feed(value)
    return re.sub(r'\n{3,}', '\n\n', ''.join(parser.parts)).strip()[:18000]


def timestamp(value):
    if value in (None, ''):
        return 0
    if not isinstance(value, str):
        raise ValueError('invalid_public_timestamp')
    at = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('public_timestamp_must_have_timezone')
    return at.timestamp()


def get_json(path, deadline):
    """Only anonymous public GETs; explicit UA, timeout, retry and byte budget."""
    if not (path.startswith('?') or path.startswith('/')) or path.startswith('//'):
        raise ValueError('invalid_public_api_path')
    for attempt in range(3):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            raise TimeoutError('sync_budget_exhausted')
        try:
            req = Request(API + path, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json'})
            with urlopen(req, timeout=min(15, remaining)) as response:
                if response.headers.get_content_type() != 'application/json':
                    raise ValueError('public_api_non_json')
                data = response.read(2 * 1024 * 1024 + 1)
                if len(data) > 2 * 1024 * 1024:
                    raise ValueError('public_api_response_too_large')
                return json.loads(data)
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise ValueError('public_api_http_' + str(error.code)) from None
            retry_after=error.headers.get('Retry-After','')
            delay = min(30, max(1, int(retry_after) if retry_after.isdigit() else 2 ** attempt))
            if attempt == 2 or time.monotonic() + delay + 1 >= deadline:
                raise ValueError('public_api_rate_limited' if error.code == 429 else 'public_api_server_error') from None
            time.sleep(delay)
        except (TimeoutError, OSError):
            if attempt == 2 or time.monotonic() + 2 ** attempt + 1 >= deadline:
                raise ValueError('public_api_network_error') from None
            time.sleep(2 ** attempt)
    raise ValueError('public_api_failed')


def seed(b, path):
    from muse_ext.companion import _set
    from muse_ext.meme_store import put_public
    path = Path(path).expanduser().resolve()
    if not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError('invalid_seed_file')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != SEED_SHA256:
        raise ValueError('seed_hash_mismatch')
    count = 0
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.row_factory = sqlite3.Row
        cursor = source.execute('SELECT title,slug,tags,usage,origin,other,summary,aliases FROM memes')
        while True:
            batch = cursor.fetchmany(100)
            if not batch:
                break
            with b.db:
                for r in batch:
                    item = dict(r)
                    slug = item['slug'] or item['title']
                    # A seed can be retried; it must never overwrite later API updates.
                    if b.db.execute('SELECT 1 FROM ct_meme_public WHERE slug=?', (slug,)).fetchone():
                        continue
                    item.update(slug=slug, tags=re.split('[、,，]', item['tags'] or ''),
                                aliases=re.split('[,，]', item['aliases'] or ''), keywords=[], updated_at='')
                    for field in ('usage', 'origin', 'other', 'summary'):
                        item[field] = (item[field] or '')[:{'usage': 10000, 'origin': 10000, 'other': 18000, 'summary': 3000}[field]]
                    item['tags'] = [x.strip() for x in item['tags'] if x.strip()][:50]
                    item['aliases'] = [x.strip() for x in item['aliases'] if x.strip()][:30]
                    put_public(b, item); count += 1
    with b.db:
        _set(b, 'meme_seed', dict(commit=SEED_COMMIT, sha256=digest, imported_at=time.time(),
                                source='thawline/dsh-memewiki; cnmeme.wiki',
                                freshness='seed only; API metadata and details are verified separately'))
    return dict(ok=True, imported=count)


def download_seed(b):
    """Download data only, never execute remote plugin code or bundle its database."""
    import tempfile
    with tempfile.TemporaryDirectory(prefix='companion-meme-seed-') as temp:
        target = Path(temp) / 'memes.db'
        request = Request(SEED_URL, headers={'User-Agent': USER_AGENT})
        with urlopen(request, timeout=30) as response, target.open('wb') as output:
            total = 0
            while True:
                data = response.read(256 * 1024)
                if not data:
                    break
                total += len(data)
                if total > 64 * 1024 * 1024:
                    raise ValueError('seed_too_large')
                output.write(data)
        return seed(b, target)


def sync(b, mode='incremental', max_pages=30, max_details=60, budget_seconds=180):
    from muse_ext.companion import _get, _set
    from muse_ext.humor import settings
    from muse_ext.meme_store import put_public
    if not settings(b)['values']['meme_sync_enabled']:
        return dict(ok=True, status='disabled_by_config')
    if mode not in ('incremental', 'full') or not 1 <= max_pages <= 400 or not 0 <= max_details <= 1000 or not 1 <= budget_seconds <= 900:
        raise ValueError('invalid_sync_budget')
    lease = uuid.uuid4().hex; now = time.time(); deadline = time.monotonic() + budget_seconds
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        lock = _get(b, 'meme_sync_lock', {})
        if lock.get('until', 0) > now:
            return dict(ok=True, status='busy')
        _set(b, 'meme_sync_lock', dict(id=lease, until=now + budget_seconds + 30))
    prior = _get(b, 'meme_sync_status', {})
    work = _get(b, 'meme_sync_work', {})
    # Finish the previous bounded sweep before starting a different mode.
    if work:
        mode = work['mode']
    else:
        work = dict(mode=mode, offset=0, seen=[], max_updated=0,
                    cutoff=prior.get('watermark', 0) if mode == 'incremental' else 0)
    pending = [r[0] for r in b.db.execute('SELECT slug FROM ct_meme_pending ORDER BY rowid')]
    pages = details = changed = 0; complete = False; error = None
    try:
        for _ in range(max_pages):
            if time.monotonic() + 1 >= deadline:
                break
            response = get_json('?' + urlencode(dict(limit=30, offset=work['offset'])), deadline)
            if not isinstance(response, dict) or response.get('schema_version') != 1 or not isinstance(response.get('items'), list) or type(response.get('has_more')) is not bool:
                raise ValueError('invalid_public_list_envelope')
            items = response['items']
            if len(items) > 30 or (not items and response['has_more']):
                raise ValueError('invalid_public_page')
            older = bool(items and work['cutoff'])
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError('invalid_public_item')
                remote_at = timestamp(item.get('updated_at'))
                slug = item.get('slug')
                if not isinstance(slug, str) or not slug or len(slug) > 300:
                    raise ValueError('invalid_public_slug')
                older = older and 0 < remote_at < work['cutoff']
                work['max_updated'] = max(work['max_updated'], remote_at)
                row = b.db.execute('SELECT payload,updated_at FROM ct_meme_public WHERE slug=?', (slug,)).fetchone()
                old = json.loads(row['payload']) if row else {}
                work['seen'].append(slug)
                if row and row['updated_at'] == (item.get('updated_at') or ''):
                    with b.db:
                        b.db.execute('UPDATE ct_meme_public SET seen_at=?,available=1 WHERE slug=?', (time.time(), slug))
                    continue
                metadata_changed = any(old.get(k) != item.get(k, [] if k in ('aliases', 'keywords', 'tags') else '') for k in ('title', 'summary', 'aliases', 'keywords', 'tags'))
                need_detail = not row or bool(row['updated_at']) or metadata_changed
                merged = dict(old, **item)
                if need_detail:
                    # Metadata is fresh immediately; don't inject an outdated body.
                    merged.update(usage='', origin='', other='')
                    if slug not in pending:
                        pending.append(slug)
                with b.db:
                    put_public(b, merged)
                    if need_detail:
                        b.db.execute('INSERT OR IGNORE INTO ct_meme_pending VALUES(?)',(slug,))
                changed += 1
            pages += 1; work['offset'] += 30
            work['seen'] = list(dict.fromkeys(work['seen']))
            with b.db:
                _set(b, 'meme_sync_work', work)
            if not response['has_more'] or older:
                complete = True
                break
            time.sleep(.25)
        # Details are separate retryable enrichment; the documented envelope is {item}.
        remaining = []
        for slug in pending:
            if details >= max_details or time.monotonic() + 2 >= deadline:
                remaining.append(slug); continue
            try:
                detail = get_json('/' + quote(slug, safe=''), deadline)
                if not isinstance(detail, dict) or detail.get('schema_version') != 1 or not isinstance(detail.get('item'), dict):
                    raise ValueError('invalid_public_detail_envelope')
                item = detail['item']; timestamp(item.get('updated_at'))
                item = dict(item, other=plain(item.get('content_html', '')), usage='', origin='')
                with b.db:
                    canonical = put_public(b, item)
                    if canonical != slug:
                        b.db.execute('UPDATE ct_meme_public SET available=0 WHERE slug=?', (slug,))
                    b.db.execute('DELETE FROM ct_meme_pending WHERE slug=?',(slug,))
                details += 1
            except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as exc:
                if str(exc)=='public_api_http_404':
                    with b.db:
                        b.db.execute('UPDATE ct_meme_public SET available=0 WHERE slug=?',(slug,))
                        b.db.execute('DELETE FROM ct_meme_pending WHERE slug=?',(slug,))
                    details+=1
                    continue
                remaining.append(slug); error = 'detail_enrichment_incomplete'
                # Stop this run on a transport/rate-limit failure; retain the queue.
                remaining.extend(x for x in pending[pending.index(slug) + 1:] if x not in remaining)
                break
            time.sleep(.25)
        pending = remaining
        with b.db:
            if complete:
                if mode == 'full':
                    # Offset paging can move while the site changes. Absence from
                    # one sweep is not proof of deletion; verify by detail GET.
                    seen=set(work['seen'])
                    pending=list(dict.fromkeys(pending+[r[0] for r in b.db.execute('SELECT slug FROM ct_meme_public WHERE available=1') if r[0] not in seen]))
                    b.db.executemany('INSERT OR IGNORE INTO ct_meme_pending VALUES(?)',[(s,) for s in pending])
                _set(b, 'meme_sync_work', {})
            state = dict(status='complete' if complete and not pending else 'partial',
                         checked_at=time.time(), mode=mode, pages=pages, details=details, changed=changed,
                         pending_details=pending, offset=0 if complete else work['offset'], error=error,
                         watermark=max(prior.get('watermark', 0), work['max_updated']) if complete else prior.get('watermark', 0),
                         last_success_at=time.time() if complete and not pending else prior.get('last_success_at'),
                         detail_note='seed bodies without API verification retain seed provenance; changed bodies are cleared until fetched')
            _set(b, 'meme_sync_status', state)
        return dict(ok=True, **state, pending_count=len(pending))
    except (ValueError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        state = dict(prior, status='failed', checked_at=time.time(), error=str(exc)[:100], pending_details=pending)
        with b.db:
            _set(b, 'meme_sync_work', work); _set(b, 'meme_sync_status', state)
        return dict(ok=False, **state)
    finally:
        with b.db:
            if _get(b, 'meme_sync_lock', {}).get('id') == lease:
                _set(b, 'meme_sync_lock', {})


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', required=True); p.add_argument('--seed', action='store_true')
    p.add_argument('--seed-file'); p.add_argument('--mode', choices=('incremental', 'full'), default='incremental')
    p.add_argument('--max-pages', type=int, default=30); p.add_argument('--max-details', type=int, default=60)
    p.add_argument('--budget-seconds', type=int, default=180)
    args = p.parse_args()
    from brain import Brain
    with closing(Brain(args.root)) as b:
        if b.config().get('companion_v2') is not True:
            raise ValueError('companion_v2_required')
        if not b.config().get('enabled'):
            result = dict(ok=True, status='disabled_by_config')
        elif args.seed or args.seed_file:
            result = seed(b, args.seed_file) if args.seed_file else download_seed(b)
        else:
            result = sync(b, args.mode, args.max_pages, args.max_details, args.budget_seconds)
    # Keep huge pending slug lists out of logs; they remain in the private database.
    result.pop('pending_details', None)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())
