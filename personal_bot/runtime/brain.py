"""Muse Brain: local, scoped, source-backed memory and life ledger. No network I/O.

Independent implementation inspired by memory-brain's six-layer architecture.
Logical scope filtering is not an OS security boundary for an agent with exec.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sqlite3
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

try:
    from proactive import proactive_allowed
except ImportError:
    proactive_allowed = None

VERSION = '1.0.0'
MODULES = ('memory', 'mood', 'life', 'style', 'feedback', 'input')
KINDS = ('episode', 'fact', 'preference', 'relation', 'reflection', 'skill', 'lesson')
FEATURES = ('events','time_query','emotion_events','reminders','vector','consolidation','reading')

# Morning batch digest bounds: claim at most this many pendings / chars per
# round. Unselected pendings stay pending for later rounds (never dropped).
# The first pending is always selected even if over budget, so one overlong
# item cannot starve the queue forever (it is digested alone).
DIGEST_MAX_ITEMS = 6
DIGEST_MAX_CHARS = 8000


@contextmanager
def config_guard(root):
    path=Path(root)/'config.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with open(path,'a+b') as lock:
        if os.name=='nt':
            import msvcrt
            if lock.tell()==0:
                lock.write(b'0'); lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_LOCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name=='nt':
                lock.seek(0); msvcrt.locking(lock.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with open(tmp, 'x', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def tokens(text):
    out = set(re.findall(r'[a-zA-Z0-9_]+', text.lower()))
    for run in re.findall(r'[\u3400-\u9fff]+', text):
        out.update(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            out.add(run)
    return sorted(out)


def scope_ok(scope):
    if scope != 'owner-private' and not re.fullmatch(r'qq:(group|c2c):[A-Za-z0-9_-]{1,128}', scope or ''):
        raise ValueError('invalid_scope')
    return scope


def _emotion_explicitly_disabled(brain, q):
    """v1 (2026-11-04): explicit-disable pre-check for the emotion path.

    Returns True ONLY when the trusted local config actually reads as off:
    enabled=false (master), modules.mood=false,
    features.emotion_events=false, features.events=false.
    Missing keys / unreadable config / corrupt config are NOT explicit disable
    (they surface as errors elsewhere); model input is never consulted.
    """
    try:
        c = brain.config()
    except Exception:
        return False
    if not isinstance(c, dict):
        return False
    if c.get('enabled', True) is False:
        return True
    mods = c.get('modules')
    if isinstance(mods, dict) and mods.get('mood', True) is False:
        return True
    feats = c.get('features')
    if isinstance(feats, dict):
        if feats.get('emotion_events', True) is False:
            return True
        if feats.get('events', True) is False:
            return True
    return False


class Brain:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root/'config.json'
        if not self.config_path.exists():
            atomic_json(self.config_path, dict(version=VERSION, enabled=False, epoch=0,
                                              modules={k: True for k in MODULES}))
        self.db_path = self.root/'data'/'brain.sqlite'
        self.db_path.parent.mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.db_path, timeout=.08)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS memories(
          id INTEGER PRIMARY KEY, scope TEXT NOT NULL, text TEXT NOT NULL,
          kind TEXT NOT NULL, source TEXT NOT NULL, event_id TEXT NOT NULL,
          evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          importance REAL NOT NULL, occurred_at REAL NOT NULL, created_at REAL NOT NULL,
          supersedes INTEGER, fingerprint TEXT NOT NULL,
          UNIQUE(scope,event_id,kind,fingerprint));
        CREATE INDEX IF NOT EXISTS memory_scope ON memories(scope,status,occurred_at);
        CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(terms,scope UNINDEXED);
        CREATE TABLE IF NOT EXISTS entities(memory_id INTEGER,scope TEXT,name TEXT,
          UNIQUE(memory_id,name));
        CREATE INDEX IF NOT EXISTS entity_scope ON entities(scope,name);
        CREATE TABLE IF NOT EXISTS mood(scope TEXT PRIMARY KEY,p REAL,a REAL,d REAL,at REAL);
        CREATE TABLE IF NOT EXISTS emotion(scope TEXT,label TEXT,intensity REAL,reason TEXT,at REAL,
          PRIMARY KEY(scope,label));
        CREATE TABLE IF NOT EXISTS candidates(
          id INTEGER PRIMARY KEY, scope TEXT NOT NULL, text TEXT NOT NULL,
          sources TEXT NOT NULL, topic TEXT NOT NULL, fingerprint TEXT UNIQUE NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending', lease TEXT, epoch INTEGER,
          created_at REAL NOT NULL, claimed_at REAL, finished_at REAL);
        CREATE TABLE IF NOT EXISTS news_ledger(
          id INTEGER PRIMARY KEY, scope TEXT NOT NULL, story_key TEXT NOT NULL,
          canonical_url TEXT NOT NULL, subject TEXT NOT NULL, event TEXT NOT NULL,
          phase TEXT NOT NULL, title TEXT NOT NULL, source_url TEXT NOT NULL,
          publish_date TEXT, event_date TEXT, score REAL NOT NULL,
          score_breakdown TEXT NOT NULL, interest_basis TEXT NOT NULL,
          reason TEXT NOT NULL, candidate_id INTEGER,
          status TEXT NOT NULL DEFAULT 'pending', created_at REAL NOT NULL,
          audit_json TEXT,
          UNIQUE(scope, story_key));
        CREATE INDEX IF NOT EXISTS news_story ON news_ledger(scope, story_key);
        CREATE INDEX IF NOT EXISTS news_url ON news_ledger(scope, canonical_url);
        ''')
        self.db.commit()
        # Optional extension import keeps copied v1 core fixtures operable.
        try:
            from muse_ext.events import initialize
        except ModuleNotFoundError as exc:
            if exc.name not in ('muse_ext', 'muse_ext.events'):
                raise
        else:
            initialize(self.db)
        if os.name != 'nt':
            os.chmod(self.root, 0o700)
            os.chmod(self.db_path, 0o600)
            os.chmod(self.config_path, 0o600)

    def close(self):
        self.db.close()

    def _proactive_gate(self):
        """Quiet-hours gate for proactive life/news only. Uses actual system
        clock; request-supplied `now` cannot bypass. Returns None if allowed,
        else a refusal dict (not a failure: never auto-retried as a send failure).
        FAIL CLOSED: import/policy errors refuse proactive (policy_unavailable),
        never silently allow. QQ remember/recall unaffected."""
        if proactive_allowed is None:
            return dict(ok=False, quiet_hours=True, reason='policy_unavailable',
                        meaning='fail_closed_no_send_not_failure')
        try:
            allowed, reason = proactive_allowed(self.root)
        except Exception:
            return dict(ok=False, quiet_hours=True, reason='policy_invalid',
                        meaning='fail_closed_no_send_not_failure')
        if not allowed:
            return dict(ok=False, quiet_hours=True, reason=reason,
                        meaning='sleep_window_no_send_not_failure')
        return None

    def _revalidate_news_candidate(self, candidate, scope):
        """Re-validate news candidate against CURRENT profile/policy.
        Returns True if still valid, False if should be cancelled.
        Uses raw scores (not rounded) for strict > threshold comparison.
        Also checks expiry (72h default from publish_date)."""
        from proactive import load_policy
        try:
            # Find news ledger entry
            nl = self.db.execute(
                "SELECT * FROM news_ledger WHERE candidate_id=? AND scope=?",
                (candidate['id'], scope)).fetchone()
            if not nl or not nl['audit_json']:
                return False
            audit = json.loads(nl['audit_json'])
            policy = load_policy(self.root)
            # Expiry check: publish_date + expiry_hours
            import datetime
            expiry_hours = float(policy.get('news_expiry_hours', 72))
            pub_ds = nl['publish_date']
            if pub_ds:
                try:
                    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', pub_ds):
                        pub_dt = datetime.datetime.combine(
                            datetime.date.fromisoformat(pub_ds),
                            datetime.time.min).replace(tzinfo=datetime.timezone.utc)
                    else:
                        pub_dt = datetime.datetime.fromisoformat(pub_ds.replace('Z', '+00:00'))
                    if time.time() - pub_dt.timestamp() > expiry_hours * 3600:
                        return False  # expired
                except ValueError:
                    pass
            # Re-read interests: check if interest_id still exists and basis unchanged
            interests_path = Path(self.root) / 'interests.json'
            interests_data = json.loads(interests_path.read_text(encoding='utf-8'))
            interest_map = {i['id']: i for i in interests_data.get('interests', [])}
            interest = interest_map.get(audit.get('interest_id'))
            if not interest:
                return False  # interest revoked
            # Recalculate with CURRENT policy (threshold may have risen)
            basis = interest.get('basis', 'inferred').lower()
            w = policy['news_weights']
            penalty = float(policy.get('inferred_relevance_penalty', 0.65))
            rel_adj = audit['relevance'] * (penalty if basis == 'inferred' else 1.0)
            score_raw = rel_adj * w['relevance'] + audit['utility'] * w['utility'] + audit['novelty'] * w['novelty']
            if not (score_raw > float(policy['news_threshold'])):
                return False  # threshold raised or scores no longer pass
            return True
        except Exception:
            return False

    def _proactive_gate_in_lock(self):
        """Re-check real time INSIDE config_guard+SQLite transaction.
        Prevents cross-boundary send if quiet hours began while waiting for lock.
        Note: native final delivery cannot be atomically controlled; a message
        already accepted by the platform cannot be retracted."""
        return self._proactive_gate()

    def _enqueue_gate(self):
        """Gate for background enqueue (life/news candidate creation).
        Quiet hours ALLOWED (accumulate to pending); hard failures still refuse:
        master switch/module off, policy unavailable/invalid. Fail closed.
        Production gate NEVER accepts caller-supplied time."""
        if proactive_allowed is None:
            return dict(ok=False, quiet_hours=True, reason='policy_unavailable',
                        meaning='fail_closed_no_send_not_failure')
        try:
            from proactive import load_policy, validate_policy
            validate_policy(load_policy(self.root))
        except Exception:
            return dict(ok=False, quiet_hours=True, reason='policy_invalid',
                        meaning='fail_closed_no_send_not_failure')
        if not self.available('life'):
            return dict(ok=False, disabled=True)
        return None

    def _enqueue_gate_in_lock(self):
        """In-transaction re-check for enqueue: config still on, policy still
        valid. Quiet hours do NOT block enqueue (accumulate, notify later)."""
        return self._enqueue_gate()

    def _validate_score(self, v, name):
        """Validate score is finite float in [0,1]. Reject NaN/Infinity/bool/out-of-range.
        Do NOT silently clamp."""
        if isinstance(v, bool):
            raise ValueError(f'invalid_score_{name}_bool')
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise ValueError(f'invalid_score_{name}_type')
        if not math.isfinite(f):
            raise ValueError(f'invalid_score_{name}_nonfinite')
        if not (0.0 <= f <= 1.0):
            raise ValueError(f'invalid_score_{name}_range')
        return f

    def _news_op(self, q, scope):
        """News candidate entry. Code validates and scores; model judges semantics only.
        News MUST use this entry; cannot bypass via normal life op."""
        from proactive import load_policy, story_key, normalize_url
        # Enqueue gate: quiet hours ALLOWED (accumulate to pending + ledger).
        # Scoring (>70), interest basis, public source/date, 72h expiry and
        # transactional dedup below are unchanged. Notify path stays gated.
        gate = self._enqueue_gate()
        if gate:
            return gate
        policy = load_policy(self.root)
        # Required fields
        subject = q.get('subject', '')
        event = q.get('event', '')
        phase = q.get('phase', 'initial')
        title = q.get('title', '')
        source_url = q.get('source_url', '')
        if not all(isinstance(s, str) and s.strip() for s in [subject, event, title, source_url]):
            raise ValueError('invalid_news_fields')
        if len(title) > 500 or len(source_url) > 2000:
            raise ValueError('invalid_news_length')
        # URL must be valid http(s)
        import urllib.parse
        u = urllib.parse.urlparse(source_url.strip())
        if u.scheme.lower() not in ('http', 'https') or not u.netloc:
            raise ValueError('invalid_news_url')
        # Dates: publish_date REQUIRED and verifiable; event_date optional but not fabricated.
        # date-only: compared against Beijing today, must not be future.
        # with-time: must include timezone, compared against actual clock, must not be future (5min skew allowed).
        # Old news keeps actual date (novelty downscores via model). Code validates format/timing;
        # authority and body authenticity verified by model reading.
        import datetime
        from proactive import beijing_now
        now_bj = beijing_now()
        today_bj = now_bj.date()
        def _parse_news_date(ds, key, required):
            if not ds:
                if required:
                    raise ValueError(f'missing_{key}')
                return None
            if not isinstance(ds, str):
                raise ValueError(f'invalid_news_{key}')
            ds = ds.strip()
            # date-only: YYYY-MM-DD
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', ds):
                try:
                    d = datetime.date.fromisoformat(ds)
                except ValueError:
                    raise ValueError(f'invalid_news_{key}_format')
                if d > today_bj:
                    raise ValueError(f'news_{key}_future')
                return ds
            # with-time: must include timezone
            try:
                dt = datetime.datetime.fromisoformat(ds.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError(f'invalid_news_{key}_format')
            if dt.tzinfo is None:
                raise ValueError(f'news_{key}_missing_tz')
            # Compare against actual clock, 5min skew allowed
            if dt.timestamp() > time.time() + 300:
                raise ValueError(f'news_{key}_future')
            return ds
        publish_date = _parse_news_date(q.get('publish_date'), 'publish_date', required=True)
        event_date = _parse_news_date(q.get('event_date'), 'event_date', required=False)
        # Expiry: news candidates expire after news_expiry_hours (default 72) from publish_date.
        # Prevents pushing old news days later. Only for news, not private reminders.
        expiry_hours = float(policy.get('news_expiry_hours', 72))
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', publish_date):
                pub_dt = datetime.datetime.combine(
                    datetime.date.fromisoformat(publish_date),
                    datetime.time.min).replace(tzinfo=datetime.timezone.utc)
            else:
                pub_dt = datetime.datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
                if pub_dt.tzinfo is None:
                    pub_dt = pub_dt.replace(tzinfo=datetime.timezone.utc)
            if time.time() - pub_dt.timestamp() > expiry_hours * 3600:
                return dict(ok=True, passes=False, reason='expired_no_candidate',
                            meaning='news_too_old')
        except ValueError:
            pass  # date already validated above; defensive
        # Phase: non-empty string, length limit
        if not isinstance(phase, str) or not phase.strip() or len(phase) > 120:
            raise ValueError('invalid_news_phase')
        # Scores: validate finite 0..1 (no silent clamp)
        rel = self._validate_score(q.get('relevance'), 'relevance')
        util = self._validate_score(q.get('utility'), 'utility')
        nov = self._validate_score(q.get('novelty'), 'novelty')
        # Basis: MUST come from local interests.json whitelist via interest_id.
        # q may ONLY pass interest_id; any q.interest_basis self-claim is IGNORED.
        # Unknown ID -> reject. This prevents forging 'confirmed'.
        interest_id = q.get('interest_id', '')
        if not isinstance(interest_id, str) or not interest_id.strip():
            raise ValueError('missing_interest_id')
        interests_path = Path(self.root) / 'interests.json'
        try:
            interests_data = json.loads(interests_path.read_text(encoding='utf-8'))
        except Exception:
            raise ValueError('interests_unavailable')
        interest_map = {i['id']: i for i in interests_data.get('interests', [])
                        if isinstance(i, dict) and 'id' in i}
        interest = interest_map.get(interest_id.strip())
        if not interest:
            raise ValueError('unknown_interest_id')
        basis = interest.get('basis', 'inferred').lower()
        if basis not in ('confirmed', 'inferred'):
            basis = 'inferred'
        interest_topic = interest.get('topic', '')
        interest_source = interest.get('source', '')
        # Score: inferred multiplier from config (default 0.65; 0.5 maxes at 70, never passes strict >70)
        w = policy['news_weights']
        penalty = float(policy.get('inferred_relevance_penalty', 0.65))
        rel_adj = rel * (penalty if basis == 'inferred' else 1.0)
        # Strict >70, do NOT round before compare
        score_raw = rel_adj * w['relevance'] + util * w['utility'] + nov * w['novelty']
        threshold = float(policy['news_threshold'])
        passes = score_raw > threshold
        score = round(score_raw, 1)
        breakdown = {
            'relevance': round(rel_adj * w['relevance'], 1),
            'utility': round(util * w['utility'], 1),
            'novelty': round(nov * w['novelty'], 1),
        }
        if not passes:
            # Low score: do NOT create candidate
            return dict(ok=True, passes=False, score=score, breakdown=breakdown,
                        reason='below_threshold_no_candidate')
        # Dedup: story_key unique per scope; also check canonical_url+phase
        sk = story_key(subject, event, phase)
        canon = normalize_url(source_url)
        # Sources: REQUIRED 1..20 active same owner-private non-inference memories.
        # Sources must record public article URL and actual date for traceability.
        # Empty sources -> reject, no candidate (valid_sources(all([])) would be vacuous true).
        sources = q.get('sources', [])
        if not isinstance(sources, list) or not (1 <= len(sources) <= 20):
            raise ValueError('invalid_news_sources_count')
        ids = sorted(set(int(x) for x in sources))
        if not (1 <= len(ids) <= 20):
            raise ValueError('invalid_news_sources_count')
        for mid in ids:
            r = self.db.execute("SELECT 1 FROM memories WHERE id=? AND scope=? AND status='active' AND evidence!='inference'",(mid,scope)).fetchone()
            if not r:
                raise ValueError('news_source_not_in_scope_or_inactive')
        # Fingerprint: story_key ONLY (not source IDs) to prevent bypass via new sources
        fp = hashlib.sha256(json.dumps([scope, sk]).encode()).hexdigest()
        reason = q.get('reason', '')
        if not isinstance(reason, str) or len(reason) > 1000:
            raise ValueError('invalid_news_reason')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            # Re-check enabled/life/policy INSIDE transaction (avoid lock-wait
            # boundary crossing). Quiet hours do NOT block enqueue.
            gate2 = self._enqueue_gate_in_lock()
            if gate2:
                self.db.rollback()
                return gate2
            # Check existing by story_key OR (canonical_url + phase)
            # Same phase different media -> story_key dedup; new phase allows substantive progress.
            existing = self.db.execute(
                "SELECT id, candidate_id FROM news_ledger WHERE scope=? AND (story_key=? OR (canonical_url=? AND phase=?))",
                (scope, sk, canon, phase.strip())).fetchone()
            if existing:
                self.db.commit()
                return dict(ok=True, passes=True, score=score, breakdown=breakdown,
                            duplicate=True, news_id=existing['id'],
                            candidate_id=existing['candidate_id'])
            # Create news ledger entry + candidate (same transaction)
            # Candidate fingerprint excludes source IDs (uses story_key)
            # Audit: persist interest_id/source/basis/raw scores (not just return value)
            audit = {
                'interest_id': interest_id.strip(),
                'interest_topic': interest_topic,
                'interest_source': interest_source,
                'interest_basis': basis,
                'relevance': rel, 'utility': util, 'novelty': nov,
                'raw_score': score_raw, 'threshold': threshold,
                'breakdown': breakdown,
            }
            cur = self.db.execute(
                '''INSERT INTO news_ledger(scope, story_key, canonical_url, subject, event, phase,
                   title, source_url, publish_date, event_date, score, score_breakdown,
                   interest_basis, reason, candidate_id, status, created_at, audit_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?, NULL, 'pending', ?, ?)''',
                (scope, sk, canon, subject.strip(), event.strip(), phase.strip(),
                 title.strip(), source_url.strip(),
                 publish_date, event_date,
                 score, json.dumps(breakdown), basis, reason.strip(), time.time(),
                 json.dumps(audit, ensure_ascii=False)))
            news_id = cur.lastrowid
            # Create candidate linked to news (fingerprint = story_key, not sources)
            # Candidate text MUST include real source_url/date, not just title+reason
            cand_text = f"【新闻】{title.strip()}\n来源：{source_url.strip()}\n日期：{publish_date}\n{reason.strip()}"
            self.db.execute(
                '''INSERT OR IGNORE INTO candidates(scope,text,sources,topic,fingerprint,created_at)
                   VALUES(?,?,?,?,?,?)''',
                (scope, cand_text[:2400], json.dumps(ids), f"news:{sk[:60]}", fp, time.time()))
            cid = self.db.execute('SELECT id FROM candidates WHERE fingerprint=?',(fp,)).fetchone()[0]
            self.db.execute('UPDATE news_ledger SET candidate_id=? WHERE id=?', (cid, news_id))
            self.db.commit()
        return dict(ok=True, passes=True, score=score, breakdown=breakdown,
                    news_id=news_id, candidate_id=cid, interest_basis=basis,
                    interest_id=interest_id.strip(), interest_topic=interest_topic,
                    interest_source=interest_source)

    def config(self):
        cfg = json.loads(self.config_path.read_text(encoding='utf-8'))
        if not isinstance(cfg.get('enabled'), bool) or not isinstance(cfg.get('epoch'), int):
            raise ValueError('invalid_config')
        return cfg

    def available(self, module):
        c = self.config()
        return c['enabled'] and c.get('modules', {}).get(module, False)

    def feature(self, name):
        c = self.config()
        return c['enabled'] and c.get('features', {}).get(name) is True

    def _remember(self, q, supersedes=None):
        text = q.get('text', '')
        source = q.get('source', '')
        event_id = q.get('event_id', '')
        kind = q.get('kind', 'episode')
        evidence = q.get('evidence', 'observed')
        if not isinstance(text, str) or not text.strip() or len(text) > 12000:
            raise ValueError('invalid_text')
        if not isinstance(source, str) or not source.strip() or len(source)>1000:
            raise ValueError('invalid_source')
        if not isinstance(event_id, str) or not event_id or len(event_id)>256:
            raise ValueError('invalid_event')
        if kind not in KINDS or evidence not in ('confirmed', 'observed', 'inference'):
            raise ValueError('invalid_kind_or_evidence')
        if source.startswith(('assistant:', 'life:')) and evidence != 'inference':
            raise ValueError('generated_content_is_inference')
        scope = scope_ok(q.get('scope'))
        at = float(q.get('occurred_at', time.time()))
        importance = float(q.get('importance', .6))
        if not math.isfinite(at) or not math.isfinite(importance):
            raise ValueError('invalid_number')
        fingerprint = hashlib.sha256((text+('\0corrects:'+str(supersedes) if supersedes is not None else '')).encode()).hexdigest()
        row = self.db.execute('SELECT id FROM memories WHERE scope=? AND event_id=? AND kind=? AND fingerprint=?',
                              (scope, event_id, kind, fingerprint)).fetchone()
        if row:
            return row['id']
        cur = self.db.execute('''INSERT INTO memories(scope,text,kind,source,event_id,evidence,importance,
                              occurred_at,created_at,supersedes,fingerprint) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                              (scope,text,kind,source,event_id,evidence,max(0,min(1,importance)),at,time.time(),supersedes,fingerprint))
        mid = cur.lastrowid
        entities = q.get('entities',[])
        if not isinstance(entities,list) or len(entities)>30 or any(not isinstance(x,str) or not x or len(x)>80 for x in entities):
            raise ValueError('invalid_entities')
        self.db.execute('INSERT INTO search(rowid,terms,scope) VALUES(?,?,?)', (mid, ' '.join(tokens(text+' '+' '.join(entities))),scope))
        for entity in set(entities):
            self.db.execute('INSERT INTO entities VALUES(?,?,?)',(mid,scope,entity))
        return mid

    def valid_sources(self, candidate):
        return all(self.db.execute("SELECT 1 FROM memories WHERE id=? AND scope=? AND status='active' AND evidence!='inference'",(mid,candidate['scope'])).fetchone()
                   for mid in json.loads(candidate['sources']))

    def recall(self, q):
        if not self.available('memory'):
            return dict(ok=True, memories=[], disabled=True)
        scope = scope_ok(q.get('scope'))
        text = q.get('text', '')
        if not isinstance(text, str) or len(text)>12000:
            raise ValueError('invalid_query')
        temporal = None
        if self.feature('time_query'):
            from muse_ext.temporal import resolve_query
            temporal = resolve_query(text)
            if temporal:
                explicit = 'start' in q or 'end' in q
                q = dict(q, **{k:v for k,v in temporal.items() if k in (('actor',) if explicit else ('start','end','actor')) and v is not None}, text=temporal['query'])
                text = q['text']
        if self.feature('vector'):
            from muse_ext.retrieval import recall
            response = recall(self,q)
            if self.feature('events') and ('start' in q or 'end' in q):
                from muse_ext.events import recall_events
                response['events'] = recall_events(self,q)
            if temporal:
                response['temporal'] = temporal
            if self.feature('consolidation'):
                from muse_ext.consolidation import apply_views
                response = apply_views(self,response,scope)
                from muse_ext.insights import recall as recall_insights
                response['insights'] = recall_insights(self,q)
            return response
        terms = tokens(text)[:64]
        params = [scope]
        where = "m.scope=? AND m.status='active' AND m.evidence!='inference'"
        for key, sql in [('start','m.occurred_at>=?'), ('end','m.occurred_at<?')]:
            if key in q:
                n = float(q[key])
                if not math.isfinite(n):
                    raise ValueError('invalid_time')
                where += ' AND '+sql
                params.append(n)
        if terms:
            where += ' AND m.id IN (SELECT rowid FROM search WHERE search MATCH ? AND scope=?)'
            params += [' OR '.join('"'+t.replace('"','""')+'"' for t in terms),scope]
        elif not ('start' in q or 'end' in q):
            return dict(ok=True, memories=[])
        rows = self.db.execute('SELECT m.* FROM memories m WHERE '+where+' ORDER BY occurred_at DESC LIMIT 300', params).fetchall()
        query = set(terms)
        now = time.time()
        def score(r):
            overlap = len(query.intersection(tokens(r['text'])))/max(1,len(query)) if query else 0
            recent = math.exp(-max(0,now-r['occurred_at'])/(86400*60))
            return overlap*.7 + r['importance']*.2 + recent*.1
        ranked = sorted(rows,key=score,reverse=True)
        result, budget = [], 2400
        for row in ranked:
            if len(result)>=6 or budget<=0:
                break
            item = {k:row[k] for k in ('id','text','kind','source','event_id','evidence','occurred_at')}
            item['text'] = item['text'][:budget]
            item['truncated'] = len(item['text'])<len(row['text'])
            budget -= len(item['text'])
            result.append(item)
        response = dict(ok=True,memories=result,retrieval='local_keyword_time_importance',vector=False)
        if self.feature('events') and ('start' in q or 'end' in q):
            from muse_ext.events import recall_events
            response['events'] = recall_events(self, q)
        if temporal:
            response['temporal'] = temporal
        if self.feature('consolidation'):
            from muse_ext.consolidation import apply_views
            response = apply_views(self,response,scope)
            from muse_ext.insights import recall as recall_insights
            response['insights'] = recall_insights(self,q)
        return response

    def dispatch(self, q):
        op = q.get('op')
        if op == 'configure':
            with config_guard(self.root):
                c = self.config()
                if 'enabled' in q:
                    if not isinstance(q['enabled'],bool):
                        raise ValueError('invalid_enabled')
                    c['enabled'] = q['enabled']
                    c['epoch'] += 1
                for key,val in q.get('modules',{}).items():
                    if key not in MODULES or not isinstance(val,bool):
                        raise ValueError('invalid_module')
                    c['modules'][key] = val
                for key,val in q.get('features',{}).items():
                    if key not in FEATURES or not isinstance(val,bool):
                        raise ValueError('invalid_feature')
                    c.setdefault('features',{})[key] = val
                    c['epoch'] += 1
                atomic_json(self.config_path,c)
            return dict(ok=True,**c)
        if op == 'health':
            return dict(ok=True, version=VERSION, config=self.config(),
                        integrity=self.db.execute('PRAGMA quick_check').fetchone()[0],
                        counts={t:self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                                for t in ('memories','candidates')})
        if op == 'backup':
            folder = self.root/'backups'
            folder.mkdir(exist_ok=True)
            dest = folder/(str(time.time_ns())+'.sqlite')
            other = sqlite3.connect(dest)
            try:
                self.db.backup(other)
            finally:
                other.close()
            # Retain seven newest online backups; unlink only files produced here.
            for old in sorted(folder.glob('[0-9]*.sqlite'),reverse=True)[7:]:
                old.unlink()
            return dict(ok=True,path=str(dest))
        scope = scope_ok(q.get('scope'))
        if op == 'expression':
            from muse_ext.expression import dispatch
            return dispatch(self,q)
        if op == 'reminder':
            from muse_ext.reminders import dispatch
            return dispatch(self,q)
        if op == 'vector_index':
            from muse_ext.embeddings import index_pending
            return index_pending(self,q.get('limit',20))
        if op == 'consolidate':
            from muse_ext.consolidation import dispatch
            return dispatch(self,q)
        if op == 'reading':
            from muse_ext.reading import dispatch
            return dispatch(self,q)
        if op == 'derive':
            from muse_ext.insights import derive
            return derive(self,q)
        if op == 'capture':
            # v1: capture only. No emotion side effect; assessment comes later
            # via prepare-with-assessment referencing the same event_id.
            from muse_ext.events import capture_event
            event = capture_event(self,q)
            return dict(ok=True,event=event,emotion={'status':'pending_assessment'},
                        mood=self.dispatch(dict(op='mood',scope=scope)))
        if op == 'prepare':
            event, emotion = None, None
            if _emotion_explicitly_disabled(self, q):
                # Explicit local disable: honest status, zero emotion writes.
                # No capture, no submit. (Corrupt config / missing keys are NOT
                # explicit and fall through to the normal/error paths below.)
                emotion = {'status': 'disabled_by_config'}
            elif self.feature('events'):
                from muse_ext.events import capture_event
                from muse_ext.emotion import submit_assessment
                event = capture_event(self,q)
                # v1 model-judged protocol: no assessment -> explicit 'missing'
                # (no keyword fallback); invalid -> explicit 'invalid'. Neither
                # consumes the event's assessment opportunity.
                raw = q.get('emotion_assessment', None)
                if raw is None:
                    emotion = {'status':'missing'}
                else:
                    emotion = submit_assessment(self,event.get('id'),raw)
            recalled=self.recall(q)
            result = dict(recalled,mood=self.dispatch(dict(op='mood',scope=scope)),
                        event=event,emotion=emotion,
                        style=self.dispatch(dict(op='style',scope=scope,sender_type=q.get('sender_type'))))
            return result
        if op == 'ingest':
            if not self.available('input'):
                return dict(ok=False,disabled=True)
            attachments=q.get('attachments',[])
            if not isinstance(attachments,list) or len(attachments)>20:
                raise ValueError('invalid_attachments')
            parts=[q.get('text','')]
            for a in attachments:
                if not isinstance(a,dict) or a.get('type') not in ('image','audio','video','link','file'):
                    raise ValueError('invalid_attachment')
                parsed=a.get('text') if a.get('status')=='parsed' else None
                parts.append('['+a['type']+'] '+(parsed if isinstance(parsed,str) and parsed else '未解析：无内容证据'))
            return self.dispatch(dict(q,op='remember',text='\n'.join(parts),kind='episode',evidence='observed'))
        if op == 'maintain':
            if not self.available('feedback'):
                return dict(ok=False,disabled=True)
            cutoff=float(q.get('now',time.time()))-180*86400
            if not math.isfinite(cutoff):
                raise ValueError('invalid_time')
            with self.db:
                cur=self.db.execute("UPDATE memories SET status='archived' WHERE scope=? AND kind='episode' AND importance<.9 AND occurred_at<? AND status='active'",(scope,cutoff))
            return dict(ok=True,archived=cur.rowcount,deleted=0)
        if op == 'recall':
            return self.recall(q)
        if op in ('remember','correct','forget'):
            if not self.available('memory'):
                return dict(ok=False,disabled=True)
            if op in ('correct','forget') and not self.available('feedback'):
                return dict(ok=False,disabled=True)
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                old = None
                if op in ('correct','forget'):
                    old = self.db.execute("SELECT * FROM memories WHERE id=? AND scope=? AND status='active'",(q.get('id'),scope)).fetchone()
                    if not old:
                        raise ValueError('memory_not_in_scope_or_inactive')
                if op == 'forget':
                    from muse_ext.consolidation import invalidate_group
                    invalidate_group(self,old,'forgotten')
                    self.db.execute("UPDATE memories SET status='forgotten' WHERE id=?",(old['id'],))
                    try:
                        from muse_ext.events import hide_original
                    except ModuleNotFoundError:
                        pass
                    else:
                        hide_original(self,old)
                    return dict(ok=True,id=old['id'])
                if op == 'correct':
                    if q.get('text')==old['text']:
                        return dict(ok=True,id=old['id'],unchanged=True)
                    q = dict(q, evidence='confirmed',kind=old['kind'])
                mid = self._remember(q, old['id'] if old else None)
                if old:
                    from muse_ext.consolidation import invalidate_group
                    invalidate_group(self,old,'superseded')
                    self.db.execute("UPDATE memories SET status='superseded' WHERE id=?",(old['id'],))
                return dict(ok=True,id=mid)
        if op == 'mood':
            if not self.available('mood'):
                return dict(ok=True,disabled=True)
            now = float(q.get('now',time.time()))
            if not math.isfinite(now):
                raise ValueError('invalid_time')
            row = self.db.execute('SELECT * FROM mood WHERE scope=?',(scope,)).fetchone()
            factor = .5**(max(0,now-row['at'])/21600) if row else 1
            vals = {k:(row[k]*factor if row else 0) for k in ('p','a','d')}
            for k,v in q.get('delta',{}).items():
                if k not in vals or not math.isfinite(float(v)):
                    raise ValueError('invalid_mood')
                vals[k] = max(-1,min(1,vals[k]+max(-.12,min(.12,float(v)))))
            if q.get('delta'):
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO mood VALUES(?,?,?,?,?)',(scope,vals['p'],vals['a'],vals['d'],now))
            label=q.get('label')
            if label:
                reason=q.get('reason','')
                if not isinstance(label,str) or len(label)>30 or not isinstance(reason,str) or len(reason)>300:
                    raise ValueError('invalid_emotion')
                previous=self.db.execute('SELECT * FROM emotion WHERE scope=? AND label=?',(scope,label)).fetchone()
                intensity=min(.6,(previous['intensity']*.5**(max(0,now-previous['at'])/2700) if previous else 0)+.1)
                with self.db:
                    self.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)',(scope,label,intensity,reason,now))
            labels=[]
            for r in self.db.execute('SELECT * FROM emotion WHERE scope=?',(scope,)):
                intensity=r['intensity']*.5**(max(0,now-r['at'])/2700)
                if intensity>.01:
                    labels.append(dict(label=r['label'],intensity=intensity,reason=r['reason']))
            return dict(ok=True,**vals,labels=labels,at=now,meaning='tone_only_not_user_facts')
        if op == 'style':
            if not self.available('style'):
                return dict(ok=True,disabled=True)
            task=q.get('scene')=='task'
            return dict(ok=True,mention='first_only' if q.get('sender_type')=='bot' else 'none',allow_detail=task,
                        guidance=('认真任务可展开步骤、证据与限制' if task else '熟人闲聊自然短句，不强行列点总结')+'；保留当前机器人的原有人设；不改写事实、不删除回答、不增加模型调用')
        if op == 'proactive_check':
            # Lightweight startup check: enabled/life + quiet-hours gate.
            # Returns actual policy state; NOT just reading rule text.
            # background_allowed: master switch + life module + policy valid
            #   (quiet hours do NOT block background work: read/analyze/enqueue).
            # can_notify: background_allowed AND actual Beijing time outside
            #   01:00-07:00 (claim/authorize/finish/digest notify path only).
            # `proactive` is kept as can_notify for backward compatibility.
            # Honest limitation: this checks at call time. Native final delivery
            # has no atomic time bound; a message accepted by the platform before
            # 01:00 cannot be retracted if delivery completes after 01:00.
            # The in-lock re-check minimizes but does not absolutely prevent
            # cross-boundary delivery.
            bg_gate = self._enqueue_gate()
            background_allowed = bg_gate is None
            gate = self._proactive_gate()
            quiet_hours = gate is not None
            can_notify = background_allowed and not quiet_hours
            if not background_allowed:
                reason = bg_gate.get('reason', 'disabled')
                meaning = ('life_module_off' if reason == 'disabled'
                           else 'fail_closed_no_send_not_failure')
            elif quiet_hours:
                reason = gate.get('reason')
                meaning = 'sleep_window_no_proactive'
            else:
                reason = 'ok'
                meaning = 'proactive_allowed'
            return dict(ok=True, proactive=can_notify,
                        background_allowed=background_allowed,
                        can_notify=can_notify, quiet_hours=quiet_hours,
                        reason=reason, meaning=meaning)
        if op in ('life','candidates','claim','finish','authorize','news',
                   'digest_claim','digest_authorize','digest_finish'):
            if not self.available('life'):
                return dict(ok=False,disabled=True,candidate=None,candidates=[])
            if scope != 'owner-private':
                raise ValueError('life_owner_only')
            if op == 'news':
                return self._news_op(q, scope)
            if op == 'life':
                # Enqueue gate: quiet hours ALLOWED (accumulate to pending).
                # Notify path (claim/authorize/finish) stays strictly gated.
                gate = self._enqueue_gate()
                if gate:
                    return gate
                text, sources, topic = q.get('text',''), q.get('sources'),q.get('topic','')
                if not isinstance(text,str) or not text.strip() or len(text)>2400 or not isinstance(sources,list) or not sources or len(sources)>20 or not isinstance(topic,str) or not topic.strip() or len(topic)>120:
                    raise ValueError('invalid_life_note')
                ids = sorted(set(int(x) for x in sources))
                for mid in ids:
                    r = self.db.execute("SELECT 1 FROM memories WHERE id=? AND scope=? AND status='active' AND evidence!='inference'",(mid,scope)).fetchone()
                    if not r:
                        raise ValueError('life_source_not_in_scope_or_inactive')
                fp = hashlib.sha256(json.dumps([scope,ids,topic.strip().lower()]).encode()).hexdigest()
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO candidates(scope,text,sources,topic,fingerprint,created_at) VALUES(?,?,?,?,?,?)',
                                    (scope,text,json.dumps(ids),topic.strip(),fp,time.time()))
                cid = self.db.execute('SELECT id FROM candidates WHERE fingerprint=?',(fp,)).fetchone()[0]
                return dict(ok=True,id=cid,evidence='inference')
            if op == 'candidates':
                return dict(ok=True,candidates=[dict(x) for x in self.db.execute('SELECT * FROM candidates WHERE scope=? ORDER BY id DESC LIMIT 30',(scope,))])
            def _revalidate_digest_batch(lease, epoch):
                # Shared batch re-check, called INSIDE the caller's lock
                # transaction (no commit here). Re-verifies every generating row
                # under lease: scope/status/lease, EACH row's epoch == q epoch
                # (not just config), active sources, current news eligibility.
                # Returns (valid_rows, invalid_ids). Raises invalid_lease if empty.
                brows = self.db.execute(
                    "SELECT * FROM candidates WHERE lease=? AND scope=? AND status='generating'",
                    (lease, scope)).fetchall()
                if not brows:
                    raise ValueError('invalid_lease')
                bok, bad = [], []
                for brow in brows:
                    if brow['lease'] != lease or brow['epoch'] != epoch:
                        bad.append(brow['id'])
                        continue
                    if not self.valid_sources(brow):
                        bad.append(brow['id'])
                        continue
                    if brow['topic'].startswith('news:') \
                            and not self._revalidate_news_candidate(brow, scope):
                        bad.append(brow['id'])
                        continue
                    bok.append(brow)
                return bok, bad

            if op == 'digest_claim':
                channels=q.get('channels')
                if channels is not None and (not isinstance(channels,list) or not channels or any(x not in ('life','news','emotion','reading') for x in channels)):
                    raise ValueError('invalid_candidate_channels')
                # Morning batch digest: atomically claim a BOUNDED selection of
                # valid pendings (oldest first, at most DIGEST_MAX_ITEMS and
                # DIGEST_MAX_CHARS) under ONE global lease. Unselected pendings
                # stay pending for later rounds (never dropped). The first
                # pending is always selected even if over budget, so one
                # overlong item cannot starve the queue (digested alone).
                # Notify path: strict quiet gate (no night send).
                # Stale generating leases (>3600s or epoch mismatch) are reset to
                # pending (never notified -> not lost); fresh ones mean another
                # worker holds the batch -> busy.
                gate = self._proactive_gate()
                if gate:
                    return dict(gate, candidates=[])
                if not self.available('life'):
                    return dict(ok=False, disabled=True, candidates=[])
                if scope != 'owner-private':
                    raise ValueError('life_owner_only')
                now = time.time()
                try:
                    self.db.execute('BEGIN IMMEDIATE')
                    cfg = self.config()
                    if not cfg['enabled'] or not cfg.get('modules', {}).get('life', False):
                        self.db.rollback()
                        return dict(ok=False, disabled=True, candidates=[])
                    self.db.execute(
                        "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                        "WHERE status='generating' AND (claimed_at IS NULL OR claimed_at < ?)",
                        (now - 3600,))
                    self.db.execute(
                        "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                        "WHERE status='generating' AND epoch != ?", (cfg['epoch'],))
                    if self.db.execute(
                            "SELECT 1 FROM candidates WHERE status='generating' LIMIT 1").fetchone():
                        self.db.commit()
                        return dict(ok=True, candidates=[], busy=True)
                    valid = []
                    for candidate in self.db.execute(
                            "SELECT * FROM candidates WHERE scope=? AND status='pending' ORDER BY id",
                            (scope,)).fetchall():
                        channel=next((x for x in ('news','emotion','reading') if candidate['topic'].startswith(x+':')),'life')
                        if channels is not None and channel not in channels:
                            continue
                        if not self.valid_sources(candidate):
                            self.db.execute("UPDATE candidates SET status='cancelled' WHERE id=?",
                                            (candidate['id'],))
                        elif candidate['topic'].startswith('news:'):
                            if not self._revalidate_news_candidate(candidate, scope):
                                self.db.execute("UPDATE candidates SET status='cancelled' WHERE id=?",
                                                (candidate['id'],))
                            else:
                                valid.append(candidate)
                        else:
                            valid.append(candidate)
                    selected, chars = [], 0
                    for candidate in valid:
                        tlen = len(candidate['text'] or '')
                        if len(selected) >= DIGEST_MAX_ITEMS:
                            break
                        if selected and chars + tlen > DIGEST_MAX_CHARS:
                            break
                        selected.append(candidate)
                        chars += tlen
                    remaining = len(valid) - len(selected)
                    if not selected:
                        self.db.commit()
                        return dict(ok=True, candidates=[], remaining=remaining)
                    lease = uuid.uuid4().hex
                    sel_ids = [c['id'] for c in selected]
                    marks = ','.join('?' * len(sel_ids))
                    self.db.execute(
                        "UPDATE candidates SET status='generating', lease=?, epoch=?, claimed_at=? "
                        "WHERE id IN (%s)" % marks, (lease, cfg['epoch'], now, *sel_ids))
                    rows = self.db.execute(
                        "SELECT * FROM candidates WHERE id IN (%s)" % marks,
                        sel_ids).fetchall()
                    self.db.commit()
                    return dict(ok=True, candidates=[dict(r) for r in rows],
                                lease=lease, epoch=cfg['epoch'], remaining=remaining)
                except Exception:
                    self.db.rollback()
                    raise
            if op == 'digest_authorize':
                # Strict notify gate + in-lock real-time recheck + full batch
                # revalidation (scope/status/lease/per-row epoch, active
                # sources, current news eligibility). Any invalid item ->
                # whole batch refused this round: invalid cancelled, rest back
                # to pending. No partial authorize.
                gate = self._proactive_gate()
                if gate:
                    return gate
                if not self.available('life'):
                    return dict(ok=False, disabled=True)
                if scope != 'owner-private':
                    raise ValueError('life_owner_only')
                lease = q.get('lease')
                if not lease or not isinstance(lease, str):
                    raise ValueError('invalid_lease')
                with config_guard(self.root), self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    try:
                        gate2 = self._proactive_gate_in_lock()
                        if gate2:
                            self.db.rollback()
                            return gate2
                        cfg = self.config()
                        if (not cfg['enabled'] or q.get('epoch') != cfg['epoch']
                                or not cfg.get('modules', {}).get('life', False)):
                            self.db.rollback()
                            return dict(ok=False, disabled=True)
                        valid, invalid = _revalidate_digest_batch(lease, q.get('epoch'))
                        if invalid:
                            marks = ','.join('?' * len(invalid))
                            self.db.execute(
                                "UPDATE candidates SET status='cancelled' WHERE id IN (%s)"
                                % marks, invalid)
                            self.db.execute(
                                "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                                "WHERE lease=? AND scope=? AND status='generating'",
                                (lease, scope))
                            self.db.commit()
                            return dict(ok=False, refused=True, invalid_ids=invalid,
                                        released=len(valid),
                                        meaning='batch_revalidated_refused_no_partial')
                        self.db.commit()
                        return dict(ok=True, authorized_at=time.time(),
                                    epoch=cfg['epoch'], count=len(valid))
                    except Exception:
                        self.db.rollback()
                        raise
            if op == 'digest_finish':
                # Atomic settle of the claimed batch. `expressed_ids` lists the
                # claimed candidate ids actually expressed in the digest text;
                # they are settled with `outcome`, the REST are atomically
                # released back to pending (never marked unknown/lost).
                # The digest text must be fully prepared AND the selected id set
                # included before calling. Cross-01:00 -> whole batch refused,
                # rows stay 'generating' (reclaimable, not lost).
                # outcome 'unknown' records the handoff; it is NOT a read receipt.
                gate = self._proactive_gate()
                if gate:
                    return gate
                if not self.available('life'):
                    return dict(ok=False, disabled=True)
                if scope != 'owner-private':
                    raise ValueError('life_owner_only')
                lease = q.get('lease')
                outcome = q.get('outcome')
                expressed = q.get('expressed_ids')
                if not lease or not isinstance(lease, str):
                    raise ValueError('invalid_lease')
                if outcome not in ('accepted', 'unknown', 'failed'):
                    raise ValueError('invalid_outcome')
                if (not isinstance(expressed, list)
                        or not all(isinstance(i, int) for i in expressed)):
                    raise ValueError('invalid_expressed_ids')
                with config_guard(self.root), self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    try:
                        gate2 = self._proactive_gate_in_lock()
                        if gate2:
                            self.db.rollback()
                            return gate2
                        cfg = self.config()
                        if (not cfg['enabled'] or q.get('epoch') != cfg['epoch']
                                or not cfg.get('modules', {}).get('life', False)):
                            self.db.rollback()
                            return dict(ok=False, disabled=True)
                        valid, invalid = _revalidate_digest_batch(lease, q.get('epoch'))
                        row_ids = {r['id'] for r in valid} | set(invalid)
                        if not set(expressed) <= row_ids:
                            self.db.rollback()
                            raise ValueError('expressed_ids_not_claimed')
                        invalid_expressed = [i for i in invalid if i in set(expressed)]
                        if invalid_expressed:
                            # Whole batch refused: nothing finished unknown.
                            # Invalid -> cancelled; everything else -> pending.
                            marks = ','.join('?' * len(invalid))
                            self.db.execute(
                                "UPDATE candidates SET status='cancelled' WHERE id IN (%s)"
                                % marks, invalid)
                            self.db.execute(
                                "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                                "WHERE lease=? AND scope=? AND status='generating'",
                                (lease, scope))
                            self.db.commit()
                            return dict(ok=False, refused=True,
                                        invalid_ids=invalid_expressed,
                                        meaning='batch_revalidated_refused_no_partial')
                        now = time.time()
                        n_exp = 0
                        if expressed:
                            marks = ','.join('?' * len(expressed))
                            cur = self.db.execute(
                                "UPDATE candidates SET status=?, finished_at=? "
                                "WHERE lease=? AND scope=? AND status='generating' "
                                "AND id IN (%s)" % marks,
                                (outcome, now, lease, scope, *expressed))
                            n_exp = cur.rowcount
                            if n_exp != len(expressed):
                                self.db.rollback()
                                raise ValueError('partial_settle_refused')
                        # Release the unexpressed remainder back to pending.
                        rest_marks = ','.join('?' * len(expressed)) if expressed else ''
                        if expressed:
                            self.db.execute(
                                "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                                "WHERE lease=? AND scope=? AND status='generating' "
                                "AND id NOT IN (%s)" % rest_marks,
                                (lease, scope, *expressed))
                        else:
                            self.db.execute(
                                "UPDATE candidates SET status='pending', lease=NULL, claimed_at=NULL "
                                "WHERE lease=? AND scope=? AND status='generating'",
                                (lease, scope))
                        left = self.db.execute(
                            "SELECT COUNT(*) FROM candidates WHERE lease=? AND status='generating'",
                            (lease,)).fetchone()[0]
                        if left:
                            self.db.rollback()
                            raise ValueError('partial_settle_refused')
                        self.db.commit()
                        return dict(ok=True, status=outcome, expressed=n_exp,
                                    released=len(row_ids) - n_exp,
                                    meaning='platform_acceptance_not_read_receipt')
                    except Exception:
                        self.db.rollback()
                        raise
            if op == 'claim':
                gate = self._proactive_gate()
                if gate:
                    gate = dict(gate, candidate=None)
                    return gate
                try:
                    self.db.execute('BEGIN IMMEDIATE')
                    cfg = self.config()
                    if not cfg['enabled'] or not cfg['modules']['life']:
                        self.db.rollback()
                        return dict(ok=False,disabled=True,candidate=None)
                    # Stale leases become unknown, never automatically retried.
                    self.db.execute("UPDATE candidates SET status='unknown' WHERE status='generating' AND claimed_at<?",(time.time()-3600,))
                    self.db.execute("UPDATE candidates SET status='cancelled' WHERE status='generating' AND epoch!=?",(cfg['epoch'],))
                    if self.db.execute("SELECT 1 FROM candidates WHERE status='generating' LIMIT 1").fetchone():
                        self.db.commit()
                        return dict(ok=True,candidate=None,busy=True)
                    for candidate in self.db.execute("SELECT * FROM candidates WHERE scope=? AND status='pending'",(scope,)).fetchall():
                        if not self.valid_sources(candidate):
                            self.db.execute("UPDATE candidates SET status='cancelled' WHERE id=?",(candidate['id'],))
                        # News candidates: re-validate against CURRENT profile/policy
                        # (interest revoked or threshold raised -> cancel, do not send old)
                        elif candidate['topic'].startswith('news:'):
                            if not self._revalidate_news_candidate(candidate, scope):
                                self.db.execute("UPDATE candidates SET status='cancelled' WHERE id=?",(candidate['id'],))
                    r = self.db.execute("SELECT * FROM candidates WHERE scope=? AND status='pending' ORDER BY id LIMIT 1",(scope,)).fetchone()
                    if not r:
                        self.db.commit()
                        return dict(ok=True,candidate=None)
                    lease = uuid.uuid4().hex
                    self.db.execute("UPDATE candidates SET status='generating',lease=?,epoch=?,claimed_at=? WHERE id=?",(lease,cfg['epoch'],time.time(),r['id']))
                    self.db.commit()
                    return dict(ok=True,candidate=dict(dict(r),lease=lease,epoch=cfg['epoch']))
                except Exception:
                    self.db.rollback()
                    raise
            if op in ('finish','authorize'):
                gate = self._proactive_gate()
                if gate:
                    return gate
                with config_guard(self.root),self.db:
                    self.db.execute('BEGIN IMMEDIATE')
                    # Re-check real time INSIDE lock: fail closed if quiet hours
                    # began while waiting. Native final cannot be atomically
                    # controlled; platform-accepted messages cannot be retracted.
                    gate2 = self._proactive_gate_in_lock()
                    if gate2:
                        self.db.rollback()
                        return gate2
                    cfg = self.config()
                    if not cfg['enabled'] or q.get('epoch')!=cfg['epoch'] or not cfg.get('modules',{}).get('life',False):
                        return dict(ok=False,disabled=True)
                    candidate = self.db.execute('SELECT * FROM candidates WHERE id=? AND scope=?',(q.get('id'),scope)).fetchone()
                    if not candidate or candidate['status']!='generating' or candidate['lease']!=q.get('lease') or candidate['epoch']!=q.get('epoch'):
                        raise ValueError('invalid_lease')
                    if not self.valid_sources(candidate):
                        self.db.execute("UPDATE candidates SET status='cancelled' WHERE id=?",(candidate['id'],))
                        return dict(ok=False,stale_sources=True)
                    if op=='authorize':
                        return dict(ok=True,authorized_at=time.time(),epoch=cfg['epoch'])
                    outcome = q.get('outcome')
                    if outcome not in ('accepted','unknown','failed'):
                        raise ValueError('invalid_outcome')
                    self.db.execute("UPDATE candidates SET status=?,finished_at=? WHERE id=?",(outcome,time.time(),candidate['id']))
                    return dict(ok=True,status=outcome,meaning='platform_acceptance_not_read_receipt')
        raise ValueError('unknown_operation')


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()
    brain = None
    try:
        data = sys.stdin.buffer.read(65537)
        if len(data)>65536:
            raise ValueError('input_too_large')
        req = json.loads(data.decode('utf-8'))
        if not isinstance(req,dict):
            raise ValueError('invalid_request')
        brain = Brain(args.root)
        result = brain.dispatch(req)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except Exception as exc:
        # Never echo malformed input, SQLite SQL or a traceback containing text.
        print(json.dumps(dict(ok=False,error=type(exc).__name__)))
        return 1
    finally:
        if brain:
            brain.close()
    return 0


if __name__ == '__main__':
    sys.modules.setdefault('brain', sys.modules[__name__])
from muse_ext.companion import install as _install_companion
_install_companion(Brain)

if __name__ == '__main__':
    sys.exit(main())
