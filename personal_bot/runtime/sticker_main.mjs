#!/usr/bin/env node
// Host main-chat adapter. Native final is rule-driven, not a platform hard hook.
// JSON stdin: trusted turnId/text/timestamp, phase=context|finalize|finish,
// emotion_assessment v2, and actual delivery receipts for finish.
import {readFileSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {spawnSync} from 'node:child_process';
import {decide,setPaths,getDecision,settleDecision} from './sticker_decision.mjs';
import {classifyIntent} from './sticker_intent.mjs';
import {recordEntry,entryStatus,auditEntries,boundReadings} from './main_entry_guard.mjs';
const HERE=dirname(fileURLToPath(import.meta.url));
const arg=process.argv.indexOf('--root');
const workspace=arg>=0?process.argv[arg+1]:(process.env.STICKER_ROOT||join(HERE,'..','..'));
const brainRoot=process.env.STICKER_BRAIN_ROOT||join(workspace,'muse-brain');
setPaths({configPath:join(workspace,'stickers','config.json'),decisionDir:join(workspace,'stickers','decisions')});
function runBrain(req){
  const child=spawnSync(process.env.STICKER_PYTHON||'python3',[join(brainRoot,'brain.py'),'--root',brainRoot],
    {input:JSON.stringify(req),encoding:'utf8',timeout:8000,maxBuffer:131072});
  if(child.error||child.status!==0)return {ok:false,error:'brain_call_failed'};
  try{return JSON.parse(child.stdout);}catch{return {ok:false,error:'brain_response_invalid'};}
}
function bounded(p){
  return {memories:(p.memories||[]).slice(0,5).map(x=>({id:x.id,text:String(x.text||'').slice(0,500)})),
    insights:(p.insights||[]).slice(0,3),companion:p.companion||null,
    scene_context:(p.scene_context||[]).slice(0,3),persona_context:(p.persona_context||[]).slice(0,3),
    reaction:p.reaction||null,emotion_protocol:p.emotion_protocol||null,
    expression_context:p.expression_context||null,emotion_effect:p.emotion_effect||null,
    current_persona:p.current_persona||null,camera_context:p.camera_context||null,
    emotion_template:p.emotion_template||null,emotion_frame:p.emotion_frame||null,
    plugin_context:p.plugin_context||null};
}
function main(){
  if(process.argv.includes('--help'))return {ok:true,usage:'JSON stdin: phase=context|commit|gate|audit|finish; full48 supplied by the host model',
    boundary:'local validation only; native final is not intercepted'};
  let q;try{q=JSON.parse(readFileSync(0,'utf8'));}catch{return {ok:false,error:'JSON_stdin_required'};}
  if(q.phase==='audit')return auditEntries(workspace,brainRoot,q.turns,getDecision);
  if(typeof q.turnId!=='string'||!q.turnId||q.turnId.length>256||typeof q.text!=='string'||q.text.length>12000)
    return {ok:false,error:'trusted_turnId_and_real_text_required'};
  const phase=q.phase||'finalize',scope='main';
  if(!['context','finalize','commit','gate','finish'].includes(phase))return {ok:false,error:'invalid_phase'};
  if(phase==='finish')return settleDecision(scope,q.turnId,q);
  const actor=q.actor||'user';if(!['user','assistant'].includes(actor))return {ok:false,error:'invalid_actor'};
  const mode=classifyIntent(q.text),hash=createHash('sha256').update(q.text).digest('hex').slice(0,16);
  const debug=/^(?:\[Codex调试\]|［Codex调试］)/.test(q.text.trimStart());
  if(debug)return {ok:true,event:'control_ignored',decision:{mode:'skip',sampled:false,reason:'debug_skip',roll:null},assessment_required:false};
  if(phase==='gate')return entryStatus(workspace,q,getDecision(scope,q.turnId));
  const readingDocuments=phase==='commit'?boundReadings(workspace,q):[];
  if(phase==='commit'){
    const preflight=entryStatus(workspace,q,getDecision(scope,q.turnId));
    if(preflight.missing.includes('context')||preflight.missing.includes('source_conflict'))return {...preflight,error:'native_context_required_before_commit'};
  }
  const finalizing=phase==='finalize'||phase==='commit';
  const cached=finalizing?getDecision(scope,q.turnId):null;
  if(cached?.input_hash&&cached.input_hash!==hash)return {ok:false,error:'input_conflict'};
  const at=q.timestamp??Date.now()/1000;
  if(typeof at!=='number'||!Number.isFinite(at))return {ok:false,error:'invalid_timestamp'};
  const req={op:'prepare',scope:'owner-private',source:actor==='assistant'?'main:proactive':'main:sticker',
    event_id:q.turnId,occurred_at:at,text:q.text,actor,person_id:'owner',sender_type:'human'};
  if(finalizing&&q.emotion_assessment!==undefined)
    req.emotion_assessment={...q.emotion_assessment,format:'full48-v1'};
  if(finalizing)for(const key of ['humor_assessment','meme_updates'])if(q[key]!==undefined)req[key]=q[key];
  const p=runBrain(req);
  let status=p.emotion?.status||(p.ok?'missing':'error');
  const previousEntry=entryStatus(workspace,q,cached);
  if(status==='missing'&&p.reaction&&previousEntry.event_id===p.event?.id&&
     ['updated','unchanged','replayed'].includes(previousEntry.assessment_status))status='replayed';
  if(status==='missing'&&p.reaction&&['updated','unchanged','replayed'].includes(cached?.assessment_status))status='replayed';
  const result={ok:true,turnId:q.turnId,event:p.event||null,emotion:status,mood:p.mood||null,
    context:bounded(p),reaction:p.reaction||null,emotion_protocol:p.emotion_protocol||null,
    humor_updates:p.humor_updates||null,emotion_validation:p.emotion||null,
    assessment_required:phase==='context',protocol:'companion-v2-emotion48'};
  if(phase==='context'){
    result.ok=p.ok===true;result.decision=null;
    if(result.ok&&p.event?.id){const saved=recordEntry(workspace,q,{context_ok:true,context_event_id:p.event.id});
      result.formal_entry=saved.ok?{context_recorded:true,event_id:p.event.id}:saved;result.ok=saved.ok;}
    else{result.ok=false;result.formal_entry={context_recorded:false};}
    return result;
  }
  // A real assessment error stays visible. It does not silently suppress the draw.
  if(!result.mood)result.mood=runBrain({op:'mood',scope:'owner-private'});
  result.decision=decide({scope,turnId:q.turnId,sampling_mode:mode,mood:result.mood,
    event_id:q.turnId,input_hash:hash,assessment_status:status});
  result.image_action=result.decision.sampled&&result.decision.send_status==='not_handed_off'?'select_then_append_after_all_text':'do_not_send';
  result.ok=result.decision.mode!=='error';result.receipt_required=true;
  result.assessment_degraded=!['updated','unchanged','replayed'].includes(status);
  result.pipeline_ok=p.ok===true&&result.ok&&!result.assessment_degraded;
  result.assessment_required=result.assessment_degraded;
  result.repair_hint=result.assessment_degraded?'Fill context.emotion_template; inspect emotion_validation.detail; retry this same turnId/text. Do not reroll or claim emotion was saved.':null;
  if(result.pipeline_ok){const saved=recordEntry(workspace,q,{finalized_ok:true,finalized_event_id:p.event?.id,assessment_status:status});
    if(!saved.ok){if(phase==='commit')result.pipeline_ok=false;result.formal_entry=saved;}}
  if(phase==='commit'){
    result.reading_completion=readingDocuments.map(document_id=>runBrain({op:'plugin_call',scope:'owner-private',
      plugin:'social-reading',action:'completion',document_id}));
    const readingComplete=result.reading_completion.every(x=>x.ok===true&&x.complete===true);
    if(readingDocuments.length){const saved=recordEntry(workspace,q,{reading_documents:readingDocuments,reading_complete:readingComplete});
      if(!saved.ok)result.pipeline_ok=false;}
    result.formal_entry=entryStatus(workspace,q,result.decision);
    result.ready_to_send=result.pipeline_ok&&result.formal_entry.ready_to_send;
    if(!result.ready_to_send){result.ok=false;result.error='main_entry_not_ready';}
  }
  return result;
}
try{const r=main();process.stdout.write(JSON.stringify(r)+'\n');if(!r.ok)process.exitCode=1;}
catch{process.stdout.write(JSON.stringify({ok:false,error:'main_adapter_failed'})+'\n');process.exitCode=1;}
