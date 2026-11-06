"""Bounded emotion reconciliation. Never sends, samples stickers or replays replies."""
import json
import uuid

SUCCESS = ('updated', 'unchanged', 'replayed')
WINDOW = 86400


def initialize(b):
    b.db.executescript('''
    CREATE TABLE IF NOT EXISTS ct_feedback(
      event INTEGER PRIMARY KEY,status TEXT NOT NULL,reason TEXT NOT NULL,
      attempts INTEGER NOT NULL DEFAULT 0,lease TEXT,lease_until REAL NOT NULL DEFAULT 0,
      created REAL NOT NULL,updated REAL NOT NULL,detail TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS ct_feedback_scan(
      id INTEGER PRIMARY KEY,at REAL NOT NULL,coverage TEXT NOT NULL,checked INTEGER NOT NULL,
      queued INTEGER NOT NULL,already_valid INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS ct_feedback_receipt(
      round_id TEXT PRIMARY KEY,output_event INTEGER NOT NULL,status TEXT NOT NULL,
      source_events TEXT NOT NULL,reconciled_at REAL NOT NULL);
    ''')


def note(b, event, result):
    if not event or result.get('status') not in ('invalid', 'missing', 'conflict'):
        return
    from muse_ext.companion import stamp
    row=b.db.execute('SELECT * FROM source_events WHERE id=?',(event,)).fetchone()
    if not row or not _eligible(b,row):
        return
    now = stamp()
    with b.db:
        b.db.execute("INSERT INTO ct_feedback(event,status,reason,created,updated,detail) "
                     "VALUES(?,'pending',?,?,?,?) ON CONFLICT(event) DO UPDATE SET "
                     "reason=CASE WHEN excluded.reason='missing' THEN ct_feedback.reason ELSE excluded.reason END,"
                     "detail=CASE WHEN excluded.detail='' THEN ct_feedback.detail ELSE excluded.detail END,updated=excluded.updated "
                     "WHERE ct_feedback.status!='repaired'",
                     (event,result['status'],now,now,str(result.get('detail', ''))[:240]))


def _eligible(b, row):
    if row['status'] != 'active' or row['scope'] != 'owner-private':
        return False
    # An assistant's own delivered sharing is not another emotional stimulus.
    return (row['actor'] == 'user' and row['source'] == 'main:sticker') or bool(
        b.db.execute('SELECT 1 FROM ct_life WHERE source_event=?',(row['id'],)).fetchone())


def scan(b, q):
    from muse_ext.companion import stamp, dump, _get, _set
    from muse_ext.events import capture_event
    now = stamp()
    incoming = q.get('native_events', [])
    if not isinstance(incoming, list) or len(incoming) > 20:
        raise ValueError('feedback_native_sample_max20')
    # Only the native adapter supplies this faithful projection. No summaries,
    # assistant outputs, legacy source names or arbitrary event identities.
    for item in incoming:
        if not isinstance(item,dict) or item.get('actor') != 'user' or item.get('source') != 'main:sticker':
            raise ValueError('feedback_actual_native_user_required')
        at = item.get('occurred_at')
        from muse_ext.companion import num
        at = num(at, 1e13)
        if now-WINDOW <= at <= now-120:
            capture_event(b,dict(item,scope='owner-private',person_id='owner'))
    checked = queued = valid = 0
    cursor=_get(b,'feedback_cursor',0)
    rows = b.db.execute("SELECT * FROM source_events WHERE scope='owner-private' AND status='active' "
                        'AND id>? AND occurred_at>=? AND occurred_at<=? ORDER BY id LIMIT 200',
                        (cursor,now-WINDOW,now-120)).fetchall()
    for row in rows:
        if not _eligible(b,row):
            continue
        checked += 1
        if b.db.execute('SELECT 1 FROM ct_appraisal WHERE event=?',(row['id'],)).fetchone():
            valid += 1
            with b.db:
                b.db.execute("UPDATE ct_feedback SET status='already_valid',updated=?,lease=NULL,lease_until=0 "
                             "WHERE event=? AND status!='repaired'",(now,row['id']))
            continue
        existed = b.db.execute('SELECT 1 FROM ct_feedback WHERE event=?',(row['id'],)).fetchone()
        note(b,row['id'],dict(status='missing'))
        queued += not bool(existed)
    coverage = q.get('coverage', {'origin':'captured_source_events_only'})
    if not isinstance(coverage,dict) or len(dump(coverage))>2000:
        raise ValueError('feedback_coverage_metadata_required')
    coverage = {k:v for k,v in coverage.items() if k in ('chat_id','page','sample_size','origin')}
    with b.db:
        # Do not move past a very recent event still inside the grace period.
        # Keeping that lower barrier makes the next heartbeat see it normally.
        barrier=b.db.execute("SELECT min(id) FROM source_events WHERE scope='owner-private' AND id>? AND occurred_at>?",
                             (cursor,now-120)).fetchone()[0]
        last=max([cursor]+[r['id'] for r in rows])
        _set(b,'feedback_cursor',min(last,barrier-1) if barrier is not None else last)
        b.db.execute('INSERT INTO ct_feedback_scan(at,coverage,checked,queued,already_valid) VALUES(?,?,?,?,?)',
                     (now,dump(coverage),checked,queued,valid))
        b.db.execute('DELETE FROM ct_feedback_scan WHERE id < (SELECT max(id)-96 FROM ct_feedback_scan)')
    return dict(ok=True,checked=checked,queued=queued,already_valid=valid,
                coverage=coverage,window_hours=24,grace_seconds=120,scan_capped=len(rows)==200)


def status(b):
    from muse_ext.companion import stamp
    counts = {r['status']:r['n'] for r in b.db.execute('SELECT status,count(*) n FROM ct_feedback GROUP BY status')}
    last = b.db.execute('SELECT * FROM ct_feedback_scan ORDER BY id DESC LIMIT 1').fetchone()
    return dict(ok=True,counts=counts,last_scan=({**dict(last),'coverage':json.loads(last['coverage'])} if last else None),
                receipt_reconciliations=b.db.execute('SELECT count(*) FROM ct_feedback_receipt').fetchone()[0],
                pending_recent=b.db.execute("SELECT count(*) FROM ct_feedback f JOIN source_events e ON e.id=f.event "
                    "WHERE f.status IN ('pending','failed','claimed') AND e.occurred_at>=?",(stamp()-WINDOW,)).fetchone()[0],
                policy='same source, original-time decay, no resend, no sticker draw, no relationship/expectation replay')


def claim(b,q):
    from muse_ext.companion import stamp, context, mood
    from muse_ext.emotion_full48 import template
    now = stamp()
    limit = q.get('limit', 2)
    if type(limit) is not int or not 1 <= limit <= 3:
        raise ValueError('feedback_claim_limit_1_to_3')
    lease = uuid.uuid4().hex
    work = []
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        rows = b.db.execute("SELECT f.*,e.occurred_at FROM ct_feedback f JOIN source_events e ON e.id=f.event "
                "WHERE f.status IN ('pending','failed','claimed') AND f.lease_until<? "
                'AND f.attempts<3 AND e.occurred_at>=? AND e.occurred_at<=? ORDER BY e.occurred_at LIMIT ?',
                (now,now-WINDOW,now-120,limit)).fetchall()
        for f in rows:
            event = b.db.execute('SELECT * FROM source_events WHERE id=?',(f['event'],)).fetchone()
            if not _eligible(b,event):
                b.db.execute("UPDATE ct_feedback SET status='ineligible',updated=? WHERE event=?",(now,f['event']))
                continue
            if b.db.execute('SELECT 1 FROM ct_appraisal WHERE event=?',(f['event'],)).fetchone():
                b.db.execute("UPDATE ct_feedback SET status='already_valid',updated=? WHERE event=?",(now,f['event']))
                continue
            b.db.execute("UPDATE ct_feedback SET status='claimed',lease=?,lease_until=?,updated=? WHERE event=?",
                         (lease,now+180,now,f['event']))
            neighbors = [dict(x) for x in b.db.execute("SELECT actor,text,occurred_at FROM source_events "
                "WHERE scope=? AND status='active' AND occurred_at<=? AND id!=? "
                'ORDER BY occurred_at DESC LIMIT 3',(event['scope'],event['occurred_at'],event['id']))]
            for n in neighbors:
                n['text'] = n['text'][:500]
            work.append(dict(source_event=event['id'],text=event['text'],source=event['source'],actor=event['actor'],
                             occurred_at=event['occurred_at'],age_seconds=now-event['occurred_at'],
                             context_before=neighbors,prior_error=f['detail'],emotion_template=template()))
    return dict(ok=True,lease=lease,events=work,companion=context(b,'owner-private'),mood=mood(b,'owner-private'),
                instructions='Use the same host model. This is retrospective inference, not exact recovered feelings. '
                'Judge each original stimulus with its earlier context; current mood is reference only. '
                'Do not infer neglect from silence or appraise assistant output. Submit full48 only; '
                'no relationship, energy, expectation or share changes. Runtime decays from original time.')


def repair(b,q):
    from muse_ext.companion import assess, stamp
    now = stamp()
    eid = q.get('source_event')
    f = b.db.execute('SELECT * FROM ct_feedback WHERE event=?',(eid,)).fetchone()
    event = b.db.execute('SELECT * FROM source_events WHERE id=?',(eid,)).fetchone()
    if not f or not event or not _eligible(b,event):
        raise ValueError('feedback_existing_original_event_required')
    if b.db.execute('SELECT 1 FROM ct_appraisal WHERE event=?',(eid,)).fetchone():
        return dict(ok=True,status='already_valid',source_event=eid,applied=False)
    if f['status']!='claimed' or f['lease']!=q.get('lease') or f['lease_until']<now:
        raise ValueError('feedback_current_claim_required')
    if not now-WINDOW <= event['occurred_at'] <= now-120:
        raise ValueError('feedback_outside_recent_window')
    raw = q.get('assessment')
    if not isinstance(raw,dict) or raw.get('format')!='full48-v1':
        raise ValueError('feedback_full48_required')
    if raw.get('relationship') or raw.get('expectations') or raw.get('share'):
        raise ValueError('feedback_no_relationship_expectation_or_send_replay')
    # assess performs the bounded, single-gain, decayed write and success guard.
    result = assess(b,eid,raw,lambda *_:dict(status='conflict'),repair=True)
    good = result.get('status') in SUCCESS
    with b.db:
        b.db.execute('UPDATE ct_feedback SET status=?,attempts=attempts+1,updated=?,lease=NULL,lease_until=0,detail=? WHERE event=?',
                     ('repaired' if good else 'failed',now,str(result.get('detail',result.get('status')))[:240],eid))
    return dict(ok=good,status='repaired' if good else 'failed',source_event=eid,emotion=result,
                original_time=event['occurred_at'],applied_at=now,age_seconds=now-event['occurred_at'],
                retrospective=True,send_actions=[],sticker_actions=[])


def dispatch(b,q):
    if not b.available('feedback') or not b.available('mood'):
        return dict(ok=False,disabled=True)
    action = q.get('action','status')
    if action=='scan': return scan(b,q)
    if action=='claim': return claim(b,q)
    if action=='repair': return repair(b,q)
    if action=='status': return status(b)
    if action=='defer':
        from muse_ext.companion import stamp
        reason=q.get('reason')
        if not isinstance(reason,str) or not reason.strip() or len(reason)>240:
            raise ValueError('feedback_defer_reason_required')
        with b.db:
            count=b.db.execute("UPDATE ct_feedback SET status='needs_context',detail=?,updated=?,lease=NULL,lease_until=0 "
                "WHERE event=? AND status='claimed' AND lease=? AND lease_until>=?",
                (reason,stamp(),q.get('source_event'),q.get('lease'),stamp())).rowcount
        if not count: raise ValueError('feedback_current_claim_required')
        return dict(ok=True,status='needs_context',mood_writes=0)
    if action=='receipt':
        from muse_ext.companion import dump,stamp
        from muse_ext.main_commit import proactive
        event=b.db.execute("SELECT * FROM source_events WHERE id=? AND scope='owner-private' AND status='active'",
                           (q.get('output_event'),)).fetchone()
        if (not event or event['source']!='main:proactive' or event['actor']!='assistant' or
                not isinstance(q.get('round_id'),str) or event['event_id']!=q['round_id']):
            raise ValueError('feedback_exact_existing_proactive_output_required')
        check=proactive(b,dict(source_events=q.get('source_events',[])))
        if not check.get('ok'): return check
        sources=dump(check['source_events'])
        old=b.db.execute('SELECT * FROM ct_feedback_receipt WHERE round_id=?',(q['round_id'],)).fetchone()
        if old and (old['output_event']!=event['id'] or old['source_events']!=sources):
            raise ValueError('feedback_receipt_source_conflict')
        with b.db:
            b.db.execute('INSERT OR IGNORE INTO ct_feedback_receipt VALUES(?,?,?,?,?)',
                         (q['round_id'],event['id'],check['emotion']['status'],sources,stamp()))
        return dict(ok=True,replayed=bool(old),source_events=check['source_events'],
                    reconciled_status=check['emotion']['status'],historical_failure_preserved=True,
                    mood_writes=0,draw_actions=[],send_actions=[])
    raise ValueError('invalid_feedback_action')
