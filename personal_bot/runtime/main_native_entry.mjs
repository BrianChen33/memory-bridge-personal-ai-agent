#!/usr/bin/env node
// Muse native message adapter. The host supplies the real read_messages result.
import {readFileSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';

function main(){
 if(process.argv.includes('--help'))return {ok:true,usage:'main_native_entry.mjs --root WORKSPACE --chat-id TRUSTED_OWNER_CHAT < request.json',
  input:'{phase:context|commit|gate|audit|feedback,native_response:real_chat_read_messages_result,target_seq?,target_turn_id?,emotion_assessment?,reading_documents?}',
  boundary:'host performs chat.read_messages; this local adapter cannot intercept native final or access a chat API'};
 const argument=name=>{const i=process.argv.indexOf(name);return i<0?null:process.argv[i+1];};
 const root=argument('--root'),chat=argument('--chat-id');
 if(!root||!chat)return {ok:false,error:'trusted_workspace_and_owner_chat_binding_required'};
 let q;try{q=JSON.parse(readFileSync(0,'utf8'));}catch{return {ok:false,error:'native_JSON_stdin_required'};}
 const native=q.native_response;
 if(!native||native.chat_id!==chat||!Array.isArray(native.turns)||native.turns.length>100)
  return {ok:false,error:'bound_native_chat_response_required'};
 const rows=[],ignored=[],outputs=[];
 for(const turn of native.turns){
  if(typeof turn.id!=='string'||!turn.id||turn.id.length>200||!Array.isArray(turn.items))return {ok:false,error:'unsupported_native_turn_shape'};
  // Only the scheduled feedback phase consumes actual assistant output. It is
  // usage evidence, never an emotional stimulus or a new user input.
  for(const item of turn.items.filter(x=>x?.role==='assistant')){
   if(typeof item.content==='string'&&item.content.trim()&&item.content.length<=12000&&
      Number.isSafeInteger(item.seq)&&item.seq>=0&&Number.isFinite(item.occurred_at_ms)&&item.occurred_at_ms>0)
    outputs.push({chat_id:chat,turn_id:turn.id,seq:item.seq,occurred_at_ms:item.occurred_at_ms,text:item.content});
  }
  const users=turn.items.filter(x=>x?.role==='user');
  const meaningful=[];
  for(const item of users){
   if(typeof item.content!=='string'||item.content.length>12000||!Number.isSafeInteger(item.seq)||item.seq<0||
      !Number.isFinite(item.occurred_at_ms)||item.occurred_at_ms<=0)return {ok:false,error:'native_user_text_seq_and_timestamp_required'};
   if(!item.content.trim()){
    if(Object.keys(item).some(k=>!['role','content','seq','occurred_at_ms'].includes(k)))
     return {ok:false,error:'native_empty_media_or_unknown_payload_requires_adapter'};
    ignored.push({seq:item.seq,turn_id:turn.id});continue;
   }
   meaningful.push(item);
  }
  const first=meaningful.length?Math.min(...meaningful.map(item=>item.seq)):null;
  for(const item of meaningful){
   rows.push({turnId:item.seq===first?turn.id:turn.id+':user:'+item.seq,text:item.content,
    timestamp:item.occurred_at_ms/1000,actor:'user',native:{chat_id:chat,turn_id:turn.id,seq:item.seq,
     input_sha256:createHash('sha256').update(item.content).digest('hex')}});
  }
 }
 rows.sort((a,b)=>b.native.seq-a.native.seq);
 const phase=q.phase||'context';
 if(!['context','commit','gate','audit','feedback'].includes(phase))return {ok:false,error:'invalid_native_entry_phase'};
 if(phase==='feedback'){
  // This is the existing scheduled model's bounded historical scan. It never
  // goes through sticker decisions or changes the current native-source head.
  const brainRoot=process.env.STICKER_BRAIN_ROOT||join(root,'muse-brain');
  const users=rows.slice(0,20).map(r=>({source:'main:sticker',event_id:r.turnId,actor:'user',text:r.text,occurred_at:r.timestamp}));
  const delivered=outputs.sort((a,b)=>b.seq-a.seq).slice(0,20);
  const request={op:'companion_feedback',action:'scan',scope:'owner-private',native_events:[],native_outputs:[],
    coverage:{chat_id:chat,page:native.page||null,sample_size:rows.length,partial:rows.length>20||outputs.length>20}};
  // The real brain stdin limit is64KiB. Select complete records, never truncate
  // originals, and give both user and assistant evidence room in this batch.
  for(let i=0;i<Math.max(users.length,delivered.length);i++)for(const [field,item] of
    [['native_events',users[i]],['native_outputs',delivered[i]]]){
    if(!item)continue;request[field].push(item);
    if(Buffer.byteLength(JSON.stringify(request),'utf8')>60000){request[field].pop();request.coverage.partial=true;}
  }
  const result=spawnSync(process.env.STICKER_PYTHON||'python3',[join(brainRoot,'brain.py'),'--root',brainRoot],
    {input:JSON.stringify(request),encoding:'utf8',timeout:8000,maxBuffer:262144});
  if(result.error||!result.stdout)return {ok:false,error:'feedback_scan_process_failed'};
  let output;try{output=JSON.parse(result.stdout);}catch{return {ok:false,error:'feedback_scan_output_invalid'};}
  if(result.status!==0&&output.ok!==false)return {ok:false,error:'feedback_scan_process_failed'};
  return {...output,native_sample:{chat_id:chat,page:native.page||null,coverage:'recent verified sample; assistant output for usage evidence only'}};
 }
 let selected;
 if(phase!=='audit'){
  const blank=ignored.find(r=>(q.target_seq!==undefined?r.seq===q.target_seq:
    phase==='context'&&r.seq>Math.max(-1,...rows.map(x=>x.native.seq)))&&
    (q.target_turn_id===undefined||r.turn_id===q.target_turn_id));
  if(blank||(!rows.length&&ignored.length))return {ok:true,event:'empty_user_input_ignored',response_required:false,ready_to_send:false};
  selected=rows.find(r=>(q.target_seq===undefined||r.native.seq===q.target_seq)&&
    (q.target_turn_id===undefined||r.native.turn_id===q.target_turn_id));
  if(!selected)return {ok:false,error:'actual_owner_user_item_not_found'};
  if((phase==='commit'||phase==='gate')&&selected.native.seq!==rows[0].native.seq)
   return {ok:false,error:'new_owner_turn_requires_context',latest_seq:rows[0].native.seq};
 }
 const input=phase==='audit'?{phase:'audit',turns:rows.slice(0,20)}:{...selected,phase,
  native_head:{...rows[0].native,source_timestamp:rows[0].timestamp},
  ...(q.emotion_assessment===undefined?{}:{emotion_assessment:q.emotion_assessment}),
  ...(q.humor_assessment===undefined?{}:{humor_assessment:q.humor_assessment}),
  ...(q.meme_updates===undefined?{}:{meme_updates:q.meme_updates}),
  ...(q.reading_documents===undefined?{}:{reading_documents:q.reading_documents})};
 const result=spawnSync(process.execPath,[join(dirname(fileURLToPath(import.meta.url)),'sticker_main.mjs'),'--root',root],
  {input:JSON.stringify(input),encoding:'utf8',timeout:60000,maxBuffer:262144});
 if(result.error||!result.stdout)return {ok:false,error:'main_entry_process_failed'};
 let output;try{output=JSON.parse(result.stdout);}catch{return {ok:false,error:'main_entry_output_invalid'};}
 if(selected)output.native_source=selected.native;
 if(phase==='audit')output.native_sample={chat_id:chat,page:native.page||null,coverage:'recent sample only'};
 return output;
}
try{const result=main();process.stdout.write(JSON.stringify(result)+'\n');if(!result.ok)process.exitCode=1;}
catch{process.stdout.write(JSON.stringify({ok:false,error:'native_entry_failed'})+'\n');process.exitCode=1;}
