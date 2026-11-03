// Background source ingestion: no model call, no outbound chat capability.
import {readFileSync,writeFileSync,readdirSync,realpathSync,mkdirSync,renameSync,statSync,existsSync} from 'node:fs';
import {join,dirname,basename} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {scopeFor} from './qq-adapter.mjs';

const DEFAULT_ROOT=dirname(fileURLToPath(import.meta.url));

export function drainLearning(options={}){
 const root=options.root||DEFAULT_ROOT,codeRoot=options.codeRoot||DEFAULT_ROOT,bridge=options.bridgeDir||join(dirname(root),'qq-bridge');
 const python=options.python||(process.platform==='win32'?'python':'python3');
 let cfg;
 try{cfg=JSON.parse(readFileSync(join(root,'config.json'),'utf8'));}catch{return {ok:false,disabled:true};}
 if(cfg.enabled!==true||cfg.qq_enabled!==true||cfg.modules?.input!==true) return {ok:true,disabled:true,learned:0};
 const queue=join(root,'state','learning');
 if(!existsSync(queue)) return {ok:true,learned:0,failed:0};
 let learned=0,failed=0;
 for(const name of readdirSync(queue).filter(n=>/^[a-f0-9]{64}\.json$/.test(n)).slice(0,20)){
  const pending=join(queue,name);
  try{
   const ref=JSON.parse(readFileSync(pending,'utf8'));
   const parent=realpathSync(join(bridge,'inbox','processed'));
   const source=realpathSync(ref.source_file);
   if(dirname(source)!==parent||!basename(source).endsWith('.json')) throw Error('invalid_source');
   const prep=spawnSync(process.execPath,[join(bridge,'qq-prepare.mjs'),source],{encoding:'utf8',timeout:2000,maxBuffer:262144,windowsHide:true});
   if(prep.error||prep.status!==0) throw Error('prepare_failed');
   const prepared=JSON.parse(prep.stdout);
   const original=prepared.inbox;
   const scope=scopeFor(original,prepared.sender_identity);
   const event=String(original.event_id||original.id||basename(source));
   if(event!==ref.event_id) throw Error('event_changed');
   const text=typeof original.text==='string'&&original.text?original.text:'收到一个无可读正文的QQ事件；内容未解析，不能推断附件内容';
   const parsed=typeof original.ts==='number'&&Number.isFinite(original.ts)?original.ts:(typeof original.ts==='string'?Date.parse(original.ts):NaN);
   for(let offset=0;offset<text.length;offset+=10000){
    const request={op:'ingest',scope,text:text.slice(offset,offset+10000),source:'qq:'+source,
     event_id:event+':part:'+Math.floor(offset/10000),occurred_at:(Number.isFinite(parsed)?parsed:statSync(source).mtimeMs)/1000};
    const child=spawnSync(python,[join(codeRoot,'brain.py'),'--root',root],{input:JSON.stringify(request),encoding:'utf8',timeout:2000,maxBuffer:32768,windowsHide:true});
    if(child.error||child.status!==0||JSON.parse(child.stdout).ok!==true) throw Error('ingest_failed');
   }
   const done=join(root,'state','learning-done');mkdirSync(done,{recursive:true,mode:0o700});
   renameSync(pending,join(done,name)); learned++;
  }catch{
   failed++;
   // Quarantine failed references so a bad first batch cannot starve new events.
   // Recovery is explicit; this never generates/retries a QQ reply.
   const bad=join(root,'state','learning-failed');mkdirSync(bad,{recursive:true,mode:0o700});
   try{renameSync(pending,join(bad,name));}catch{/* leave reference if filesystem is unavailable */}
  }
 }
 return {ok:failed===0,learned,failed};
}

if(process.argv[1]&&fileURLToPath(import.meta.url)===process.argv[1]){
 console.log(JSON.stringify(drainLearning()));
}
