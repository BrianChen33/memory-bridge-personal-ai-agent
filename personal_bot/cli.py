"""CLI entrypoints for the portable runtime; nothing installs host APIs silently."""
import argparse,json,sys,subprocess
from pathlib import Path
from . import __version__
from . import deploy as d


def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Personal-bot local memory; explicit data root; host integration remains separate')
    p.add_argument('--root');p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='action',required=True)
    for name in ('init','status','doctor','self-test','rollback','relocate','companion-upgrade'):sub.add_parser(name)
    s=sub.add_parser('enable');s.add_argument('--features',default=','.join(d.DEFAULT_FEATURES))
    s=sub.add_parser('request');s.add_argument('--file')
    s=sub.add_parser('plugin');s.add_argument('operation',choices=('list','install','enable','disable'));s.add_argument('--id');s.add_argument('--source')
    s=sub.add_parser('backup');s.add_argument('--manual',action='store_true')
    s=sub.add_parser('verify');s.add_argument('--snapshot',required=True)
    s=sub.add_parser('restore');s.add_argument('--snapshot',required=True);s.add_argument('--destination',required=True)
    s=sub.add_parser('model');s.add_argument('operation',choices=['download','check','serve','service']);s.add_argument('--output')
    s=sub.add_parser('reminder');s.add_argument('--id',required=True);s.add_argument('--version',type=int,required=True);s.add_argument('--handoff',action='store_true')
    s=sub.add_parser('meme-sync');s.add_argument('--seed',action='store_true');s.add_argument('--seed-file');s.add_argument('--mode',choices=('incremental','full'),default='incremental');s.add_argument('--max-pages',type=int,default=30);s.add_argument('--max-details',type=int,default=60);s.add_argument('--budget-seconds',type=int,default=180)
    args=p.parse_args(argv)
    try:
        if args.action=='self-test':result=d.self_test()
        else:
            if not args.root:raise ValueError('root_required')
            root=d.root_path(args.root)
            if args.action=='init':result=d.init(root)
            else:
                d.owned(root)
                if args.action in ('status','doctor'):
                    result=d.request(root,{'op':'health'})
                    result.update(version=__version__,code_root=str(d.PACKAGE),data_root=str(root),
                        host=json.loads((root/'state/host-bindings.json').read_text(encoding='utf-8')),
                        deployment_scope='local_runtime_only_not_native_delivery_receipt')
                elif args.action=='enable':result=d.enable(root,args.features.split(',') if args.features else [])
                elif args.action=='plugin':
                    result=d.request(root,dict(op='plugin_manage',scope='owner-private',action=args.operation,
                                              plugin=args.id,source_dir=args.source))
                elif args.action=='meme-sync':
                    opts=['--root',str(root),'--mode',args.mode,'--max-pages',str(args.max_pages),'--max-details',str(args.max_details),'--budget-seconds',str(args.budget_seconds)]
                    if args.seed:opts+=['--seed']
                    if args.seed_file:opts+=['--seed-file',args.seed_file]
                    return d.module(root,'muse_ext.meme_sync',opts,timeout=args.budget_seconds+45)
                elif args.action=='companion-upgrade':
                    cfg=json.loads((root/'config.json').read_text(encoding='utf-8'))
                    cfg['companion_v2']=True;d.write_json(root/'config.json',cfg)
                    result=d.request(root,dict(op='health'))
                    result['host_prompts_require_v2_binding']=True
                elif args.action=='request':
                    data=Path(args.file).read_bytes() if args.file else sys.stdin.buffer.read(65537)
                    if len(data)>65536:raise ValueError('request_too_large')
                    q=json.loads(data.decode('utf-8-sig'))
                    if not isinstance(q,dict):raise ValueError('request_object_required')
                    result=d.request(root,q)
                elif args.action=='rollback':result=d.rollback(root)
                elif args.action=='relocate':result=d.relocate(root)
                elif args.action in ('backup','verify','restore'):
                    cmd=['create' if args.action=='backup' else args.action,'--root',str(root)]
                    if args.action=='backup' and args.manual:cmd+=['--manual']
                    if args.action!='backup':cmd+=['--snapshot',args.snapshot]
                    if args.action=='restore':cmd+=['--destination',args.destination]
                    return d.module(root,'muse_ext.backup',cmd)
                elif args.action=='reminder':
                    return d.module(root,'muse_ext.reminders',['--root',str(root),'--id',args.id,'--version',str(args.version)]+(['--handoff'] if args.handoff else []))
                elif args.action=='model':
                    if args.operation=='service':
                        if sys.platform=='win32':raise ValueError('systemd_template_requires_linux_use_foreground_serve')
                        if not args.output:raise ValueError('output_required')
                        def quote(s):return '"'+str(s).replace('\\','\\\\').replace('"','\\"').replace('%','%%').replace('$','$$')+'"'
                        command=' '.join(quote(x) for x in [sys.executable,'-m','personal_bot','--root',str(root),'model','serve'])
                        text='[Unit]\nDescription=Personal memory local encoder\nStartLimitIntervalSec=60\nStartLimitBurst=3\n\n[Service]\nType=simple\nWorkingDirectory='+quote(d.PACKAGE.parent)+'\nExecStart='+command+'\nRestart=on-failure\nRestartSec=10\n\n[Install]\nWantedBy=default.target\n'
                        output=Path(args.output)
                        with open(output,'x',encoding='utf-8') as f:f.write(text)
                        result=dict(ok=True,generated=str(output),installed=False,requires_host_service_install=True)
                    else:
                        cmd=['--folder',str(root/'models/bge'),'--manifest',str(d.RUNTIME/'model-assets.json')]
                        if args.operation!='serve':cmd+=['--'+args.operation]
                        return d.module(root,'muse_ext.embedding_server',cmd)
        print(json.dumps(result,ensure_ascii=False,allow_nan=False));return 0 if result.get('ok',True) else 1
    except (ValueError,OSError,RuntimeError,subprocess.SubprocessError) as exc:
        print(json.dumps(dict(ok=False,error=type(exc).__name__,reason=str(exc)[:180]),ensure_ascii=False));return 2

if __name__=='__main__':raise SystemExit(main())
