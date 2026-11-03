// Bounded local enhancement. No network, token or reply sending capabilities.
import {readFileSync,writeFileSync,renameSync,mkdirSync,existsSync,realpathSync} from 'node:fs';
import {dirname,join,resolve,basename,isAbsolute} from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';
import {createHash,randomUUID} from 'node:crypto';

const DEFAULT_ROOT=dirname(fileURLToPath(import.meta.url));
const validId=x=>typeof x==='string'&&/^[A-Za-z0-9_-]{1,128}$/.test(x);

export function scopeFor(data,identity){
  const t=data?.reply_target;
  if(!data||identity?.sender_id!==data.sender_id||!validId(data.sender_id)||!validId(t?.targetId)) throw Error('invalid_identity');
  if(t.scope==='group') return `qq:group:${t.targetId}`;
  if(t.scope!=='c2c'||t.targetId!==data.sender_id) throw Error('invalid_c2c_target');
  return identity.is_master===true?'owner-private':`qq:c2c:${data.sender_id}`;
}

function config(root){
  try{return JSON.parse(readFileSync(join(root,'config.json'),'utf8'));}catch{return {};}
}

export function prepareRequest(data,identity,scope){
  const bot=identity.record?.type==='bot';
  const request={op:'prepare',scope,text:(typeof data.text==='string'?data.text:'').slice(0,12000),
    sender_type:bot?'bot':'human',actor:bot?'bot':'user',source:'qq:bridge'};
  if(typeof data.id==='string'&&data.id.length<=256) request.event_id=data.id;
  if(typeof data.ts==='number'&&Number.isFinite(data.ts)&&data.ts>0) request.occurred_at=data.ts/1000;
  return request;
}

export function enhance(prepared,options={}){
  const start=Date.now(),root=options.root||DEFAULT_ROOT,codeRoot=options.codeRoot||DEFAULT_ROOT;
  const cfg=config(root);
  if(cfg.enabled!==true||cfg.qq_enabled!==true) return {disabled:true,memories:[],elapsed_ms:Date.now()-start};
  try{
    const data=prepared.inbox, identity=prepared.sender_identity;
    const scope=scopeFor(data,identity);
    const request=prepareRequest(data,identity,scope);
    const child=spawnSync(options.python||(process.platform==='win32'?'python':'python3'),
      [join(codeRoot,'brain.py'),'--root',root],{input:JSON.stringify(request),encoding:'utf8',timeout:450,maxBuffer:32768,windowsHide:true});
    if(child.error||child.status!==0) throw Error('core_degraded');
    const result=JSON.parse(child.stdout);
    if(result.ok!==true||!Array.isArray(result.memories)) throw Error('invalid_response');
    return {...result,elapsed_ms:Date.now()-start,scope,logical_isolation_only:true};
  }catch{
    return {ok:false,degraded:true,memories:[],elapsed_ms:Date.now()-start};
  }
}

export function enqueueLearning(bridgeDir,inboxFile,options={}){
  const root=options.root||DEFAULT_ROOT,codeRoot=options.codeRoot||DEFAULT_ROOT;
  const cfg=config(root);
  if(cfg.enabled!==true||cfg.qq_enabled!==true||cfg.modules?.input!==true) return {ok:false,disabled:true};
  try{
    if(typeof inboxFile!=='string'||!inboxFile) throw Error('invalid_ref');
    if(isAbsolute(inboxFile)){
      if(dirname(resolve(inboxFile))!==resolve(bridgeDir,'inbox')) throw Error('invalid_ref');
    }else if(basename(inboxFile)!==inboxFile) throw Error('invalid_ref');
    const processed=realpathSync(join(bridgeDir,'inbox','processed'));
    const source=realpathSync(join(processed,basename(inboxFile)));
    if(dirname(source)!==processed) throw Error('invalid_ref');
    const original=JSON.parse(readFileSync(source,'utf8'));
    const eventId=String(original.event_id||original.id||basename(source));
    const key=createHash('sha256').update(source+'\0'+eventId).digest('hex');
    const folder=join(root,'state','learning');
    mkdirSync(folder,{recursive:true,mode:0o700});
    const target=join(folder,key+'.json');
    if(!existsSync(target)){
      const tmp=join(folder,'.'+randomUUID()+'.tmp');
      writeFileSync(tmp,JSON.stringify({event_id:eventId,source_file:source,queued_at_ms:Date.now()}),{encoding:'utf8',mode:0o600});
      renameSync(tmp,target);
    }
    return {ok:true,key};
  }catch{
    // Failure cannot change an already committed QQ reply's success.
    return {ok:false,degraded:true};
  }
}
