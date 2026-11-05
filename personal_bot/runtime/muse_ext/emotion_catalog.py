"""Authoritative companion emotion vocabulary; no inference from message words."""
import copy
import json
import math

CATALOG_VERSION='emotion48-2026-11-05'
ASSESSMENT_VERSION=2
GROUPS={
    '愉悦与成就':('欣喜','愉快','兴奋','满足','得意','自豪','感动','感激'),
    '亲近与联结':('喜爱','亲近','想念','依恋','关切','心疼','害羞','受宠若惊'),
    '平稳与探索':('平静','放松','安心','好奇','期待','专注','惊讶','释然'),
    '受挫与低落':('难过','失落','委屈','孤单','沮丧','失望','遗憾','无聊'),
    '警觉与不满':('害怕','不安','紧张','担忧','生气','烦躁','不满','无奈'),
    '反省与矛盾':('内疚','懊恼','后悔','尴尬','难为情','羞愧','困惑','纠结'),
}
LABELS=tuple(label for group in GROUPS.values() for label in group)
ALIASES={'愧疚':'内疚','歉疚':'内疚','伤心':'难过','羞涩':'害羞','窘迫':'尴尬'}
HALF={'委屈':10,'失落':10,'难过':8,'期待':8,'想念':8,'满足':6,'自豪':6,
      '得意':4,'害怕':1,'不安':2,'害羞':.5,'生气':2,'烦躁':1,'内疚':3,
      '懊恼':2,'后悔':4,'尴尬':1/3,'难为情':.5,'羞愧':2,'亲近':6,'喜爱':8,
      '依恋':8,'感激':6,'感动':4,'受宠若惊':1,'惊讶':.25,'释然':2,
      '孤单':6,'沮丧':4,'失望':6,'遗憾':4,'紧张':1,'担忧':4,'不满':3,
      '无奈':2,'困惑':1,'纠结':2}
DEFINITIONS={
    '欣喜':'得到好消息或积极结果时的明显喜悦。','愉快':'普通轻松的好心情。',
    '兴奋':'积极事件带来的高唤醒和活跃感。','满足':'需要或目标获得满足的充实感。',
    '得意':'对自己的表现有一点炫耀式的开心。','自豪':'对努力、成果或价值的肯定。',
    '感动':'被有意义的关怀或经历打动。','感激':'认可别人给予的帮助或善意。',
    '喜爱':'对某人或事物的积极情感。','亲近':'当下感到关系温暖、距离缩短。',
    '想念':'希望再次接触不在身边的人。','依恋':'期待持续联结的情感，不能当成权限。',
    '关切':'关注对方的处境和需要。','心疼':'因在意对方的痛苦而想照顾对方。',
    '害羞':'因积极关注或亲密互动感到羞涩；不是犯错后的默认反应。',
    '受宠若惊':'获得超出预期的积极关注。','平静':'低波动、安定的状态。',
    '放松':'紧绷减少、容易自在交流。','安心':'担心的事情有了可靠保障。',
    '好奇':'想了解未知信息。','期待':'盼望尚未发生的结果。',
    '专注':'注意力投入当前事情。','惊讶':'发生出乎预期的事情，未必开心或害怕。',
    '释然':'原来的负担或纠结缓解。','难过':'因损失、痛苦或不如意而悲伤。',
    '失落':'原有期待没有得到回应或实现。','委屈':'感到被误解或受到不公对待。',
    '孤单':'想交流却缺少联结的感受。','沮丧':'受挫后信心或行动意愿下降。',
    '失望':'实际结果低于明确期待。','遗憾':'在意错过或无法改变的不圆满。',
    '无聊':'缺少投入和新鲜感。','害怕':'感到具体威胁。',
    '不安':'尚不明确或不确定的安全感下降。','紧张':'面对即将发生的事而紧绷。',
    '担忧':'关注可能出现的不良结果。','生气':'对伤害、阻碍或不公的强烈不满。',
    '烦躁':'持续不舒服或受干扰。','不满':'认为当前做法或结果不合适。',
    '无奈':'在意问题却暂时缺少可行办法。','内疚':'认为自己的具体行为造成失误或影响，想补救。',
    '懊恼':'对自己本可以避免的失误感到不快。','后悔':'希望过去的选择有所不同。',
    '尴尬':'当前社交场面不自在，不一定有过错。','难为情':'因被注意或不便启齿而局促。',
    '羞愧':'涉及自我形象或社会评价的负面自我感受，勿把小失误泛化成人格否定。',
    '困惑':'信息或解释无法吻合。','纠结':'多个在意的选择或感受相互牵制。',
}


def canonical(label):
    return ALIASES.get(label,label) if isinstance(label,str) else label


def normalize(raw):
    if not isinstance(raw,dict): raise ValueError('assessment_object_required')
    if 'additional_labels' in raw:
        raise ValueError('additional_labels:unknown_field_use_full48_emotion_deltas_or_sparse_emotions')
    clean=copy.deepcopy(raw)
    if clean.get('format') is not None or 'emotion_deltas' in clean:
        from muse_ext.emotion_full48 import normalize as normalize_full
        clean=normalize_full(clean)
    clean['label']=canonical(clean.get('label'))
    if isinstance(clean.get('emotions'),list):
        for item in clean['emotions']:
            if isinstance(item,dict): item['label']=canonical(item.get('label'))
    if clean.get('catalog_version',CATALOG_VERSION)!=CATALOG_VERSION:
        raise ValueError('emotion_catalog_mismatch')
    clean.setdefault('catalog_version',CATALOG_VERSION)
    appraisal=clean.get('appraisal')
    if appraisal is not None:
        if not isinstance(appraisal,dict) or set(appraisal)-{'kind','target','agency','certainty','feeling','action'}:
            raise ValueError('appraisal:expected_kind_target_agency_certainty_feeling_action_not_event_object')
        choices={'kind':('feedback','praise','care','loss','threat','achievement','expectation','life','reading','other'),
                 'target':('self','user','relationship','task','other'),
                 'agency':('self','other','shared','uncertain','none'),
                 'action':('repair','connect','support','explore','celebrate','rest','neutral')}
        for key,allowed in choices.items():
            if key in appraisal and appraisal[key] not in allowed: raise ValueError('invalid_appraisal_'+key)
        if 'certainty' in appraisal:
            v=appraisal['certainty']
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1:
                raise ValueError('invalid_appraisal_certainty')
        if 'feeling' in appraisal and (not isinstance(appraisal['feeling'],str) or len(appraisal['feeling'])>120):
            raise ValueError('invalid_appraisal_feeling')
    return clean


def schema():
    from muse_ext.emotion_full48 import schema as full_schema
    return {'assessment_version':ASSESSMENT_VERSION,'catalog_version':CATALOG_VERSION,
            'preferred_format':'full48-v1','full48':full_schema(),
            'labels':list(LABELS),'groups':{k:list(v) for k,v in GROUPS.items()},
            'aliases':dict(ALIASES),'definitions':dict(DEFINITIONS),
            'half_life_hours':{k:HALF.get(k,2) for k in LABELS},
            'limits':{'pad_delta':.35,'intensity_delta':.45,'label_max':.6,'mixed_max':3,'half_life_hours':[.15,24]},
            'judgment':'same reply model; distinguish event/target/agency/expectation; no keyword mood updates; no full reasoning',
            'expression':'current-event reaction guides this turn; background mood persists; an error does not imply shame or sadness'}


def reaction(raw,event_id):
    if not isinstance(raw,dict): return None
    changes=[]
    if raw.get('changed'):
        changes=[{'label':raw['label'],'delta':raw['intensity_delta']}]+[
            {'label':x['label'],'delta':x['delta']} for x in raw.get('emotions',[])]
    return {'source_event':event_id,'catalog_version':CATALOG_VERSION,'changed':raw['changed'],
            'emotions':changes,'appraisal':raw.get('appraisal',{}),
            'meaning':'current_event_model_inference_not_background_replacement'}


if __name__=='__main__': print(json.dumps(schema(),ensure_ascii=False,indent=2))
