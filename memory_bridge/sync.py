"""Transport contract and in-memory CAS reference; github.py supplies explicit network transport."""
from .core import Invalid, Denied, identifier, digest, validate, MAX_BYTES, canonical

class Conflict(Invalid): pass

class FakePrivateTransport:
    """Test double, NOT a GitHub connection or persistent storage."""
    def __init__(self,private=True): self.private=private; self.files={}
    def verify_private(self): return self.private is True
    def read(self,path):
        value=self.files.get(path)
        # Deep copies prevent caller mutation from bypassing CAS.
        import copy
        return (digest(value),copy.deepcopy(value)) if value is not None else (None,[])
    def compare_and_swap(self,path,expected,events):
        if not self.verify_private(): raise Denied('private repository required')
        actual,_=self.read(path)
        if actual!=expected: raise Conflict('remote changed; pull and review again')
        import copy
        self.files[path]=copy.deepcopy(events)
        return digest(events)

def export(store,source,transport,*,dry_run=True):
    identifier(source)
    if not transport.verify_private(): raise Denied('private repository required')
    path=f'{store.owner}/{source}/events.json'
    revision,remote=transport.read(path)
    if not isinstance(remote,list) or len(remote)>1000: raise Invalid('remote limit')
    combined={}
    for event in remote:
        validate(event)
        if event['source']!=source or not store.policy.permits(event): raise Denied('remote event needs local approval')
        if event['id'] in combined: raise Invalid('duplicate remote event')
        combined[event['id']]=event
    for event in store.events():
        if event['source']!=source or not store.policy.permits(event): continue
        if event['id'] in combined and combined[event['id']]!=event: raise Invalid('remote event collision')
        combined[event['id']]=event
    events=sorted(combined.values(),key=lambda e:e['id'])
    if len(events)>1000 or len(canonical(events).encode())>MAX_BYTES: raise Invalid('export limit')
    result={'dry_run':dry_run,'path':path,'expected_revision':revision,'count':len(events)}
    if not dry_run: result['revision']=transport.compare_and_swap(path,revision,events)
    return result

def pull(store,source,transport,*,dry_run=True):
    identifier(source)
    if not transport.verify_private(): raise Denied('private repository required')
    _,events=transport.read(f'{store.owner}/{source}/events.json')
    if not isinstance(events,list) or len(events)>1000 or len(canonical(events).encode())>MAX_BYTES: raise Invalid('remote limit')
    for event in events:
        validate(event)
        if event['source']!=source or not store.policy.permits(event): raise Denied('remote event needs local approval')
    if not dry_run: store.ingest(events)
    return {'dry_run':dry_run,'count':len(events)}
