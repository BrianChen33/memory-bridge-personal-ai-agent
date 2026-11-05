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
  let q;try{q=JSON.parse(readFileSync(0,'utf8'));}catch{return {ok:false,error:'JSON_stdin_required'};}
  if(typeof q.turnId!=='string'||!q.turnId||q.turnId.length>256||typeof q.text!=='string'||q.text.length>12000)
    return {ok:false,error:'trusted_turnId_and_real_text_required'};
  const phase=q.phase||'finalize',scope='main';
  if(!['context','finalize','finish'].includes(phase))return {ok:false,error:'invalid_phase'};
  if(phase==='finish')return settleDecision(scope,q.turnId,q);
  const actor=q.actor||'user';if(!['user','assistant'].includes(actor))return {ok:false,error:'invalid_actor'};
  const mode=classifyIntent(q.text),hash=createHash('sha256').update(q.text).digest('hex').slice(0,16);
  const debug=/^(?:\[Codex调试\]|［Codex调试］)/.test(q.text.trimStart());
  if(debug)return {ok:true,event:'control_ignored',decision:{mode:'skip',sampled:false,reason:'debug_skip',roll:null},assessment_required:false};
  const cached=phase==='finalize'?getDecision(scope,q.turnId):null;
  if(cached?.input_hash&&cached.input_hash!==hash)return {ok:false,error:'input_conflict'};
  const at=q.timestamp??Date.now()/1000;
  if(typeof at!=='number'||!Number.isFinite(at))return {ok:false,error:'invalid_timestamp'};
  const req={op:'prepare',scope:'owner-private',source:actor==='assistant'?'main:proactive':'main:sticker',
    event_id:q.turnId,occurred_at:at,text:q.text,actor,person_id:'owner',sender_type:'human'};
  if(phase==='finalize'&&q.emotion_assessment!==undefined)
    req.emotion_assessment={...q.emotion_assessment,format:'full48-v1'};
  if(phase==='finalize')for(const key of ['humor_assessment','meme_updates'])if(q[key]!==undefined)req[key]=q[key];
  const p=runBrain(req);
  let status=p.emotion?.status||(p.ok?'missing':'error');
  if(status==='missing'&&p.reaction&&['updated','unchanged','replayed'].includes(cached?.assessment_status))status='replayed';
  const result={ok:true,turnId:q.turnId,event:p.event||null,emotion:status,mood:p.mood||null,
    context:bounded(p),reaction:p.reaction||null,emotion_protocol:p.emotion_protocol||null,
    humor_updates:p.humor_updates||null,emotion_validation:p.emotion||null,
    assessment_required:phase==='context',protocol:'companion-v2-emotion48'};
  if(phase==='context'){result.ok=p.ok===true;result.decision=null;return result;}
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
  return result;
}
try{const r=main();process.stdout.write(JSON.stringify(r)+'\n');if(!r.ok)process.exitCode=1;}
catch{process.stdout.write(JSON.stringify({ok:false,error:'main_adapter_failed'})+'\n');process.exitCode=1;}
