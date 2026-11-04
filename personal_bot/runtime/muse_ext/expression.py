"""One draw per assessed event; broad asset selection; host sends text then image."""
import json
import math
import random
import time

DEFAULT={'enabled':False,'base_probability':.4,'maximum_probability':.9,
         'recent_seconds':3600,'candidate_limit':10,'shared_owner_mood':False}
RNG=random.SystemRandom()


def dispatch(b,q):
    policy=dict(DEFAULT)
    file=b.root/'expression-policy.json'
    if file.is_file(): policy.update(json.loads(file.read_text(encoding='utf-8')))
    for k in ('base_probability','maximum_probability'):
        if isinstance(policy[k],bool) or not isinstance(policy[k],(int,float)) or not math.isfinite(policy[k]) or not 0<=policy[k]<=1:
            raise ValueError('invalid_expression_probability')
    if policy['maximum_probability']<policy['base_probability']: raise ValueError('invalid_expression_range')
    if type(policy.get('recent_seconds')) is not int or not 0<=policy['recent_seconds']<=86400: raise ValueError('invalid_recent_window')
    if type(policy.get('candidate_limit')) is not int or not 1<=policy['candidate_limit']<=10: raise ValueError('invalid_candidate_limit')
    b.db.executescript('''CREATE TABLE IF NOT EXISTS expression_turn(
      event INTEGER PRIMARY KEY,scope TEXT NOT NULL,decision TEXT NOT NULL,status TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS expression_recent(asset TEXT PRIMARY KEY,at REAL NOT NULL);''')
    event=b.db.execute("SELECT * FROM source_events WHERE id=? AND scope=? AND status='active'",(q.get('source_event'),q['scope'])).fetchone()
    if not event: return {'ok':False,'reason':'captured_source_event_required'}
    action=q.get('action','plan')
    with b.db:
        b.db.execute('BEGIN IMMEDIATE')
        prev=b.db.execute('SELECT * FROM expression_turn WHERE event=?',(event['id'],)).fetchone()
        if action=='finish':
            if not prev: return {'ok':False,'reason':'decision_required'}
            if prev['status']!='prepared': return {'ok':True,'replayed':True,'status':prev['status']}
            if q.get('outcome') not in ('accepted','unknown','failed') or q.get('text_finished') is not True:
                return {'ok':False,'reason':'text_must_finish_before_image_handoff'}
            decision=json.loads(prev['decision'])
            if decision.get('asset') and q['outcome'] in ('accepted','unknown'):
                b.db.execute('INSERT OR REPLACE INTO expression_recent VALUES(?,?)',(decision['asset'],time.time()))
            b.db.execute('UPDATE expression_turn SET status=? WHERE event=?',(q['outcome'],event['id']))
            return {'ok':True,'status':q['outcome']}
        if action!='plan': raise ValueError('invalid_expression_action')
        if prev:
            decision=json.loads(prev['decision'])
            if decision['status']!='asset_required' or prev['status']!='prepared':
                return dict(ok=True,replayed=True,delivery_status=prev['status'],**decision)
        else:
            if not b.db.execute('SELECT 1 FROM assessment_log WHERE event_id=?',(event['id'],)).fetchone():
                return {'ok':False,'reason':'valid_model_assessment_required'}
            intent=q.get('intent','auto')
            if intent not in ('auto','direct','skip'): raise ValueError('invalid_expression_intent')
            from muse_ext.events import is_control
            if is_control(dict(text=event['text'])): intent='skip'
            mood=b.dispatch(dict(op='mood',scope=event['scope']))
            if policy.get('shared_owner_mood') and event['scope']!='owner-private':
                shared=b.dispatch(dict(op='mood',scope='owner-private'))
                labels=(mood.get('labels') or [])+(shared.get('labels') or [])
            else: labels=mood.get('labels') or []
            strength=min(1,max([abs(mood.get('p',0)),abs(mood.get('a',0))]+[x.get('intensity',0)/.6 for x in labels]))
            probability=policy['base_probability']+(policy['maximum_probability']-policy['base_probability'])*strength
            roll=RNG.random() if intent=='auto' and policy['enabled'] else None
            hit=policy['enabled'] and (intent=='direct' or intent=='auto' and roll<probability)
            decision={'intent':intent,'probability':probability if intent=='auto' else None,'roll':roll,
                      'hit':bool(hit),'asset':None,'status':'asset_required' if hit else 'skip',
                      'order':'all_text_then_image','reason':'media_not_configured' if not policy['enabled'] else 'policy'}
        if decision['hit']:
            assets=q.get('assets',[])
            if not isinstance(assets,list) or len(assets)>200: raise ValueError('invalid_asset_inventory')
            valid=[]
            for asset in assets:
                if not isinstance(asset,dict) or not isinstance(asset.get('id'),str) or not 1<=len(asset['id'])<=160:
                    raise ValueError('invalid_asset_id')
                score=asset.get('relevance',0)
                if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score): raise ValueError('invalid_asset_score')
                recent=b.db.execute('SELECT at FROM expression_recent WHERE asset=?',(asset['id'],)).fetchone()
                if not recent or time.time()-recent[0]>=policy['recent_seconds']: valid.append((score,asset['id']))
            if valid:
                valid.sort(reverse=True)
                decision['asset']=RNG.choice(valid[:max(1,min(10,int(policy['candidate_limit'])))])[1]
                decision['status']='image_planned'
            # An empty/recent-only pool does NOT turn a hit into a missed draw.
            # The host broadens its inventory and repeats plan with the SAME ID.
        b.db.execute('INSERT OR REPLACE INTO expression_turn VALUES(?,?,?,?)',
                     (event['id'],event['scope'],json.dumps(decision,ensure_ascii=False),'prepared'))
        return dict(ok=True,replayed=bool(prev),**decision)
