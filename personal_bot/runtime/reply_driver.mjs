#!/usr/bin/env node
// Fixed host driver. It cannot read native chat tools or intercept native final.
import {readFileSync,writeFileSync,mkdirSync,renameSync,lstatSync,existsSync,readdirSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {performance} from 'node:perf_hooks';
import {prepareMedia,finishMedia} from './reply_media.mjs';

const HERE=dirname(fileURLToPath(import.meta.url));
const hash=value=>createHash('sha256').update(value).digest('hex');
const arg=name=>{const i=process.argv.indexOf(name);return i<0?null:process.argv[i+1];};
const root=arg('--root'),chat=arg('--chat-id');
const brainRoot=process.env.STICKER_BRAIN_ROOT||(root&&join(root,'muse-brain'));
const folder=root&&join(root,'stickers','reply-rounds');
const schema='main-reply-ticket-v1';

function safe(path){
  if(existsSync(path)&&lstatSync(path).isSymbolicLink())throw Error('reply_state_symlink_refused');
  return path;
}
function atomic(path,value){
  safe(dirname(path));safe(path);
  mkdirSync(dirname(path),{recursive:true,mode:0o700});
  const temporary=path+'.'+randomUUID()+'.tmp';
  writeFileSync(temporary,JSON.stringify(value),{mode:0o600,flag:'wx'});
  renameSync(temporary,path);
}
function fingerprint(){
  const js=['main_native_entry.mjs','sticker_main.mjs','reply_driver.mjs','reply_media.mjs','main_entry_guard.mjs','sticker_decision.mjs'].map(name=>join(HERE,name));
  const modules=existsSync(join(brainRoot,'muse_ext'))?join(brainRoot,'muse_ext'):join(HERE,'muse_ext');
  const py=[join(brainRoot,'brain.py'),...readdirSync(modules).filter(name=>name.endsWith('.py')).sort().map(name=>join(modules,name))];
  return hash([...js,...py].map(path=>hash(readFileSync(path))).join(':'));
}
function boundTicket(record){
  return hash(JSON.stringify([record.schema,record.chat_id,record.source,record.reply_turn_id,
    record.native_sha256,record.core_fingerprint,record.created_at_ms]));
}
function run(request){
  const started=performance.now();
  const child=spawnSync(process.execPath,[join(HERE,'main_native_entry.mjs'),'--root',root,'--chat-id',chat],
    {input:JSON.stringify(request),encoding:'utf8',timeout:65000,maxBuffer:524288});
  let result;
  try{result=JSON.parse(child.stdout);}catch{result={ok:false,error:'native_driver_response_unavailable'};}
  if(child.error)result={ok:false,error:'native_driver_process_failed'};
  return {result,core_ms:Math.round((performance.now()-started)*100)/100};
}
function ticketPath(ticket){
  if(typeof ticket!=='string'||!/^[a-f0-9]{64}$/.test(ticket))throw Error('source_ticket_required');
  return safe(join(folder,ticket+'.json'));
}
function load(ticket){
  safe(folder);
  const bytes=readFileSync(ticketPath(ticket));
  if(bytes.length>2097152)throw Error('source_ticket_too_large');
  const record=JSON.parse(bytes);
  if(record.schema!==schema||record.chat_id!==chat||record.ticket!==ticket||
     boundTicket(record)!==ticket||
     record.core_fingerprint!==fingerprint()||record.native_sha256!==hash(JSON.stringify(record.native))||
     Date.now()-record.created_at_ms>86400000)throw Error('source_ticket_stale_or_changed');
  const turn=record.native?.turns?.[0];
  const item=turn?.items?.find(item=>item.seq===record.source?.seq);
  if(record.native?.chat_id!==chat||turn?.id!==record.source?.turn_id||item?.role!=='user'||
     typeof item.content!=='string'||hash(item.content)!==record.source.input_sha256||
     item.occurred_at_ms!==record.source.occurred_at_ms)throw Error('source_ticket_binding_invalid');
  const first=Math.min(...turn.items.filter(item=>item.role==='user'&&item.content.trim()).map(item=>item.seq));
  if(record.reply_turn_id!==(item.seq===first?turn.id:turn.id+':user:'+item.seq))throw Error('source_ticket_binding_invalid');
  return record;
}
function remember(native,source,replyTurn){
  const turn=native.turns.find(turn=>turn.id===source.turn_id);
  const item=turn?.items?.find(item=>item.role==='user'&&item.seq===source.seq);
  if(!item||hash(item.content)!==source.input_sha256)throw Error('actual_native_ticket_source_required');
  const core_fingerprint=fingerprint();
  const projected={chat_id:chat,page:native.page||null,
    turns:[{id:turn.id,items:turn.items.filter(item=>item.role==='user')}]};
  const boundSource={...source,occurred_at_ms:item.occurred_at_ms};
  const record={schema,chat_id:chat,source:boundSource,reply_turn_id:replyTurn,native:projected,
    native_sha256:hash(JSON.stringify(projected)),core_fingerprint,created_at_ms:Date.now()};
  record.ticket=boundTicket(record);
  atomic(ticketPath(record.ticket),record);
  return record;
}
function metric(phase,result,record,core_ms,started){
  const now=Date.now();
  const row={at_ms:now,phase,ticket:record?.ticket||null,seq:record?.source?.seq??null,
    ok:result.ok===true,ready_to_send:result.ready_to_send===true,
    core_ms,local_ms:Math.round((performance.now()-started)*100)/100,
    source_elapsed_ms:record?now-record.source.occurred_at_ms:null};
  const path=safe(join(folder,'timings.json'));
  let rows=[];try{rows=JSON.parse(readFileSync(path,'utf8'));}catch{}
  if(!Array.isArray(rows))rows=[];
  rows=[...rows.slice(-199),row];atomic(path,rows);
  atomic(join(brainRoot,'state','reply-driver-health.json'),{
    schema:'reply-driver-health-v1',observed_at:now/1000,last:row,samples:rows.length,
    boundary:'local subprocess timing; source elapsed includes host/model/tools/queue and is not model-only time'});
  return row;
}
function stats(){
  safe(folder);let rows=[];
  try{rows=JSON.parse(readFileSync(safe(join(folder,'timings.json')),'utf8'));}catch{}
  const phases={};
  for(const phase of ['context','commit','gate']){
    const values=rows.filter(row=>row.phase===phase&&row.ok).map(row=>row.local_ms).sort((a,b)=>a-b);
    if(values.length)phases[phase]={count:values.length,
      median_local_ms:values[Math.floor((values.length-1)/2)],
      p95_local_ms:values[Math.ceil(values.length*.95)-1]};
  }
  return {ok:true,samples:rows.length,phases,last:rows.at(-1)||null,
    boundary:'No platform model/queue telemetry is available here. Timings contain no chat text.'};
}
function main(){
  if(process.argv.includes('--help'))return {ok:true,
    usage:'reply_driver.mjs --root WORKSPACE --chat-id TRUSTED_CHAT < JSON',
    context:'{phase:context,native_response:ACTUAL_TOOL_RESULT}',
    commit:'{phase:commit,ticket:RETURNED_TICKET,emotion_assessment:FILLED_CONTEXT_TEMPLATE}',
    optional:'commit may include fresh native_response after long tools; gate/stats are read-only protocol checks',
    boundary:'same host model appraises48 before text; no native-final interception or sender'};
  if(!root||!chat)return {ok:false,error:'trusted_workspace_and_chat_required'};
  const bytes=readFileSync(0);
  if(bytes.length>2097152)return {ok:false,error:'bounded_native_request_required'};
  let request;try{request=JSON.parse(bytes.toString('utf8'));}catch{return {ok:false,error:'JSON_stdin_required'};}
  const phase=request.phase||'context';
  if(phase==='stats')return stats();
  if(!['context','commit','gate','media','finish'].includes(phase))return {ok:false,error:'invalid_reply_driver_phase'};
  if(phase==='finish'){const saved=load(request.ticket);return finishMedia(root,saved.reply_turn_id,request);}
  const started=performance.now();let record,executed;
  if(phase==='context'){
    executed=run({phase,native_response:request.native_response,
      ...(request.target_seq===undefined?{}:{target_seq:request.target_seq}),
      ...(request.target_turn_id===undefined?{}:{target_turn_id:request.target_turn_id})});
    if(executed.result.ok&&executed.result.context?.emotion_template?.format==='full48-v1'){
      executed.result.context.emotion_template={...executed.result.context.emotion_template,
        format:'compact48-v1',emotion_deltas:{}};
      executed.result.context.emotion_protocol={...executed.result.context.emotion_protocol,
        preferred_format:'compact48-v1'};
    }
    if(executed.result.ok&&executed.result.native_source&&executed.result.formal_entry?.context_recorded)
      record=remember(request.native_response,executed.result.native_source,executed.result.turnId);
  }else{
    record=load(request.ticket);
    const forwarded={phase:phase==='media'?'gate':phase,native_response:request.native_response||record.native,
      target_seq:record.source.seq,target_turn_id:record.source.turn_id};
    for(const field of ['emotion_assessment','humor_assessment','meme_updates','reading_documents'])
      if(request[field]!==undefined)forwarded[field]=request[field];
    executed=run(forwarded);
  }
  if(['commit','media'].includes(phase)&&executed.result.ready_to_send&&request.media!==false){
    try{executed.result.media=prepareMedia(root,record.reply_turn_id,
      {query:request.media_query||'',emotion:request.media_emotion||executed.result.mood?.label||''});}
    catch{executed.result.media={ok:false,status:'media_unavailable',sampled:executed.result.decision?.sampled===true};}
  }
  const timing=metric(phase,executed.result,record,executed.core_ms,started);
  return {...executed.result,...(record?{ticket:record.ticket}:{}),timing,
    driver:'fixed-source-ticket-v1',next:executed.result.ready_to_send?
      'Reply now from the retained context and updates. Optional maintenance must not delay text.':
      phase==='context'&&record?'The SAME host model fills the template with affected labels only (omitted=0); commit this ticket. No extra reflection or second prepare.':
      'Use the specific validation error; no reroll, invented input or repeated repair loop.'};
}
try{const result=main();process.stdout.write(JSON.stringify(result)+'\n');if(!result.ok)process.exitCode=1;}
catch(error){process.stdout.write(JSON.stringify({ok:false,error:/^(source_ticket_|reply_state_|actual_native_)/.test(error.message)?
  error.message:'reply_driver_failed'})+'\n');process.exitCode=1;}
