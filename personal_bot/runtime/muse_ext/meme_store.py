"""Scoped evolving humor knowledge. Public facts and private inferences stay separate."""
import hashlib
import json
import math
import re
import time
from urllib.parse import quote


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS ct_meme_public(
      slug TEXT PRIMARY KEY,title TEXT NOT NULL,payload TEXT NOT NULL,updated_at TEXT NOT NULL DEFAULT '',
      available INTEGER NOT NULL DEFAULT 1,seen_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS ct_meme_title ON ct_meme_public(title);
    CREATE TABLE IF NOT EXISTS ct_meme_term(term TEXT,slug TEXT,kind TEXT,PRIMARY KEY(term,slug,kind));
    CREATE INDEX IF NOT EXISTS ct_meme_term_slug ON ct_meme_term(slug);
    CREATE TABLE IF NOT EXISTS ct_meme_pending(slug TEXT PRIMARY KEY);
    CREATE TABLE IF NOT EXISTS ct_meme_private(
      id TEXT PRIMARY KEY,scope TEXT NOT NULL,title TEXT NOT NULL,payload TEXT NOT NULL,
      status TEXT NOT NULL,confidence REAL NOT NULL,evidence TEXT NOT NULL,updated REAL NOT NULL,
      UNIQUE(scope,title));
    CREATE TABLE IF NOT EXISTS ct_meme_event(
      event INTEGER,action TEXT,target TEXT,payload TEXT NOT NULL,result TEXT NOT NULL,at REAL NOT NULL,
      PRIMARY KEY(event,action,target));
    CREATE TABLE IF NOT EXISTS ct_meme_use(
      event INTEGER PRIMARY KEY,scope TEXT NOT NULL,keys_json TEXT NOT NULL,outcome TEXT NOT NULL,at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS ct_meme_block(
      scope TEXT,target TEXT,reason TEXT NOT NULL,at REAL NOT NULL,PRIMARY KEY(scope,target));
    CREATE TABLE IF NOT EXISTS ct_humor_appraisal(event INTEGER PRIMARY KEY,payload TEXT NOT NULL,at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS ct_humor_preference(
      scope TEXT,person TEXT,muted_until REAL NOT NULL,updated REAL NOT NULL,cause INTEGER NOT NULL,PRIMARY KEY(scope,person));
    CREATE TABLE IF NOT EXISTS ct_emotion_effect(
      event INTEGER PRIMARY KEY,gain REAL NOT NULL,settings_revision INTEGER NOT NULL,
      raw_delta TEXT NOT NULL,applied_delta TEXT NOT NULL,raw_labels TEXT NOT NULL,
      applied_labels TEXT NOT NULL,at REAL NOT NULL);
    ''')


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError('invalid_meme_text')
    return value.strip()


def strings(values, count=12, length=100):
    if not isinstance(values, list) or len(values) > count:
        raise ValueError('invalid_meme_list')
    return list(dict.fromkeys(text(x, length, True) for x in values))


def key(scope, title):
    return hashlib.sha256((scope + '\0' + title.casefold()).encode()).hexdigest()[:32]


def _replay(b, event, action, target, payload):
    row = b.db.execute('SELECT payload,result FROM ct_meme_event WHERE event=? AND action=? AND target=?',
                       (event, action, target)).fetchone()
    if not row:
        return None
    if row['payload'] != payload:
        return dict(ok=False, status='conflict')
    return dict(json.loads(row['result']), replayed=True)


def _record(b, event, action, target, payload, result):
    from muse_ext.companion import dump
    b.db.execute('INSERT INTO ct_meme_event VALUES(?,?,?,?,?,?)',
                 (event, action, target, payload, dump(result), time.time()))


def learn(b, q):
    from muse_ext.humor import settings, source_event
    from muse_ext.companion import dump
    if not settings(b)['values']['self_learning']:
        return dict(ok=True, status='disabled_by_config')
    event = source_event(b, q)
    title = text(q.get('title'), 120, True)
    basis = q.get('basis', 'observed')
    if basis not in ('observed', 'explained', 'coined'):
        raise ValueError('invalid_learning_basis')
    if basis == 'explained' and event['actor'] != 'user':
        raise ValueError('human_teaching_required')
    confidence = q.get('confidence', .6)
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError('invalid_meme_confidence')
    bridges = q.get('bridges', [])
    if not isinstance(bridges, list) or len(bridges) > 3:
        raise ValueError('invalid_association_bridges')
    clean_bridges = []
    for item in bridges:
        if not isinstance(item, dict) or set(item) != {'from', 'to', 'why'}:
            raise ValueError('invalid_association_bridge')
        clean_bridges.append({k: text(v, 100, True) for k, v in item.items()})
    data = dict(title=title, meaning=text(q.get('meaning'), 800, True),
                aliases=strings(q.get('aliases', [])), contexts=strings(q.get('contexts', []), 8),
                avoid=strings(q.get('avoid', []), 8), usage=text(q.get('usage', ''), 500),
                mechanism=text(q.get('mechanism', 'other'), 80, True), bridges=clean_bridges,
                basis=basis, provenance='model_interpretation_of_scoped_source')
    mid = key(q['scope'], title); payload = dump(dict(data, confidence=confidence))
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        prev = _replay(b, event['id'], 'learn', mid, payload)
        if prev is not None:
            return prev
        old = b.db.execute('SELECT * FROM ct_meme_private WHERE id=?', (mid,)).fetchone()
        parsed = _private_data(old) if old else None
        old_data = parsed[0] if parsed else {}
        same=bool(parsed and all(old_data.get(k)==data.get(k) for k in ('meaning','usage','mechanism','bridges','contexts','avoid')))
        # Evidence supports an interpretation, not merely the spelling of a title.
        evidence = parsed[1] if same else []
        evidence = list(dict.fromkeys(evidence + [event['id']]))[-32:]
        confirmed=list(old_data.get('confirmed_by',[])) if same else []
        if basis=='explained': confirmed.append(event['id'])
        data['confirmed_by']=list(dict.fromkeys(x for x in confirmed if x in evidence))
        marks=','.join('?' for _ in evidence)
        active={r[0] for r in b.db.execute("SELECT id FROM source_events WHERE scope=? AND status='active' AND id IN ("+marks+')',[q['scope']]+evidence)}
        # A single repeated tool call cannot turn speculation into established knowledge.
        status = 'active' if confidence>=.75 and (active.intersection(data['confirmed_by']) or (basis!='coined' and len(active)>=2)) else 'candidate'
        if old and old['status'] == 'retired' and basis != 'explained':
            status = 'retired'
        b.db.execute('INSERT OR REPLACE INTO ct_meme_private VALUES(?,?,?,?,?,?,?,?)',
                     (mid, q['scope'], title, dump(data), status, confidence, dump(evidence), time.time()))
        result = dict(ok=True, id=mid, status=status, evidence_count=len(evidence))
        _record(b, event['id'], 'learn', mid, payload, result)
    return result


def feedback(b, q):
    from muse_ext.humor import source_event, settings
    from muse_ext.companion import dump
    if not settings(b)['values']['self_learning']:
        return dict(ok=True, status='disabled_by_config')
    event = source_event(b, q)
    if event['actor'] != 'user':
        raise ValueError('human_feedback_required')
    mid = text(q.get('id'), 340, True)
    outcome = q.get('outcome')
    if outcome not in ('liked', 'disliked', 'misused', 'retire'):
        raise ValueError('invalid_meme_feedback')
    note = text(q.get('note', ''), 240)
    payload = dump(dict(outcome=outcome, note=note))
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        if mid.startswith('public:'):
            if not b.db.execute('SELECT 1 FROM ct_meme_public WHERE slug=?', (mid[7:],)).fetchone():
                raise ValueError('public_meme_not_found')
            prev = _replay(b, event['id'], 'feedback', mid, payload)
            if prev is not None:
                return prev
            if outcome == 'liked':
                b.db.execute('DELETE FROM ct_meme_block WHERE scope=? AND target=?', (q['scope'], mid))
            else:
                b.db.execute('INSERT OR REPLACE INTO ct_meme_block VALUES(?,?,?,?)', (q['scope'], mid, outcome, time.time()))
            result = dict(ok=True, id=mid, status='allowed' if outcome == 'liked' else 'blocked_in_scope')
            _record(b, event['id'], 'feedback', mid, payload, result)
            return result
        row = b.db.execute('SELECT * FROM ct_meme_private WHERE id=? AND scope=?', (mid, q['scope'])).fetchone()
        if not row:
            raise ValueError('scoped_private_meme_not_found')
        prev = _replay(b, event['id'], 'feedback', mid, payload)
        if prev is not None:
            return prev
        parsed = _private_data(row)
        if parsed is None:
            return dict(ok=False, error='legacy_meme_requires_source_backed_relearning')
        value, evidence = parsed
        value['last_feedback'] = dict(outcome=outcome, note=note)
        if outcome=='liked':
            evidence=list(dict.fromkeys(evidence+[event['id']]))[-32:]
            value['confirmed_by']=list(dict.fromkeys(value.get('confirmed_by',[])+[event['id']]))[-32:]
        confidence = min(1, row['confidence'] + .12) if outcome == 'liked' else max(0, row['confidence'] - .2)
        state = ('active' if confidence >= .75 else 'candidate') if outcome == 'liked' else 'retired' if outcome in ('retire', 'misused') else row['status']
        b.db.execute('UPDATE ct_meme_private SET payload=?,status=?,confidence=?,evidence=?,updated=? WHERE id=?',
                     (dump(value), state, confidence, dump(evidence), time.time(), mid))
        result = dict(ok=True, id=mid, status=state, confidence=confidence)
        _record(b, event['id'], 'feedback', mid, payload, result)
    return result


def record_use(b, q):
    from muse_ext.humor import source_event
    from muse_ext.companion import dump
    event = source_event(b, q); keys = strings(q.get('keys', []), 3, 160)
    outcome = q.get('outcome', 'model_reported')
    if outcome not in ('model_reported', 'accepted', 'unknown', 'failed'):
        raise ValueError('invalid_meme_use_outcome')
    payload = dump(keys)
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        prev = b.db.execute('SELECT * FROM ct_meme_use WHERE event=?', (event['id'],)).fetchone()
        if prev and prev['keys_json'] != payload:
            return dict(ok=False, status='conflict')
        if prev and prev['outcome'] != 'model_reported':
            return dict(ok=True, replayed=True, outcome=prev['outcome'])
        b.db.execute('INSERT OR REPLACE INTO ct_meme_use VALUES(?,?,?,?,?)',
                     (event['id'], q['scope'], payload, outcome, time.time()))
    return dict(ok=True, outcome=outcome)


def recent(b, scope, limit=4):
    return [dict(keys=json.loads(r['keys_json']), outcome=r['outcome'], at=r['at']) for r in b.db.execute(
        'SELECT keys_json,outcome,at FROM ct_meme_use WHERE scope=? ORDER BY at DESC LIMIT ?', (scope, limit))]


def put_public(b, item):
    """Called only by trusted import/sync, never by conversation learning."""
    from muse_ext.companion import dump
    slug = text(item.get('slug'), 300, True); title = text(item.get('title'), 200, True)
    aliases = strings(item.get('aliases', []), 30, 200)
    keywords = strings(item.get('keywords', []), 30, 200)
    tags = strings(item.get('tags', []), 50, 200)
    value = dict(title=title, slug=slug, aliases=aliases, keywords=keywords, tags=tags,
                 summary=text(item.get('summary', ''), 3000), usage=text(item.get('usage', ''), 10000),
                 origin=text(item.get('origin', ''), 10000), other=text(item.get('other', ''), 18000),
                 source_url='https://cnmeme.wiki/api/v1/public/memes/' + quote(slug, safe=''),
                 source='cnmeme.wiki; external reference data')
    updated = text(item.get('updated_at') or '', 80)
    b.db.execute('INSERT OR REPLACE INTO ct_meme_public VALUES(?,?,?,?,1,?)',
                 (slug, title, dump(value), updated, time.time()))
    b.db.execute('DELETE FROM ct_meme_term WHERE slug=?', (slug,))
    for kind, terms in [('title', [title]), ('alias', aliases), ('keyword', keywords)]:
        b.db.executemany('INSERT OR IGNORE INTO ct_meme_term VALUES(?,?,?)',
                         [(s.casefold(), slug, kind) for s in terms if len(s.strip()) >= 2])
    return slug


def _score(query, term, kind):
    if query == term:
        return 1 if kind == 'title' else .96 if kind == 'alias' else .78
    if len(term) >= 2 and term in query:
        return min(.94, .75 + len(term) * .02) if kind != 'keyword' else .6
    if len(query) >= 3 and query in term:
        return .55
    return 0


def search(b, q, automatic=False):
    query = text(q.get('text', ''), 12000).casefold()
    if not query:
        return dict(ok=True, items=[])
    limit = q.get('limit', 3)
    if type(limit) is not int or not 1 <= limit <= 5:
        raise ValueError('meme_limit_1_to_5_required')
    ranked = {}
    # SQL only scans short indexed-term columns, not every article body.
    for r in b.db.execute('SELECT term,slug,kind FROM ct_meme_term WHERE instr(?,term)>0 OR (length(?)>=3 AND instr(term,?)>0) ORDER BY (term=?) DESC,(kind=\'title\') DESC,length(term) DESC LIMIT 120', (query, query, query, query)):
        score = _score(query, r['term'], r['kind'])
        if automatic and score < .75:
            continue
        ranked[r['slug']] = max(ranked.get(r['slug'], 0), score)
    items = []
    blocked={r[0] for r in b.db.execute('SELECT target FROM ct_meme_block WHERE scope=?', (q['scope'],))}
    for slug, score in sorted(ranked.items(), key=lambda x: -x[1])[:limit]:
        if 'public:'+slug in blocked:
            continue
        row = b.db.execute('SELECT payload FROM ct_meme_public WHERE slug=? AND available=1', (slug,)).fetchone()
        if row:
            v = json.loads(row[0]); items.append(dict(v, key='public:' + slug, score=score, wiki_origin=v.get('origin',''), origin='public'))
    for row in b.db.execute("SELECT * FROM ct_meme_private WHERE scope=? AND status='active' ORDER BY updated DESC LIMIT 256", (q['scope'],)):
        if not evidence_active(b, row):
            continue
        v = json.loads(row['payload'])
        if v.get('last_feedback',{}).get('outcome')=='disliked':
            continue
        score = max([_score(query, row['title'].casefold(), 'title')] + [_score(query, term.casefold(), 'alias') for term in v['aliases']])
        if score >= (.75 if automatic else .5):
            # A source-backed local explanation takes precedence in this scope.
            items=[x for x in items if x.get('title')!=row['title']]
            items.append(dict(key='private:' + row['id'], score=min(1, score + .02), origin='private', confidence=row['confidence'], **v))
    items.sort(key=lambda x: (-x['score'], x['origin'] != 'private'))
    result = []; budget = 1800
    for value in items[:limit]:
        if budget < 100:
            break
        item = {k: value[k] for k in ('key', 'title', 'origin', 'score', 'source_url', 'confidence', 'mechanism', 'bridges') if k in value}
        for k in ('meaning', 'summary', 'usage', 'other'):
            if budget < 50:
                break
            if value.get(k):
                item[k] = value[k][:min(400, budget)]; budget -= len(item[k])
        result.append(item)
    return dict(ok=True, items=result, ambiguous=len(result) > 1, reference_only=True)


def _private_data(row):
    """A malformed legacy row must not break every prepare/search/pattern call."""
    try:
        ids = json.loads(row['evidence'])
        value = json.loads(row['payload'])
    except (ValueError, TypeError):
        return None
    if not isinstance(ids, list) or len(ids) > 32 or any(type(x) is not int for x in ids):
        return None
    if not isinstance(value, dict):
        return None
    for name in ('aliases', 'contexts', 'avoid'):
        if not isinstance(value.get(name), list) or any(not isinstance(x, str) for x in value[name]):
            return None
    if not isinstance(value.get('mechanism'), str) or not isinstance(value.get('bridges'), list):
        return None
    if not isinstance(value.get('confirmed_by'), list) or any(type(x) is not int for x in value['confirmed_by']):
        return None
    if not isinstance(value.get('last_feedback', {}), dict):
        return None
    return value, ids


def evidence_active(b, row):
    parsed = _private_data(row)
    if parsed is None:
        return False
    value, ids = parsed
    if not ids: return False
    active={r[0] for r in b.db.execute("SELECT id FROM source_events WHERE scope=? AND status='active' AND id IN ("+','.join('?' for _ in ids)+')', [row['scope']]+ids)}
    return bool(active.intersection(value.get('confirmed_by',[])) or len(active)>=2)


def patterns(b, scope, event_id):
    """Stable per-event variety, without a second LLM or an emotion lottery."""
    values=[]
    for row in b.db.execute("SELECT * FROM ct_meme_private WHERE scope=? AND status='active' ORDER BY updated DESC LIMIT 48", (scope,)):
        if not evidence_active(b,row):
            continue
        v=json.loads(row['payload'])
        if v.get('last_feedback',{}).get('outcome')=='disliked':
            continue
        values.append((hashlib.sha256(f'{event_id}:{row["id"]}'.encode()).hexdigest(),
                       dict(mechanism=v['mechanism'],bridges=v['bridges'],contexts=v['contexts'],avoid=v['avoid'])))
    return [x[1] for x in sorted(values,key=lambda x:x[0])[:2]]


def status(b):
    from muse_ext.companion import _get
    return dict(public_count=b.db.execute('SELECT count(*) FROM ct_meme_public WHERE available=1').fetchone()[0],
                private_counts={r[0]: r[1] for r in b.db.execute('SELECT status,count(*) FROM ct_meme_private GROUP BY status')},
                sync=_get(b, 'meme_sync_status', {}), seed=_get(b, 'meme_seed', {}),
                recent_learning=[dict(r) for r in b.db.execute('SELECT title,status,confidence,updated FROM ct_meme_private ORDER BY updated DESC LIMIT 8')])
