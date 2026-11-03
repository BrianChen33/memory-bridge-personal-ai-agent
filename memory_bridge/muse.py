"""Pure opt-in transformation of documented Muse memory rows, not a live hook.

No file, database, network, subprocess, persona or prompt access. The caller must
obtain verified principal identity independently; row data cannot grant consent.
"""
from dataclasses import dataclass
import hashlib
import math
from .core import Denied, Invalid, canonical, digest, identifier, validate

MUSE_FIELDS = {'scope','text','kind','source','event_id','evidence','status','importance','occurred_at','created_at','supersedes','fingerprint'}

@dataclass(frozen=True)
class ScopeGrant:
    """Trusted local binding. Never deserialize this from a Muse row or message."""
    principal: str
    scope: str
    owner: str
    audience: str

def row_digest(row):
    """Review helper for an explicitly selected row, not permission by itself."""
    if not isinstance(row,dict) or set(row)!=MUSE_FIELDS: raise Invalid('Muse row fields')
    try:
        raw=canonical(row).encode('utf-8')
    except (TypeError,ValueError,UnicodeError) as exc: raise Invalid('Muse row encoding') from exc
    if len(raw)>65536: raise Invalid('Muse row size')
    return hashlib.sha256(raw).hexdigest()

def transform(row,*,grant,verified_principal,selected_digest,category,record_id,revision=1,expires=None):
    """Return one candidate event. A separate core Policy approval is mandatory.

    selected_digest is a human-reviewed exact-row hash supplied by trusted local
    configuration, never accepted from imported row fields. No default mapping.
    Only confirmed active fact rows with finite numeric epoch timestamps are supported.
    """
    if not isinstance(record_id,str) or not 1<=len(record_id)<=128: raise Invalid('stable Muse row identity required')
    actual=row_digest(row)
    if not isinstance(grant,ScopeGrant): raise Denied('explicit local scope grant required')
    if not isinstance(verified_principal,str) or not verified_principal or verified_principal!=grant.principal: raise Denied('untrusted sender')
    if not isinstance(selected_digest,str) or selected_digest!=actual: raise Denied('explicit exact-row selection required')
    if row['scope']!=grant.scope: raise Denied('unmapped scope')
    if not isinstance(grant.scope,str) or not (grant.scope=='owner-private' or grant.scope.startswith('qq:c2c:') or grant.scope.startswith('qq:group:')): raise Denied('unsupported scope')
    identifier(grant.owner); identifier(grant.audience)
    if row['kind']!='fact' or row['evidence']!='confirmed' or row['status']!='active': raise Denied('only active confirmed facts')
    if category not in ('project_fact','task_state'): raise Denied('explicit project/task category required')
    for key in ('source','event_id','fingerprint'):
        if not isinstance(row[key],str) or not 1<=len(row[key])<=256: raise Invalid('Muse source identity')
    if type(row['importance']) not in (int,float) or not 0<=row['importance']<=1: raise Invalid('Muse importance')
    if row['supersedes'] not in (None,''): raise Denied('supersession requires explicit reconciliation')
    for key in ('occurred_at','created_at'):
        if type(row[key]) not in (int,float) or not 0<=row[key]<=2**53 or not math.isfinite(row[key]): raise Invalid('Muse timestamp')
    namespace=digest({'principal':grant.principal,'scope':grant.scope,'source':row['source']})
    identity=digest({'namespace':namespace,'event_id':row['event_id'],'record_id':record_id})
    # Neither raw scope IDs nor sender/source strings are exported.
    candidate={'id':'muse_'+digest({'identity':identity,'row':actual,'revision':revision})[:48],
               'owner':grant.owner,'source':'muse_'+namespace[:32],
               'fact':'muse_'+identity[:48],'revision':revision,'op':'put',
               'category':category,'text':row['text'],'timestamp':int(row['occurred_at']),
               'expires':expires,'provenance':'Explicitly selected confirmed Muse fact; local scope mapping'}
    return validate(candidate)


API_FIELDS = {'id','text','kind','source','event_id','evidence','occurred_at','truncated'}

def api_row_digest(row):
    if not isinstance(row,dict) or set(row)!=API_FIELDS: raise Invalid('Muse API row fields; merged rows require review')
    try: raw=canonical(row).encode('utf-8')
    except (TypeError,ValueError,UnicodeError) as exc: raise Invalid('Muse API encoding') from exc
    if len(raw)>65536: raise Invalid('Muse API row size')
    return hashlib.sha256(raw).hexdigest()

def transform_response(response,*,origin,selected_row_id,selected_digest,grant,verified_principal,category,revision=1,expires=None):
    """Adapt a trusted recall/prepare result's explicitly selected memories row.

    origin and grant.scope come from trusted request context, not response data.
    Other top-level fields are never traversed, hashed, serialized or exported.
    """
    if origin not in ('recall','prepare'): raise Denied('trusted recall/prepare origin required')
    if not isinstance(response,dict) or not isinstance(response.get('memories'),list) or len(response['memories'])>1000: raise Invalid('Muse memories response')
    if type(selected_row_id) is not int or selected_row_id<1: raise Invalid('Muse row id')
    rows=[r for r in response['memories'] if isinstance(r,dict) and type(r.get('id')) is int and r['id']==selected_row_id]
    if len(rows)!=1: raise Invalid('selected row missing or ambiguous')
    selected=rows[0]
    if selected_digest!=api_row_digest(selected): raise Denied('exact API row selection required')
    if selected['truncated'] is not False: raise Denied('truncated memory requires full-row review')
    if not isinstance(grant,ScopeGrant): raise Denied('trusted request scope required')
    # Active status is a recall/prepare contract, not an inferred remote field.
    row={'scope':grant.scope,'text':selected['text'],'kind':selected['kind'],
         'source':selected['source'],'event_id':selected['event_id'],
         'evidence':selected['evidence'],'status':'active','importance':0,
         'occurred_at':selected['occurred_at'],'created_at':selected['occurred_at'],
         'supersedes':None,'fingerprint':'selected-api-row'}
    return transform(row,grant=grant,verified_principal=verified_principal,
                     selected_digest=row_digest(row),category=category,
                     record_id=str(selected['id']),revision=revision,expires=expires)
