"""Source-bound commit: no capture, retrieval, file reads or presentation rebuild."""
import json
import math


def commit(b,q):
    from muse_ext.emotion_full48 import INPUT_FORMATS
    from muse_ext.companion import assess, emotion_effect, context, mood
    from muse_ext.emotion_catalog import reaction
    from muse_ext.feedback import note
    if not b.available('input') or not b.available('mood') or not b.feature('emotion_events'):
        return dict(ok=False,disabled=True,error='main_commit_disabled')
    eid=q.get('source_event')
    if type(eid) is not int:
        raise ValueError('main_commit_context_event_required')
    row=b.db.execute('SELECT * FROM source_events WHERE id=?',(eid,)).fetchone()
    if (not row or row['status']!='active' or q.get('scope')!='owner-private' or
        q.get('source') not in ('main:sticker','main:proactive') or
        any(q.get(k)!=row[k] for k in ('scope','source','event_id','actor','text'))):
        raise ValueError('main_commit_source_conflict')
    at=q.get('occurred_at')
    if isinstance(at,bool) or not isinstance(at,(int,float)) or not math.isfinite(at) or at!=row['occurred_at']:
        raise ValueError('main_commit_original_time_conflict')
    raw=q.get('emotion_assessment')
    saved=b.db.execute('SELECT payload FROM ct_appraisal WHERE event=?',(eid,)).fetchone()
    if raw is None and saved and b.db.execute('SELECT 1 FROM ct_emotion_full48 WHERE event=?',(eid,)).fetchone():
        result=dict(status='replayed',source_event=eid,effect=emotion_effect(b,eid))
    elif not isinstance(raw,dict) or raw.get('format') not in INPUT_FORMATS:
        result=dict(status='invalid',detail='main_commit_full48_required')
    else:
        result=assess(b,eid,raw,lambda *_:dict(status='conflict'))
    good=result.get('status') in ('updated','unchanged','replayed')
    if not good:
        note(b,eid,result)
    # Re-read the one event only. Never reconstruct a large context on commit.
    saved=b.db.execute('SELECT payload FROM ct_appraisal WHERE event=?',(eid,)).fetchone()
    effect=emotion_effect(b,eid) if saved else None
    current=reaction(json.loads(saved['payload']),eid) if saved else None
    if current and effect:
        current.update(emotions=effect['applied_labels'],emotion_gain=effect['gain'])
        if 'group_changes' in effect: current['group_changes']=effect['group_changes']
    updates=None
    if good and (q.get('humor_assessment') is not None or q.get('meme_updates')) and b.available('style'):
        from muse_ext.humor import apply_updates
        updates=apply_updates(b,q,eid)
    return dict(ok=True,event=dict(id=eid,status='replayed'),emotion=result,mood=mood(b,'owner-private'),
                companion=context(b,'owner-private',q.get('person_id')),reaction=current,
                emotion_effect=effect,humor_updates=updates)


def proactive(b,q):
    from muse_ext.companion import context,mood
    if not b.available('mood'):
        return dict(ok=False,disabled=True,error='proactive_context_disabled')
    ids=q.get('source_events',[])
    if not isinstance(ids,list) or len(ids)>3 or any(type(x) is not int or x<=0 for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('proactive_registered_source_ids_required')
    for eid in ids:
        row=b.db.execute("SELECT * FROM source_events WHERE id=? AND scope='owner-private' AND status='active'",(eid,)).fetchone()
        if not row or row['actor']=='assistant' or not b.db.execute('SELECT 1 FROM ct_life WHERE source_event=?',(eid,)).fetchone():
            raise ValueError('proactive_original_life_stimulus_required')
        if not b.db.execute('SELECT 1 FROM ct_appraisal WHERE event=?',(eid,)).fetchone():
            raise ValueError('proactive_original_assessment_required')
    return dict(ok=True,source_events=ids,mood=mood(b,'owner-private'),companion=context(b,'owner-private'),
                emotion=dict(status='replayed' if ids else 'not_applicable_self_output'),
                assessment_required=False,emotion_origin='original_events' if ids else 'no_new_stimulus')
