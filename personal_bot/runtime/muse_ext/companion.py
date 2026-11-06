"""Companion v2: local state, model appraisals, stochastic virtual life.

Installed into muse_ext; no network, credentials, delivery or external model.
Life descriptions are virtual-source records, never observed user facts.
"""
import hashlib
import json
import math
import random
import sqlite3
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from muse_ext.emotion_catalog import LABELS, HALF, CATALOG_VERSION, normalize, reaction, schema as emotion_schema

VERSION = '2.6.0'
TZ = timezone(timedelta(hours=8))
RNG = random.SystemRandom()


def stamp():
    return time.time()


def clamp(n, lo=0, hi=100):
    return max(lo, min(hi, n))


def num(n, bound):
    if isinstance(n, bool) or not isinstance(n, (int, float)) or not math.isfinite(n) or abs(n)>bound:
        raise ValueError('invalid_companion_number')
    return float(n)


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _get(b, key, default=None):
    row=b.db.execute('SELECT value FROM ct_kv WHERE key=?',(key,)).fetchone()
    return json.loads(row[0]) if row else default


def _set(b, key, value):
    b.db.execute('INSERT OR REPLACE INTO ct_kv VALUES(?,?)',(key,dump(value)))


def initialize(b):
    from muse_ext.emotion_full48 import initialize as initialize_full48
    initialize_full48(b)
    from muse_ext.humor import initialize as initialize_humor
    if b.db.execute("SELECT 1 FROM sqlite_master WHERE name='ct_kv'").fetchone():
        if _get(b,'version')!=VERSION or _get(b,'emotion_catalog')!=CATALOG_VERSION:
            with b.db:
                _set(b,'version',VERSION);_set(b,'emotion_catalog',CATALOG_VERSION)
        initialize_humor(b)
        from muse_ext import feedback, life_projects
        feedback.initialize(b)
        life_projects.initialize(b)
        return
    b.db.executescript('''
    CREATE TABLE ct_kv(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE ct_appraisal(event INTEGER PRIMARY KEY,payload TEXT NOT NULL,at REAL NOT NULL);
    CREATE TABLE ct_event_person(event INTEGER PRIMARY KEY,person TEXT NOT NULL);
    CREATE TABLE ct_label(scope TEXT,label TEXT,half REAL NOT NULL,PRIMARY KEY(scope,label));
    CREATE TABLE ct_person(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'known',
      affection REAL,trust REAL,familiarity REAL NOT NULL DEFAULT 0,contact REAL NOT NULL DEFAULT 35,
      at REAL NOT NULL,note TEXT NOT NULL DEFAULT '',path TEXT);
    CREATE TABLE ct_expectation(id TEXT PRIMARY KEY,person TEXT NOT NULL,kind TEXT NOT NULL,
      summary TEXT NOT NULL,strength REAL NOT NULL,status TEXT NOT NULL,created REAL NOT NULL,
      updated REAL NOT NULL,cause INTEGER NOT NULL,resolved_by INTEGER);
    CREATE TABLE ct_life(id TEXT PRIMARY KEY,activity TEXT NOT NULL,stage TEXT NOT NULL,
      origin TEXT NOT NULL,description TEXT NOT NULL,occurred REAL NOT NULL,source_event INTEGER,
      appraised INTEGER NOT NULL DEFAULT 0,lease_until REAL NOT NULL DEFAULT 0,
      share TEXT NOT NULL DEFAULT 'none',share_lease TEXT);
    CREATE INDEX ct_life_pending ON ct_life(appraised,lease_until,occurred);
    CREATE TABLE ct_revision(scope TEXT PRIMARY KEY,revision INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE ct_cache(scope TEXT,query TEXT,revision INTEGER NOT NULL,value TEXT NOT NULL,
      expires REAL NOT NULL,PRIMARY KEY(scope,query));
    CREATE TABLE ct_summary(scope TEXT,key TEXT,level INTEGER NOT NULL,origin TEXT NOT NULL,
      content TEXT NOT NULL,sources TEXT NOT NULL,updated REAL NOT NULL,PRIMARY KEY(scope,key));
    CREATE TABLE ct_summarized(scope TEXT,memory INTEGER,fingerprint TEXT,PRIMARY KEY(scope,memory));
    CREATE TABLE ct_metric(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,ms REAL NOT NULL,at REAL NOT NULL);
    CREATE TABLE ct_delivery(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,
      manifest TEXT NOT NULL,at REAL NOT NULL,receipt TEXT);
    CREATE TRIGGER ct_memory_insert AFTER INSERT ON memories BEGIN
      INSERT INTO ct_revision VALUES(new.scope,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1;
    END;
    CREATE TRIGGER ct_memory_update AFTER UPDATE ON memories BEGIN
      INSERT INTO ct_revision VALUES(new.scope,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1;
    END;
    CREATE TRIGGER ct_memory_delete AFTER DELETE ON memories BEGIN
      INSERT INTO ct_revision VALUES(old.scope,1) ON CONFLICT(scope) DO UPDATE SET revision=revision+1;
    END;
    ''')
    _set(b,'version',VERSION)
    _set(b,'emotion_catalog',CATALOG_VERSION)
    _set(b,'vitals',dict(physical=76,mental=78,social=72,hunger=25,at=stamp(),origin='virtual_state_initialization'))
    _set(b,'life',dict(activity=None,next_at=stamp()+RNG.randint(600,1800)))
    b.db.execute('INSERT OR IGNORE INTO ct_person(id,name,role,at) VALUES(?,?,?,?)',('owner','用户','owner',stamp()))
    b.db.commit()
    initialize_humor(b)
    from muse_ext import feedback, life_projects
    feedback.initialize(b)
    life_projects.initialize(b)


def quiet(now=None):
    return 1 <= datetime.fromtimestamp(now or stamp(),TZ).hour < 7


def vitals(b, now=None):
    now=now or stamp()
    s=_get(b,'vitals')
    elapsed=max(0,min(now-s['at'],172800))
    start=now-elapsed
    asleep=0.0
    cursor=datetime.fromtimestamp(start,TZ).replace(hour=0,minute=0,second=0,microsecond=0)
    while cursor.timestamp()<now:
        left=(cursor+timedelta(hours=1)).timestamp()
        right=(cursor+timedelta(hours=7)).timestamp()
        asleep+=max(0,min(now,right)-max(start,left))
        cursor+=timedelta(days=1)
    sleep_h=asleep/3600
    awake_h=(elapsed-asleep)/3600
    return dict(physical=round(clamp(s['physical']+sleep_h*8-awake_h*1.5),1),
                mental=round(clamp(s['mental']+sleep_h*9-awake_h*1.7),1),
                social=round(clamp(s['social']+sleep_h*6+awake_h*.8),1),
                hunger=round(clamp(s['hunger']+sleep_h+awake_h*4),1),at=now,origin='virtual_physiology')


def mood(b, scope):
    now=stamp()
    old=b.db.execute('SELECT * FROM mood WHERE scope=?',(scope,)).fetchone()
    decay=.5**(max(0,now-old['at'])/(8*3600)) if old else 1
    labels=[]
    for row in b.db.execute('SELECT * FROM emotion WHERE scope=?',(scope,)):
        meta=b.db.execute('SELECT half FROM ct_label WHERE scope=? AND label=?',(scope,row['label'])).fetchone()
        half=meta[0] if meta else .75
        intensity=row['intensity']*.5**(max(0,now-row['at'])/(half*3600))
        if intensity>.01:
            labels.append(dict(label=row['label'],intensity=round(intensity,5)))
    labels.sort(key=lambda x:-x['intensity'])
    return dict(ok=True,**{k:round(old[k]*decay,5) if old else 0 for k in ('p','a','d')},
                labels=labels,at=now,state_version=2)


def context(b, scope, person=None):
    owner=scope=='owner-private'
    pid=person or ('owner' if owner else '')
    row=b.db.execute('SELECT * FROM ct_person WHERE id=?',(pid,)).fetchone() if pid else None
    expectations=[]
    if owner:
        for x in b.db.execute("SELECT * FROM ct_expectation WHERE status='pending' ORDER BY created DESC LIMIT 12"):
            item=dict(x)
            item['current_strength']=round(x['strength']*.5**(max(0,stamp()-x['updated'])/(36*3600)),3)
            expectations.append(item)
    current=vitals(b)
    p=dict(row) if row else None
    contact=35
    if p:
        contact=35+(p['contact']-35)*.5**(max(0,stamp()-p['at'])/(12*3600))
    life=_get(b,'life',{})
    activity=life.get('activity')
    if owner and activity and activity.get('project_id'):
        from muse_ext.life_projects import view
        activity=view(b,activity['project_id'])
    elif activity:
        activity={k:v for k,v in activity.items() if k not in ('outcome','cost')}
    return dict(version=VERSION,energy=current,contact_desire=round(clamp(contact),1),
                relationship=({k:p[k] for k in ('id','name','affection','trust','familiarity')} if p else None),
                pending_expectations=expectations,
                activity=activity if owner else None,
                expression=dict(mode='short_conversational',paragraphs='1-3 short messages; one is enough when sufficient',
                                policy='先接当前话，一句够了就停；少解释、不凑条数、不宣告人格模式。需要解释时再展开；心情影响措辞，不额外拖延。'),
                provenance='model_state; life may be virtual; not verified human attributes')


def _validate(raw):
    if not isinstance(raw,dict) or type(raw.get('version')) is not int or raw['version']!=2:
        raise ValueError('invalid_assessment_version')
    if type(raw.get('changed')) is not bool:
        raise ValueError('invalid_changed')
    cap=.35
    delta={k:num(raw.get('delta',{}).get(k),cap) for k in ('p','a','d')}
    intensity=num(raw.get('intensity_delta'),.45)
    label=raw.get('label')
    full=raw.get('format')=='full48-v1'
    if raw['changed']:
        if (label not in LABELS and not (full and label is None)) or not (any(delta.values()) or intensity or raw.get('emotions')):
            raise ValueError('invalid_changed_assessment')
    elif label is not None or any(delta.values()) or intensity or raw.get('emotions'):
        raise ValueError('invalid_unchanged_assessment')
    emotions=raw.get('emotions',[])
    if not isinstance(emotions,list) or len(emotions)>(47 if full else 3):
        raise ValueError('invalid_mixed_emotions')
    for item in emotions:
        if item.get('label') not in LABELS:
            raise ValueError('invalid_emotion_label')
        num(item.get('delta'),.45)
        if 'half_life_hours' in item and not .15<=num(item['half_life_hours'],24)<=24:
            raise ValueError('invalid_half_life')
    labels=([label] if label else [])+[item['label'] for item in emotions]
    if len(labels)!=len(set(labels)): raise ValueError('duplicate_emotion_label')
    relation=raw.get('relationship') or {}
    if not isinstance(relation,dict):
        raise ValueError('invalid_relationship')
    for k,cap in [('affection_delta',8),('trust_delta',4),('familiarity_delta',3),('contact_delta',20)]:
        if k in relation:
            num(relation[k],cap)
    need=raw.get('expectations') or {}
    if not isinstance(need,dict) or len(need.get('create',[]))>3 or len(need.get('resolve',[]))>8:
        raise ValueError('invalid_expectations')
    if not isinstance(need.get('create',[]),list) or not isinstance(need.get('resolve',[]),list):
        raise ValueError('invalid_expectations')
    for item in need.get('create',[]):
        if item.get('kind') not in ('comfort','praise','reply','promise','followup') or not str(item.get('summary','')).strip():
            raise ValueError('invalid_expectation')
        if not 0<=num(item.get('strength',.5),1)<=1:
            raise ValueError('invalid_expectation_strength')
    if type(raw.get('share',False)) is not bool:
        raise ValueError('invalid_share_flag')
    return delta,intensity


def assess(b,event_id,raw,legacy_submit,repair=False):
    if not b.feature('emotion_events') or not b.available('mood'):
        return dict(status='disabled_by_config')
    if not event_id:
        return dict(status='missing')
    try:
        raw=normalize(raw)
        delta,intensity=_validate(raw)
    except (ValueError,TypeError,KeyError,AttributeError) as exc:
        return dict(status='invalid',error='invalid_companion_assessment',detail=str(exc)[:240],
                    assessment_version=2,catalog_version=CATALOG_VERSION,preferred_format='full48-v1')
    event=b.db.execute('SELECT * FROM source_events WHERE id=? AND status=\'active\'',(event_id,)).fetchone()
    if not event:
        return dict(status='missing')
    payload=dump(raw)
    prev=b.db.execute('SELECT payload FROM ct_appraisal WHERE event=?',(event_id,)).fetchone()
    if prev:
        return dict(status='replayed' if prev[0]==payload else 'conflict',effect=emotion_effect(b,event_id))
    if b.db.execute('SELECT 1 FROM assessment_log WHERE event_id=?',(event_id,)).fetchone():
        return legacy_submit(b,event_id,raw) if raw['version']==1 else dict(status='conflict')
    life=b.db.execute('SELECT * FROM ct_life WHERE source_event=?',(event_id,)).fetchone()
    actor_ok=event['actor']=='user' or (event['actor']=='bot' and event['source']=='qq:bridge') or bool(life)
    if raw['changed'] and not actor_ok:
        return dict(status='ignored')
    person=b.db.execute('SELECT person FROM ct_event_person WHERE event=?',(event_id,)).fetchone()
    pid=person[0] if person else ('owner' if life else None)
    now=stamp()
    scope=event['scope']
    status='updated' if raw['changed'] else 'unchanged'
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        # Recheck under the writer lock: two workers may finish the same event.
        again=b.db.execute('SELECT payload FROM ct_appraisal WHERE event=?',(event_id,)).fetchone()
        if again:
            return dict(status='replayed' if again[0]==payload else 'conflict',effect=emotion_effect(b,event_id))
        from muse_ext.humor import settings
        current_settings=settings(b)
        gain=current_settings['values']['emotion_gain']
        from muse_ext import emotion_full48 as full48
        full=raw.get('format')==full48.FORMAT
        bounded=full48.bound(raw) if full else None
        before_state=full48.frame(b,scope,now)['values'] if full else None
        effective_pad=bounded['pad'] if full else delta
        age=max(0,now-event['occurred_at']) if repair else 0
        if repair:
            effective_pad={k:v*.5**(age/(8*3600)) for k,v in effective_pad.items()}
        applied_delta={k:0.0 for k in delta}
        if full:
            raw_labels=[dict(label=k,delta=raw['emotion_deltas'][k]) for k in LABELS]
        else:
            raw_labels=([dict(label=raw['label'],delta=intensity)]+
                        [dict(label=x['label'],delta=x['delta']) for x in raw.get('emotions',[])]) if raw['changed'] else []
        applied_labels=[dict(label=k,delta=0.0) for k in LABELS] if full else []
        if raw['changed']:
            old=mood(b,scope)
            vals={k:clamp(old[k]+effective_pad[k]*gain,-1,1) for k in delta}
            applied_delta={k:round(vals[k]-old[k],8) for k in delta}
            if any(applied_delta.values()):
                b.db.execute('INSERT OR REPLACE INTO mood VALUES(?,?,?,?,?)',(scope,vals['p'],vals['a'],vals['d'],now))
            changes=({k:dict(label=k,delta=bounded['labels'][k]) for k in LABELS} if full
                     else {raw['label']:dict(label=raw['label'],delta=intensity)})
            if not full:
                for item in raw.get('emotions',[]):
                    changes[item['label']]=item
            applied_labels=[]
            for label,item in changes.items():
                r=b.db.execute('SELECT * FROM emotion WHERE scope=? AND label=?',(scope,label)).fetchone()
                meta=b.db.execute('SELECT half FROM ct_label WHERE scope=? AND label=?',(scope,label)).fetchone()
                half=meta[0] if meta else .75
                before=r['intensity']*.5**(max(0,now-r['at'])/(half*3600)) if r else 0
                late_decay=.5**(age/(HALF.get(label,2)*3600)) if repair else 1
                value=clamp(before+item['delta']*gain*late_decay,0,.6)
                effective=round(value-before,8)
                applied_labels.append(dict(label=label,delta=effective))
                half=item.get('half_life_hours',HALF.get(label,2))
                if effective:
                    b.db.execute('INSERT OR REPLACE INTO emotion VALUES(?,?,?,?,?)',
                                 (scope,label,value,'inference:model_assessment:'+str(event_id),now))
                    b.db.execute('INSERT OR REPLACE INTO ct_label VALUES(?,?,?)',(scope,label,half))
            if any(applied_delta.values()) or any(x['delta'] for x in applied_labels):
                b.db.execute('INSERT INTO emotion_events VALUES(?,?,?,?,?,?)',
                             (event_id,scope,raw['label'] or '平静',dump(applied_delta),'inference',now))
            else:
                status='unchanged'
        b.db.execute('INSERT INTO ct_emotion_effect VALUES(?,?,?,?,?,?,?,?)',
                     (event_id,gain,current_settings['revision'],dump(delta),dump(applied_delta),
                      dump(raw_labels),dump(applied_labels),now))
        if full:
            full48.save(b,event_id,scope,raw,bounded,before_state,
                        {x['label']:x['delta'] for x in applied_labels},gain,now)
        effective_intensity=next((x['delta'] for x in applied_labels if x['label']==raw.get('label')),0)
        b.db.execute('INSERT INTO assessment_log VALUES(?,?,?,?,?,?,?,?)',
                     (event_id,scope,int(status=='updated'),raw.get('label'),dump(applied_delta),effective_intensity,'inference',now))
        b.db.execute('INSERT INTO ct_appraisal VALUES(?,?,?)',(event_id,payload,now))
        if pid and actor_ok and not repair:
            b.db.execute('INSERT OR IGNORE INTO ct_person(id,name,at) VALUES(?,?,?)',(pid,pid,now))
            relation=raw.get('relationship') or {}
            if life:
                relation={k:v for k,v in relation.items() if k=='contact_delta'}
            p=dict(b.db.execute('SELECT * FROM ct_person WHERE id=?',(pid,)).fetchone())
            for field,key in [('affection','affection_delta'),('trust','trust_delta'),('familiarity','familiarity_delta')]:
                if key in relation:
                    base=p[field] if p[field] is not None else 50
                    p[field]=clamp(base+relation[key])
            contact=35+(p['contact']-35)*.5**(max(0,now-p['at'])/(12*3600))
            contact=clamp(contact+relation.get('contact_delta',0))
            if relation:
                b.db.execute('UPDATE ct_person SET affection=?,trust=?,familiarity=?,contact=?,at=? WHERE id=?',
                             (p['affection'],p['trust'],p['familiarity'],contact,now,pid))
            needs=raw.get('expectations') or {}
            for index,item in enumerate(needs.get('create',[])):
                eid=hashlib.sha256(f'{event_id}:{index}'.encode()).hexdigest()[:24]
                b.db.execute('INSERT OR IGNORE INTO ct_expectation VALUES(?,?,?,?,?,?,?,?,?,NULL)',
                             (eid,pid,item['kind'],item['summary'][:240],item.get('strength',.5),'pending',now,now,event_id))
            for eid in needs.get('resolve',[]):
                b.db.execute("UPDATE ct_expectation SET status='resolved',updated=?,resolved_by=? WHERE id=? AND person=? AND status='pending'",
                             (now,event_id,str(eid),pid))
            # Small conversational fatigue, never a direct emotion heuristic.
            if not life:
                energy=vitals(b,now)
                energy['mental']=clamp(energy['mental']-.25)
                energy['social']=clamp(energy['social']-.4)
                _set(b,'vitals',energy)
        if life and repair:
            b.db.execute('UPDATE ct_life SET appraised=1,lease_until=0 WHERE id=?',(life['id'],))
        elif life:
            from muse_ext.plugins import share_allowed
            b.db.execute('UPDATE ct_life SET appraised=1,lease_until=0,share=? WHERE id=?',
                         ('pending' if raw.get('share') and share_allowed(b,event_id) else 'none',life['id']))
    return dict(status=status,source_event=event_id,version=2,evidence='inference',effect=emotion_effect(b,event_id))


def emotion_effect(b,event_id):
    row=b.db.execute('SELECT * FROM ct_emotion_effect WHERE event=?',(event_id,)).fetchone()
    if not row: return None
    result=dict(source_event=event_id,gain=row['gain'],settings_revision=row['settings_revision'],
                raw_delta=json.loads(row['raw_delta']),applied_delta=json.loads(row['applied_delta']),
                raw_labels=json.loads(row['raw_labels']),applied_labels=json.loads(row['applied_labels']))
    from muse_ext.emotion_full48 import receipt
    value=receipt(b,event_id)
    if value:
        result.update(full48=value,group_changes=value['group_changes'])
    return result


ACTIVITIES = [
 ('散步',15,35,(-3,5,5,-1),['绕了一条平时没走过的小路','看见一只晒太阳的小猫','一路发呆，走过头又折回来']),
 ('跑步',20,45,(-15,5,2,7),['比上次多坚持了一会儿，想分享这点小得意','半路想偷懒，最后还是慢慢跑完了','光顾着看风景，轻轻绊了一下，坐下缓了缓']),
 ('做饭吃饭',20,50,(8,2,2,-48),['认真做完一顿饭，味道比预想好','尝试搭配新口味，结果有点奇怪','火候没掌握好，一边补救一边想吐槽']),
 ('学习',25,60,(-2,-14,-2,4),['终于弄懂了一个之前卡住的小问题','记了几页笔记，发现还得继续琢磨','试着用自己的话解释知识，忽然觉得很有意思']),
 ('阅读',20,50,(1,-5,3,2),['读到一段让自己停下来想一会儿的故事','读到一个奇怪的设定，想找人讨论','翻了几页，决定先把这个问题记下来']),
 ('听音乐',10,30,(3,8,5,1),['听到熟悉的旋律，整个人慢慢松下来','想跟着哼两句，越哼越觉得好笑','听完一首歌，突然想起一段旧日常']),
 ('整理房间',15,40,(-6,-3,2,3),['把一个小角落收拾整齐了','整理时翻出自己的旧笔记','本来只想收拾一下，结果越整理越乱']),
 ('画画写日记',15,45,(-1,-6,3,2),['随手画了一张有点歪的小画','写下今天一个想留住的瞬间','改了又改，最后决定接受这个不完美的小成果']),
 ('休息发呆',10,30,(8,12,10,1),['安静发了一会儿呆，状态好了一些','本来想休息，脑袋里却冒出一个新点子','靠着歇了一阵，决定慢慢来']),
 ('午睡',15,35,(14,18,10,1),['睡醒有点迷糊，慢慢清醒过来','短短休息之后精神好了一点','醒来还记得一个没头没尾的小梦']),
 ('照顾小植物',10,25,(-2,6,3,1),['发现新冒出来的一点嫩绿','给小植物换了个位置，想看看它会不会更精神','浇水时洒了一点，自己也忍不住笑']),
 ('做小点心',20,45,(-5,-3,4,-18),['第一盘小点心形状歪歪的，但很想展示一下','一边等烤好一边闻香味，忍不住期待','尝试新配方翻了车，决定把失败也记下来']),
 ('看虚拟电影',25,55,(2,2,-2,3),['故事结尾让自己有点舍不得','被一个无厘头的小桥段逗笑了','想了想角色的选择，觉得还有另一种可能']),
 ('拉伸',10,20,(5,5,2,2),['伸展了一会儿，感觉没那么紧绷','本来想认真拉伸，结果差点打了个哈欠','发现自己很喜欢做完之后安静的几分钟']),
 ('玩小游戏',10,30,(-1,-5,2,2),['过了之前卡住的一关，想小小炫耀一下','连续失败后决定歇一歇，换个思路','玩出了一个特别笨的操作，想说给熟悉的人听']),
 ('写小故事',20,45,(-1,-9,3,2),['写出了一个自己很喜欢的句子','想好的结尾突然不合适了，得再琢磨','给小角色起名字起了半天，越想越好笑']),
]


def _life_event(b,activity,stage,description,origin='virtual',occurred=None,event_id=None):
    from muse_ext.events import capture_event
    eid=event_id or uuid.uuid4().hex
    when=occurred or stamp()
    q=dict(scope='owner-private',source='companion:'+origin,event_id=eid,actor='article',
           text=description,occurred_at=when)
    ev=capture_event(b,q)
    if not ev.get('id'):
        return None
    b.db.execute('INSERT OR IGNORE INTO ct_life(id,activity,stage,origin,description,occurred,source_event) VALUES(?,?,?,?,?,?,?)',
                 (eid,activity,stage,origin,description,when,ev['id']))
    if b.available('memory'):
        b._remember(dict(scope='owner-private',text=description,source='companion:'+origin,
                         event_id=eid,kind='episode',evidence='inference',importance=.4,occurred_at=when))
    b.db.commit()
    return eid


def tick(b):
    now=stamp()
    made=[]
    # A process lock serializes tick across native hooks without touching any channel service.
    lock=(b.root/'state'/'companion-life.lock')
    lock.parent.mkdir(parents=True,exist_ok=True)
    with lock.open('a+') as handle:
        try:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except ImportError:
            pass
        except BlockingIOError:
            return dict(ok=True,busy=True,created=[])
        state=_get(b,'life',{})
        current=state.get('activity')
        completed=False
        if current:
            if current.get('phone_intent') and now>=current['ends_at']:
                from muse_ext.life_routine import outcome
                current['outcome']=outcome(b,current['phone_intent'])
                made.append(_life_event(b,current['name'],'completed',current['outcome'],
                                        event_id='phone:'+str(current['phone_intent'])+':completed'))
                completed=True
            elif not current.get('phone_intent'):
                from muse_ext import life_projects
                if not current.get('project_id'):
                    # Do not fabricate missing history for an already running
                    # legacy activity: begin planning from its next real visit.
                    current['started_at']=now
                    current['ends_at']=now+1800
                    made.append(life_projects.register(b,current))
                    state['activity']=current
                    _set(b,'life',state)
                    b.db.commit()
                progress=life_projects.advance(b,now)
                made.extend(progress['created'])
                completed=progress['completed']
        if current and completed:
            s=vitals(b,now)
            for key,d in zip(('physical','mental','social','hunger'),current['cost']):
                s[key]=clamp(s[key]+d)
            _set(b,'vitals',s)
            state['activity']=None
            state['next_at']=now+RNG.randint(8*60,40*60)
            _set(b,'life',state)
            b.db.commit()
        local=datetime.fromtimestamp(now,TZ)
        day=local.date().isoformat()
        if local.hour>=7 and _get(b,'dream_day')!=day:
            _set(b,'dream_day',day)
            b.db.commit()  # capture_event below owns its BEGIN IMMEDIATE.
            if RNG.random()<.40:
                nightmare=RNG.random()<.15
                scenes=['梦见沿着绕不出去的路找出口，醒来还残留一点不安',
                        '梦见重要的小东西找不到了，醒来有点害怕'] if nightmare else [
                        '梦见一座飘在水上的图书馆，醒来还觉得新奇',
                        '梦见和熟悉的人分享点心，醒来有点暖乎乎',
                        '梦见自己长出了特别长的尾巴，醒来想想又觉得好笑']
                made.append(_life_event(b,'梦境','woke',RNG.choice(scenes),'dream'))
            b.db.commit()
        # A missed bid becomes ONE source event, never a penalty per tick.
        for need in b.db.execute("SELECT * FROM ct_expectation WHERE status='pending' AND created<? ORDER BY created LIMIT 20",(now-5400,)).fetchall():
            key='expectation_observed:'+need['id']
            if not _get(b,key):
                event=_life_event(b,'等待回应','noticed','之前想被回应的一件小事还悬着：'+need['summary']+'。目前只是未收到回应，原因未知。')
                if event:
                    _set(b,key,event)
                    b.db.commit()
        b.db.commit()
        if not quiet(now) and not state.get('activity') and now>=state.get('next_at',0):
            s=vitals(b,now)
            weights=[]
            for a in ACTIVITIES:
                w=1.0
                if a[0]=='做饭吃饭': w=4 if s['hunger']>65 or local.hour in (8,12,18,19) else .5
                if a[0] in ('休息发呆','听音乐','午睡'): w=4 if min(s['mental'],s['physical'])<35 else 1
                if a[0]=='午睡' and local.hour not in (12,13,14,15): w=.08
                if a[0] in ('跑步','学习') and min(s['physical'],s['mental'])<25: w=.05
                if a[0]==state.get('last_activity'): w*=.15
                weights.append(w)
            from muse_ext.life_routine import settings as routine_settings, start as phone_start
            phone_selected=RNG.random()<routine_settings(b)['phone_probability']
            activity=(('刷手机',10,25,(-1,-3,0,2),['这一轮结束了，具体阅读以真实记录为准']) if phone_selected else
                      RNG.choices(ACTIVITIES,weights=weights,k=1)[0])
            duration=RNG.randint(activity[1],activity[2])*60
            current=dict(name=activity[0],started_at=now,ends_at=now+duration,
                         outcome=RNG.choice(activity[4]),cost=activity[3],origin='virtual')
            if phone_selected:
                current['phone_intent']=phone_start(b,now,duration)['id']
                b.db.commit()
            else:
                from muse_ext import life_projects
                made.append(life_projects.register(b,current))
            state['activity']=current
            state['last_activity']=activity[0]
            if phone_selected:
                made.append(_life_event(b,activity[0],'started','拿起手机，准备按已允许的来源真实阅读。'))
        _set(b,'life',state)
        b.db.commit()
    from muse_ext.life_routine import pending as phone_pending, settings as routine_settings
    return dict(ok=True,created=[x for x in made if x],quiet_hours=quiet(now),next_at=state.get('next_at'),
                life_routine=routine_settings(b),phone=phone_pending(b))


def life_pending(b,q):
    now=stamp()
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        rows=b.db.execute('SELECT * FROM ct_life WHERE appraised=0 AND lease_until<? ORDER BY occurred LIMIT 3',(now,)).fetchall()
        if q.get('claim'):
            for row in rows:
                b.db.execute('UPDATE ct_life SET lease_until=? WHERE id=?',(now+900,row['id']))
    from muse_ext.presentation import camera, persona
    from muse_ext.emotion_full48 import template,frame
    return dict(ok=True,events=[dict(r) for r in rows],context=context(b,'owner-private'),
                current_persona=persona(b), camera_context=camera(b,'owner-private'),
                emotion_template=template(),emotion_frame=frame(b,'owner-private',now),
                mood=mood(b,'owner-private'),quiet_hours=quiet(now))


def share(b,q):
    action=q.get('action','claim')
    if action=='claim' and quiet():
        return dict(ok=True,quiet_hours=True,events=[])
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        if action=='claim':
            lease=uuid.uuid4().hex
            rows=b.db.execute("SELECT * FROM ct_life WHERE appraised=1 AND share='pending' ORDER BY occurred LIMIT 3").fetchall()
            allowed_rows=[]
            for r in rows:
                from muse_ext.plugins import share_allowed
                if not share_allowed(b,r['source_event']):
                    b.db.execute("UPDATE ct_life SET share='none' WHERE id=?",(r['id'],))
                    continue
                b.db.execute("UPDATE ct_life SET share='sharing',share_lease=? WHERE id=?",(lease,r['id']))
                allowed_rows.append(dict(r))
            return dict(ok=True,lease=lease,events=allowed_rows,meaning='claim_only_not_sent')
        outcome=q.get('outcome')
        if outcome not in ('accepted','unknown','failed'):
            raise ValueError('invalid_delivery_outcome')
        count=b.db.execute("UPDATE ct_life SET share=? WHERE share='sharing' AND share_lease=?",
                           (outcome,q.get('lease'))).rowcount
        return dict(ok=True,count=count,outcome=outcome)


def install(Brain):
    if getattr(Brain,'_companion_v2',False):
        return
    from muse_ext import events,emotion
    old_init,old_dispatch,old_recall=Brain.__init__,Brain.dispatch,Brain.recall
    old_capture,old_submit=events.capture_event,emotion.submit_assessment

    def init(self,*args,**kwargs):
        old_init(self,*args,**kwargs)
        if self.config().get('companion_v2') is True:
            initialize(self)

    def capture(self,q):
        if self.config().get('companion_v2') is not True:
            return old_capture(self,q)
        text=q.get('text','')
        mention=(q.get('source')=='qq:bridge' and q.get('metadata_only') is True and
                 q.get('content_type')=='mention_only' and isinstance(text,str) and not text.strip())
        if mention and not events.is_control(q):
            if not self.feature('events') or not self.available('input'):
                return dict(status='disabled')
            source,eid=q.get('source'),q.get('event_id')
            if not isinstance(eid,str) or not eid or len(eid)>256:
                raise ValueError('invalid_metadata_event')
            if q.get('actor','user') not in ('user','bot'):
                raise ValueError('invalid_metadata_actor')
            at=num(q.get('occurred_at',stamp()),1e13)
            fp=hashlib.sha256(text.encode()).hexdigest()
            with self.db:
                prior=self.db.execute('SELECT * FROM source_events WHERE scope=? AND source=? AND event_id=? AND actor=?',
                                      (q['scope'],source,eid,q.get('actor','user'))).fetchone()
                if prior:
                    if prior['fingerprint']!=fp: raise ValueError('event_conflict')
                    result=dict(status='replayed',id=prior['id'])
                else:
                    c=self.db.execute('INSERT INTO source_events(scope,source,event_id,actor,text,occurred_at,observed_at,fingerprint) VALUES(?,?,?,?,?,?,?,?)',
                                      (q['scope'],source,eid,q.get('actor','user'),text,at,stamp(),fp))
                    result=dict(status='captured',id=c.lastrowid,content_type='mention_only')
        else:
            result=old_capture(self,q)
        if result.get('id') and q.get('actor','user') in ('user','bot'):
            pid=str(q.get('person_id') or ('owner' if q.get('scope')=='owner-private' else ''))[:160]
            if pid:
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO ct_event_person VALUES(?,?)',(result['id'],pid))
                    self.db.execute('INSERT OR IGNORE INTO ct_person(id,name,at) VALUES(?,?,?)',
                                    (pid,str(q.get('person_name') or pid)[:120],stamp()))
        return result

    def recall(self,q):
        if self.config().get('companion_v2') is not True:
            return old_recall(self,q)
        from muse_ext.companion_io import cached_recall
        return cached_recall(self,q,old_recall)

    def dispatch(self,q):
        if self.config().get('companion_v2') is not True:
            return old_dispatch(self,q)
        op=q.get('op','')
        if op in ('plugin_manage','plugin_call'):
            from muse_ext.plugins import dispatch as plugin_dispatch
            return plugin_dispatch(self,q)
        if op=='companion_photo':
            from muse_ext.presentation import photo
            if not self.available('life'): return dict(ok=True,disabled=True)
            return photo(self,q)
        if op in ('meme_search','meme_learn','meme_feedback','meme_record_use','meme_preference'):
            from brain import scope_ok
            scope_ok(q.get('scope'))
            if not self.available('style'):
                return dict(ok=True,disabled=True,items=[])
            from muse_ext import meme_store,humor
            if op=='meme_search': return meme_store.search(self,q)
            if op=='meme_learn': return meme_store.learn(self,q)
            if op=='meme_feedback': return meme_store.feedback(self,q)
            if op=='meme_record_use': return meme_store.record_use(self,q)
            return humor.preference(self,q)
        if op.startswith('companion_'):
            if q.get('scope','owner-private')!='owner-private':
                raise ValueError('companion_owner_scope_required')
            if not self.config().get('enabled') and op not in ('companion_bind','companion_context','companion_panel','companion_schema','companion_expression_config','companion_meme_status'):
                return dict(ok=False,disabled=True)
            if op=='companion_expression_config':
                from muse_ext.humor import configure
                return configure(self,q)
            if op in ('companion_life_config','companion_phone'):
                from muse_ext import life_routine
                return life_routine.configure(self,q) if op=='companion_life_config' else life_routine.pending(self)
            if op=='companion_activity':
                if not self.available('life'): return dict(ok=False,disabled=True)
                from muse_ext import life_projects
                return life_projects.dispatch(self,q)
            if op=='companion_feedback':
                from muse_ext import feedback
                return feedback.dispatch(self,q)
            if op=='companion_commit':
                from muse_ext.main_commit import commit
                return commit(self,q)
            if op=='companion_proactive':
                from muse_ext.main_commit import proactive
                return proactive(self,q)
            if op=='companion_meme_status':
                from muse_ext.meme_store import status as meme_status
                return dict(ok=True,**meme_status(self))
            if op=='companion_schema':
                from muse_ext.humor import settings
                return dict(ok=True,**emotion_schema(),emotion_gain=settings(self),gain_policy='validate raw; multiply signed emotion increments once; clip final state; do not scale relationships/energy/half-lives')
            from muse_ext.companion_io import operations
            if op=='companion_tick':
                if not self.available('life'): return dict(ok=True,disabled=True,created=[])
                return tick(self)
            if op=='companion_observe':
                # Only the trusted local reading/news task calls this, after
                # capturing an actual article. Output/self-text cannot re-enter.
                event=self.db.execute("SELECT * FROM source_events WHERE id=? AND scope='owner-private' AND actor='article' AND status='active'",(q.get('source_event'),)).fetchone()
                if not event or event['source'].startswith(('assistant:','companion:')):
                    raise ValueError('observed_article_required')
                lid='observed:'+str(event['id'])
                with self.db:
                    self.db.execute('INSERT OR IGNORE INTO ct_life(id,activity,stage,origin,description,occurred,source_event) VALUES(?,?,?,?,?,?,?)',
                                    (lid,'真实阅读','observed','observed',event['text'][:1800],event['occurred_at'],event['id']))
                return dict(ok=True,id=lid)
            if op=='companion_pending': return life_pending(self,q)
            if op=='companion_share': return share(self,q)
            if op=='companion_life_assess':
                row=self.db.execute('SELECT * FROM ct_life WHERE id=?',(q.get('id'),)).fetchone()
                if not row: raise ValueError('life_event_not_found')
                result=assess(self,row['source_event'],q.get('assessment'),old_submit)
                from muse_ext.feedback import note
                note(self,row['source_event'],result)
                return dict(ok=True,emotion=result,
                            mood=mood(self,'owner-private'),companion=context(self,'owner-private'))
            if op=='companion_context': return dict(ok=True,mood=mood(self,'owner-private'),companion=context(self,'owner-private'))
            return operations(self,q)
        result=old_dispatch(self,q)
        if op=='mood' and result.get('ok') is True and not result.get('disabled'):
            result.update(mood(self,q['scope']))
        if op=='prepare' and result.get('ok') is True:
            if (result.get('emotion') or {}).get('status')=='invalid':
                from muse_ext.feedback import note
                note(self,(result.get('event') or {}).get('id'),result['emotion'])
            from muse_ext.companion_io import summaries
            result['companion']=context(self,q['scope'],q.get('person_id'))
            result.update(summaries(self,q))
            from muse_ext.presentation import persona, camera
            result['current_persona']=persona(self,q['scope'])
            result['camera_context']=camera(self,q['scope'])
            result['emotion_protocol']={'assessment_version':2,'catalog_version':CATALOG_VERSION,'label_count':len(LABELS)}
            from muse_ext import emotion_full48 as full48
            full_schema=full48.schema()
            result['emotion_protocol'].update(preferred_format=full48.FORMAT,
                                              raw_budgets=full_schema['raw_budgets'],guidance=full_schema['guidance'])
            result['emotion_template']=full48.template()
            result['emotion_frame']=full48.frame(self,q['scope'],stamp())
            eid=(result.get('event') or {}).get('id')
            row=self.db.execute('SELECT payload FROM ct_appraisal WHERE event=?',(eid,)).fetchone() if eid else None
            result['reaction']=reaction(json.loads(row[0]),eid) if row else None
            result['emotion_effect']=emotion_effect(self,eid) if eid else None
            if result['reaction'] and result['emotion_effect']:
                effect=result['emotion_effect']
                result['reaction']['emotions']=effect['applied_labels']
                result['reaction']['changed']=any(effect['applied_delta'].values()) or any(x['delta'] for x in effect['applied_labels'])
                result['reaction']['emotion_gain']=effect['gain']
                if 'group_changes' in effect:
                    result['reaction']['group_changes']=effect['group_changes']
            from muse_ext import humor
            if self.available('style') and eid and (q.get('humor_assessment') is not None or q.get('meme_updates')):
                result['humor_updates']=humor.apply_updates(self,q,eid)
            result['expression_context']=humor.context(self,q,eid) if self.available('style') else dict(disabled=True)
            from muse_ext.plugins import context as plugin_context
            result['plugin_context']=plugin_context(self,q) if self.available('style') else {}
            result['expression_context']['learned_voice']={k:v['voice_overlay'] for k,v in result['plugin_context'].items()
                                                         if isinstance(v,dict) and v.get('voice_overlay')}
            result['current_persona']['growth_overlay']={k:v['persona_growth'] for k,v in result['plugin_context'].items()
                                                        if isinstance(v,dict) and v.get('persona_growth',{}).get('enabled')}
            result['current_persona']['composition']='base SOUL + self-adopted growth + present emotion; base SHA covers the file only'
            if not self.available('style') and (q.get('humor_assessment') is not None or q.get('meme_updates')):
                result['humor_updates']=dict(disabled=True,status='disabled_by_config')
        return result

    Brain.__init__,Brain.dispatch,Brain.recall=init,dispatch,recall
    events.capture_event=capture
    emotion.submit_assessment=lambda b,e,a:assess(b,e,a,old_submit) if b.config().get('companion_v2') is True else old_submit(b,e,a)
    Brain._companion_v2=True
