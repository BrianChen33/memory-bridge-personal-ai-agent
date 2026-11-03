"""Small transparent tone inferences, linked once to an actual input event."""
import json
import re
import time


def observe_event(brain, event_id):
    if not brain.feature('emotion_events') or not brain.available('mood') or not event_id:
        return {'status': 'disabled'}
    with brain.db:
        brain.db.execute('BEGIN IMMEDIATE')
        row = brain.db.execute("SELECT * FROM source_events WHERE id=? AND status='active'", (event_id,)).fetchone()
        if not row or row['actor'] != 'user':
            return {'status': 'ignored'}
        if brain.db.execute('SELECT 1 FROM emotion_events WHERE event_id=?', (event_id,)).fetchone():
            return {'status': 'replayed'}
        text = row['text']
        if re.search(r'难过|压力好大|很焦虑|伤心|很累|很孤独', text):
            label, delta = '关切', {'p': -.025, 'a': .025, 'd': .015}
        elif re.search(r'说错了|请更正|不对|纠正', text):
            label, delta = '专注', {'a': .025, 'd': .015}
        elif re.search(r'谢谢|帮了大忙|做得好|喜欢你|辛苦了|开心', text):
            label, delta = '欣喜', {'p': .045, 'a': .02, 'd': .015}
        else:
            return {'status': 'no_cue'}
        now = time.time()
        old = brain.db.execute('SELECT * FROM mood WHERE scope=?', (row['scope'],)).fetchone()
        decay = .5**(max(0, now-old['at'])/21600) if old else 1
        vals = {k: max(-1, min(1, (old[k]*decay if old else 0)+delta.get(k, 0))) for k in ('p','a','d')}
        brain.db.execute('INSERT OR REPLACE INTO mood VALUES(?,?,?,?,?)',
                         (row['scope'], vals['p'], vals['a'], vals['d'], now))
        old_label = brain.db.execute('SELECT * FROM emotion WHERE scope=? AND label=?', (row['scope'], label)).fetchone()
        intensity = min(.6, .1+(old_label['intensity']*.5**(max(0,now-old_label['at'])/2700) if old_label else 0))
        reason = 'inference:source_event:'+str(event_id)+'; conversational cue, tone only'
        brain.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)', (row['scope'],label,intensity,reason,now))
        brain.db.execute('INSERT INTO emotion_events VALUES(?,?,?,?,?,?)',
                         (event_id,row['scope'],label,json.dumps(delta),'inference',now))
        previous_intensity=old_label['intensity']*.5**(max(0,now-old_label['at'])/2700) if old_label else 0
        if row['scope']=='owner-private' and previous_intensity<.25<=intensity and brain._enqueue_gate() is None:
            mid=brain._remember(dict(scope=row['scope'],text=row['text'],source=row['source'],event_id=row['event_id'],
                                    occurred_at=row['occurred_at'],kind='episode',evidence='observed',importance=.55))
            topic='emotion:'+label+':event:'+str(event_id)
            fp='emotion-event:'+str(event_id)
            note={'关切':'读到刚才的近况，我有些挂念，想关心一下你。',
                  '专注':'刚才的交流让我更专注了，我想认真把事情弄准确。',
                  '欣喜':'刚才的交流让我有些开心，想和你分享这一点。'}[label]
            brain.db.execute('INSERT OR IGNORE INTO candidates(scope,text,sources,topic,fingerprint,created_at) VALUES(?,?,?,?,?,?)',
                             (row['scope'],note,json.dumps([mid]),topic,fp,now))
    return {'status': 'updated', 'label': label, 'source_event': event_id, 'evidence': 'inference'}
