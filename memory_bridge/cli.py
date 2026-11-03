"""Local CLI. Explicit approval is stored separately from synced event data."""
import argparse
import json
import os
import sys
import time
from .core import Policy, Store, Invalid, Denied, read_file, safe_file, strict_json, canonical

def load_policy(root,owner,audience):
    policy=Policy(owner,audience)
    path=safe_file(root,'approvals.json')
    if path.exists():
        doc=read_file(root,'approvals.json')
        if not isinstance(doc,dict) or set(doc)!={'owner','audience','grants'} or doc['owner']!=owner or doc['audience']!=audience: raise Denied('local policy scope')
        grants=doc['grants']
        if not isinstance(grants,list) or len(grants)>1000: raise Invalid('grant limit')
        for grant in grants:
            if not isinstance(grant,dict) or set(grant)!={'event','until'}: raise Invalid('grant schema')
            if type(grant['until']) is not int: raise Invalid('grant expiry')
            if grant['until']>time.time(): policy.approve(grant['event'],audience=audience,until=grant['until'],consent=True)
    return policy

def main(argv=None):
    p=argparse.ArgumentParser(description='Local external memory; no native persona access; network sync requires explicit consent')
    p.add_argument('--root',required=True); p.add_argument('--owner',required=True); p.add_argument('--audience',default='shared')
    sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('approve'); a.add_argument('file'); a.add_argument('--until',type=int,required=True); a.add_argument('--consent',action='store_true')
    a=sub.add_parser('ingest'); a.add_argument('file')
    a=sub.add_parser('query'); a.add_argument('text',nargs='?',default='')
    a=sub.add_parser('revoke'); a.add_argument('event_id')
    a=sub.add_parser('backup'); a.add_argument('file')
    a=sub.add_parser('restore'); a.add_argument('file')
    sub.add_parser('mcp')
    a=sub.add_parser('sync'); a.add_argument('--repository',required=True); a.add_argument('--source',required=True); a.add_argument('--direction',choices=['push','pull'],default='push'); a.add_argument('--network-consent',action='store_true'); a.add_argument('--apply',action='store_true')
    args=p.parse_args(argv)
    try:
        policy=load_policy(args.root,args.owner,args.audience)
        if args.command in ('approve','revoke'):
            path=safe_file(args.root,'approvals.json'); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            doc=read_file(args.root,'approvals.json') if path.exists() else {'owner':args.owner,'audience':args.audience,'grants':[]}
            if args.command=='approve':
                event=read_file(args.root,args.file)
                policy.approve(event,audience=args.audience,until=args.until,consent=args.consent)
                doc['grants']=[g for g in doc['grants'] if g['event']['id']!=event['id']]+[{'event':event,'until':args.until}]
            else: doc['grants']=[g for g in doc['grants'] if g['event']['id']!=args.event_id]
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'w') as stream: stream.write(canonical(doc))
            print(json.dumps({'status':'local_policy_updated'})); return 0
        store=Store(args.root,args.owner,policy)
        try:
            if args.command=='ingest': store.ingest([read_file(args.root,args.file)]); print('{"status":"ingested"}')
            elif args.command=='query': print(json.dumps(store.query(args.text),ensure_ascii=False))
            elif args.command=='backup': store.backup(args.root,args.file); print('{"status":"backed_up"}')
            elif args.command=='restore': store.restore(args.root,args.file); print('{"status":"restored"}')
            elif args.command=='sync':
                from .github import GitHubTransport
                from .sync import export,pull
                transport=GitHubTransport(args.repository,os.environ.get('MEMORY_BRIDGE_GITHUB_TOKEN',''),network_consent=args.network_consent,write_consent=args.apply)
                action=export if args.direction=='push' else pull
                print(json.dumps(action(store,args.source,transport,dry_run=not args.apply)))
            elif args.command=='mcp':
                from .mcp import serve
                store.refresh_policy = lambda: load_policy(args.root,args.owner,args.audience)
                serve(store)
        finally: store.close()
        return 0
    except (Invalid,OSError,ValueError) as exc:
        print(json.dumps({'error':str(exc)}),file=sys.stderr); return 2
