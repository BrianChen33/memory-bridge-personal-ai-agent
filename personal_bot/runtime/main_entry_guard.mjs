// A local protocol gate, not an interceptor for a platform's native final.
import {readFileSync,writeFileSync,mkdirSync,renameSync,openSync,closeSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {createHash} from 'node:crypto';

const digest=text=>createHash('sha256').update(text).digest('hex');
const key=q=>digest('main:'+q.turnId);
function folder(root){return join(root,'stickers','main-entry');}
function read(root,q){try{return JSON.parse(readFileSync(join(folder(root),key(q)+'.json'),'utf8'));}catch{return null;}}
function atomic(path,value){const temp=path+'.'+process.pid+'.tmp';writeFileSync(temp,JSON.stringify(value),{mode:0o600});renameSync(temp,path);}
function nativeValid(value){return value&&typeof value.chat_id==='string'&&value.chat_id.length>0&&value.chat_id.length<=512&&
 typeof value.turn_id==='string'&&value.turn_id.length>0&&value.turn_id.length<=200&&Number.isSafeInteger(value.seq)&&value.seq>=0&&
 typeof value.input_sha256==='string'&&/^[a-f0-9]{64}$/.test(value.input_sha256);}
function headPath(root,chat){return join(folder(root),'native-head-'+digest(chat)+'.json');}
function head(root,chat){try{const value=JSON.parse(readFileSync(headPath(root,chat),'utf8'));
 return nativeValid(value)&&value.schema==='main-native-head-v1'&&typeof value.source_timestamp==='number'&&
  Number.isFinite(value.source_timestamp)?value:{invalid:true};}
 catch(error){return error.code==='ENOENT'?null:{invalid:true};}}
function nativeConflict(a,b){return ['chat_id','turn_id','seq','input_sha256','source_timestamp'].some(k=>a[k]!==b[k]);}
function nativeFreshness(root,q){
 if(!q.native)return {ok:true};
 const latest=head(root,q.native.chat_id);
 if(latest?.invalid)return {ok:false,error:'native_source_head_invalid'};
 if(latest&&q.native.seq<latest.seq)return {ok:false,error:'new_owner_turn_requires_context',latest_seq:latest.seq};
 return {ok:true};
}
function sourceConflict(old,q){return Boolean(q.native&&(!nativeValid(q.native)||q.native.input_sha256!==digest(q.text)))||
 Boolean(old&&(old.input_sha256!==digest(q.text)||old.actor!==(q.actor||'user')||
 (typeof old.source_timestamp==='number'&&typeof q.timestamp==='number'&&old.source_timestamp!==q.timestamp)||
 (old.native_source&&(!q.native||['chat_id','turn_id','seq','input_sha256'].some(k=>old.native_source[k]!==q.native[k])))));}

// Remember only native identity/hash/time. A stale read cannot become current
// again merely by omitting the newer item from a later host-supplied snapshot.
export function observeNativeSource(root,q){
 if(!q.native)return {ok:true};
 if((q.actor||'user')!=='user'||!nativeValid(q.native)||q.native.input_sha256!==digest(q.text)||
    (q.turnId!==q.native.turn_id&&q.turnId!==q.native.turn_id+':user:'+q.native.seq))
  return {ok:false,error:'native_source_binding_invalid'};
 const latest=q.native_head||{...q.native,source_timestamp:q.timestamp};
 if(!nativeValid(latest)||latest.chat_id!==q.native.chat_id||latest.seq<q.native.seq||
    typeof latest.source_timestamp!=='number'||!Number.isFinite(latest.source_timestamp)||
    (latest.seq===q.native.seq&&nativeConflict(latest,{...q.native,source_timestamp:q.timestamp})))
  return {ok:false,error:'native_source_binding_invalid'};
 mkdirSync(folder(root),{recursive:true,mode:0o700});
 const path=headPath(root,latest.chat_id),lock=path+'.lock';let fd;
 try{fd=openSync(lock,'wx',0o600);}catch{return {ok:false,error:'main_entry_busy'};}
 try{
  const prior=head(root,latest.chat_id);
  if(prior?.invalid)return {ok:false,error:'native_source_head_invalid'};
  if(prior&&prior.seq===latest.seq&&nativeConflict(prior,latest))return {ok:false,error:'main_entry_input_conflict'};
  if(!prior||latest.seq>prior.seq)atomic(path,{schema:'main-native-head-v1',...latest});
  return nativeFreshness(root,q);
 }finally{closeSync(fd);try{unlinkSync(lock);}catch{}}
}

export function recordEntry(root,q,patch){
 mkdirSync(folder(root),{recursive:true,mode:0o700});
 const path=join(folder(root),key(q)+'.json'),lock=path+'.lock';let fd;
 try{fd=openSync(lock,'wx',0o600);}catch{return {ok:false,error:'main_entry_busy'};}
 try{
  const old=read(root,q),hash=digest(q.text);
  if(sourceConflict(old,q))return {ok:false,error:'main_entry_input_conflict'};
  const fresh=nativeFreshness(root,q);if(!fresh.ok)return fresh;
  if(patch.finalized_ok&&!old?.context_ok)return {ok:false,error:'main_entry_context_required'};
  if((patch.context_ok&&old?.context_event_id&&patch.context_event_id!==old.context_event_id)||
     (patch.finalized_ok&&patch.finalized_event_id!==old.context_event_id))
   return {ok:false,error:'main_entry_event_conflict'};
  const value={schema:'main-entry-v1',turnId:q.turnId,input_sha256:hash,actor:q.actor||'user',
   ...old,...patch,source_timestamp:typeof old?.source_timestamp==='number'?old.source_timestamp:q.timestamp??null,
   native_source:old?.native_source||q.native||null,updated_at:Date.now()/1000};
  atomic(path,value);return {ok:true,record:value};
 }finally{closeSync(fd);try{unlinkSync(lock);}catch{}}
}

export function entryStatus(root,q,decision,{requireLatest=true}={}){
 const receipt=read(root,q),missing=[];
 if(!receipt?.context_ok||!Number.isSafeInteger(receipt.context_event_id)||receipt.context_event_id<=0)missing.push('context');
 if(sourceConflict(receipt,q))missing.push('source_conflict');
 const fresh=requireLatest?nativeFreshness(root,q):{ok:true};
 if(!fresh.ok)missing.push(fresh.error);
 if(!receipt?.finalized_ok||receipt.finalized_event_id!==receipt.context_event_id||
    !['updated','unchanged','replayed'].includes(receipt?.assessment_status))missing.push('full48_assessment');
 if(!decision||!['auto','direct','skip','disabled'].includes(decision.mode)||decision.scope!=='main'||decision.turn_id!==q.turnId||
    decision.event_id!==q.turnId||decision.input_hash!==digest(q.text).slice(0,16))missing.push('sticker_decision');
 if(receipt?.reading_documents?.length&&!receipt?.reading_complete)missing.push('reading_completion');
 const ready=missing.length===0;
 return {ok:ready,ready_to_send:ready,turnId:q.turnId,missing,
  event_id:receipt?.context_event_id??null,source_sha256:receipt?.input_sha256??null,
  source_timestamp:receipt?.source_timestamp??null,
  assessment_status:receipt?.assessment_status??null,
  boundary:'local entry validation only; native final interception is not provided by this module',
  next:ready?'Compose the normal persona reply from the prepared context and returned state updates.':'Repair this same native turn; do not reroll, fabricate an assessment or claim success.'};
}

export function boundReadings(root,q){
 const prior=read(root,q)?.reading_documents||[];
 const supplied=q.reading_documents||[];
 if(!Array.isArray(supplied)||supplied.length>3||supplied.some(x=>typeof x!=='string'||!x||x.length>128))
  throw Error('invalid_reading_bindings');
 const result=[...new Set([...prior,...supplied])];
 if(result.length>3)throw Error('too_many_reading_bindings');
 return result;
}

export function auditEntries(root,brainRoot,turns,getDecision){
 if(!Array.isArray(turns)||turns.length>20||turns.some(q=>!q||typeof q.turnId!=='string'||!q.turnId||q.turnId.length>256||
   typeof q.text!=='string'||q.text.length>12000||(q.actor&&q.actor!=='user')))return {ok:false,error:'bounded_native_owner_turn_sample_required'};
 let enabledAt=0;try{enabledAt=JSON.parse(readFileSync(join(brainRoot,'state','formal-entry-policy.json'),'utf8')).enabled_at||0;}catch{}
 const seen=new Set(),results=[];let legacy=0;
 for(const q of turns){
  if(/^(?:\[Codex调试\]|［Codex调试］)/.test(q.text.trimStart()))continue;
  if(seen.has(q.turnId))continue;seen.add(q.turnId);
  if(enabledAt&&typeof q.timestamp==='number'&&q.timestamp<enabledAt){legacy++;continue;}
  const result=entryStatus(root,q,getDecision('main',q.turnId),{requireLatest:false});
  results.push({turnId:q.turnId,ready:result.ready_to_send,missing:result.missing});
 }
 const health={schema:'main-entry-audit-v1',observed_at:Date.now()/1000,coverage:'host-supplied recent native owner-turn sample only',
  checked:results.length,legacy_skipped:legacy,complete:results.filter(x=>x.ready).length,gaps:results.filter(x=>!x.ready),
  repairs_performed:false,native_interceptor:false};
 const state=join(brainRoot,'state');mkdirSync(state,{recursive:true,mode:0o700});atomic(join(state,'formal-entry-health.json'),health);
 return {ok:true,audit:health};
}
