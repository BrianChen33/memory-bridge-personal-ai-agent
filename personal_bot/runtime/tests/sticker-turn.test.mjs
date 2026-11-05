import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {decide,setPaths,loadDecision,saveDecision,settleDecision} from '../sticker_decision.mjs';
const adapter=fileURLToPath(new URL('../sticker_main.mjs',import.meta.url));
function fixture(body){
 const root=mkdtempSync(join(tmpdir(),'companion-turn-isolated-'));
 try{
  mkdirSync(join(root,'stickers'));writeFileSync(join(root,'stickers/config.json'),JSON.stringify({enabled:true,policy:{base_probability:.4,max_probability:1}}));
  setPaths({configPath:join(root,'stickers/config.json'),decisionDir:join(root,'stickers/decisions')});body(root);
 }finally{rmSync(root,{recursive:true,force:true});}
}
test('every topic uses auto; retries after an hour preserve the exact draw',()=>fixture(()=>{
 let draws=0;
 for(const topic of ['email','task','interview','reminder']){
  const q={scope:'main',turnId:topic,topic,input_hash:topic,randomFn:()=>{draws++;return .2;},assessment_status:'invalid'};
  const one=decide(q);assert.equal(one.sampled,true);assert.equal(one.probability,.4);assert.equal(one.degraded,true);
  const old=loadDecision('main',topic);saveDecision('main',topic,{...old,decided_at:Date.now()-7200000});
  assert.equal(decide(q).roll,.2);
 }
 assert.equal(draws,4);
}));

test('native two-phase entry validates original source, gates commits and audits without replaying',()=>fixture(root=>{
 const python=process.platform==='win32'?'python':'python3';
 const repository=fileURLToPath(new URL('../../../',import.meta.url));
 const brain=join(root,'muse-brain');
 const env={...process.env,PYTHONUTF8:'1',PYTHONPATH:repository,STICKER_PYTHON:python,STICKER_BRAIN_ROOT:brain};
 const init=spawnSync(python,['-c','from personal_bot import deploy;from pathlib import Path;import sys;r=Path(sys.argv[1]);deploy.init(r);deploy.enable(r,list(deploy.DEFAULT_FEATURES))',brain],{encoding:'utf8',env});
 assert.equal(init.status,0,init.stdout+init.stderr);
 writeFileSync(join(brain,'brain.py'),'import runpy,sys\nfrom personal_bot import deploy\nsys.path.insert(0,str(deploy.RUNTIME))\nrunpy.run_path(str(deploy.RUNTIME / "brain.py"),run_name="__main__")\n');
 const nativeAdapter=fileURLToPath(new URL('../main_native_entry.mjs',import.meta.url));
 const run=q=>{const p=spawnSync(process.execPath,[nativeAdapter,'--root',root,'--chat-id','fixture:owner-main'],{input:JSON.stringify(q),encoding:'utf8',env});return {code:p.status,...JSON.parse(p.stdout)};};
 const text='  Synthetic original\nsecond line is intact.  ';
 const native={chat_id:'fixture:owner-main',page:{order:'newest_first',has_more:true},turns:[{id:'fixture:native-turn',items:[
  {role:'assistant',content:'This is not the owner input.',seq:10,occurred_at_ms:1000000},
  {role:'user',content:text,seq:11,occurred_at_ms:1001000}]}]};
 const request={native_response:native};
 assert.notEqual(run({...request,phase:'commit'}).code,0);
 assert.notEqual(run({...request,native_response:{...native,chat_id:'fixture:other'}}).code,0);
 const context=run({...request,phase:'context'});assert.equal(context.code,0);
 assert.equal(context.native_source.input_sha256,createHash('sha256').update(text).digest('hex'));
 assert.equal(context.native_source.seq,11);
 assert.equal(run({...request,phase:'gate'}).ready_to_send,false);
 const bad=run({...request,phase:'commit',emotion_assessment:{version:99}});
 assert.notEqual(bad.code,0);assert.equal(bad.ready_to_send,false);
 const valid=run({...request,phase:'commit',emotion_assessment:context.context.emotion_template});
 assert.equal(valid.code,0);assert.equal(valid.ready_to_send,true);assert.equal(valid.decision.roll,bad.decision.roll);
 assert.equal(run({...request,phase:'commit'}).ready_to_send,true);
 assert.equal(run({...request,phase:'gate'}).ready_to_send,true);
 const appended=structuredClone(native);appended.turns[0].items.push({role:'user',content:'A later owner message.',seq:13,occurred_at_ms:1003000});
 const stable=run({phase:'audit',native_response:appended});
 assert.equal(stable.audit.complete,1);assert.equal(stable.audit.gaps.length,1);
 assert.equal(run({phase:'commit',native_response:appended,target_seq:11}).error,'new_owner_turn_requires_context');
 const blank=structuredClone(native);blank.turns[0].items.push({role:'user',content:' \n ',seq:14,occurred_at_ms:1004000});
 assert.equal(run({phase:'context',native_response:blank}).event,'empty_user_input_ignored');
 assert.equal(run({phase:'audit',native_response:blank}).audit.complete,1);
 assert.equal(run({phase:'gate',native_response:blank,target_seq:11}).ready_to_send,true);
 const media=structuredClone(blank);media.turns[0].items[2].attachments=['fixture-image'];
 assert.equal(run({phase:'context',native_response:media}).error,'native_empty_media_or_unknown_payload_requires_adapter');
 const reading=run({...request,phase:'commit',reading_documents:['not-observed']});
 assert.equal(reading.ready_to_send,false);assert.notEqual(reading.code,0);
 assert.equal(run({...request,phase:'commit'}).ready_to_send,false);
 native.turns.push({id:'fixture:unprocessed',items:[{role:'user',content:'Another real-shaped fixture.',seq:12,occurred_at_ms:1002000}]});
 const audit=run({...request,phase:'audit'});assert.equal(audit.code,0);
 assert.equal(audit.audit.checked,2);assert.equal(audit.audit.gaps.length,2);
 assert.equal(audit.audit.repairs_performed,false);
 assert.equal(readFileSync(join(brain,'state/formal-entry-health.json'),'utf8').includes('Another real-shaped'),false);
 const malformed=structuredClone(native);malformed.turns[1].items[0].content=['unsupported'];
 assert.notEqual(run({native_response:malformed,phase:'context'}).code,0);
}));
test('direct and skip have receipts without rolls; unknown handoff is terminal',()=>fixture(()=>{
 const rng=()=>{throw Error('must not draw');};
 for(const mode of ['direct','skip']){
  const q={scope:'main',turnId:mode,sampling_mode:mode,randomFn:rng};
  const a=decide(q);assert.equal(a.roll,null);assert.equal(a.sampled,mode==='direct');assert.equal(decide(q).cached,true);
 }
 assert.equal(settleDecision('main','direct',{outcome:'accepted',text_finished:false}).ok,false);
 assert.equal(settleDecision('main','direct',{outcome:'unknown',text_finished:true}).send_status,'unknown');
 assert.equal(settleDecision('main','direct',{outcome:'accepted',text_finished:true}).send_status,'unknown');
}));
test('a changed input cannot reuse a turn or consume another draw',()=>fixture(()=>{
 decide({scope:'main',turnId:'same',input_hash:'first',randomFn:()=>.8});
 assert.equal(decide({scope:'main',turnId:'same',input_hash:'changed',randomFn:()=>{throw Error();}}).reason,'input_conflict');
}));
test('main adapter explicit context and degraded finalize use a mock brain only',()=>fixture(root=>{
 const brain=join(root,'muse-brain');mkdirSync(brain);
 writeFileSync(join(brain,'brain.py'),`import json,sys\nq=json.load(sys.stdin)\nprint(json.dumps({'ok':True,'event':{'id':1},'emotion':{'status':'invalid' if 'emotion_assessment' in q else 'missing'},'mood':{'ok':True,'p':0,'a':0,'d':0,'labels':[]},'memories':[],'insights':[]}))\n`);
 writeFileSync(join(root,'stickers/config.json'),JSON.stringify({enabled:true,policy:{base_probability:1,max_probability:1}}));
 const run=q=>{
  const p=spawnSync(process.execPath,[adapter,'--root',root],{input:JSON.stringify(q),encoding:'utf8',env:{...process.env,STICKER_PYTHON:process.platform==='win32'?'python':'python3'}});
  assert.equal(p.status,0,p.stdout+p.stderr);return JSON.parse(p.stdout);
 };
 const q={turnId:'real-fixture-id',text:'synthetic email task',timestamp:100};
 assert.equal(run({...q,phase:'context'}).decision,null);
 const one=run({...q,emotion_assessment:{version:99}});
 assert.equal(one.assessment_degraded,true);assert.equal(one.decision.sampled,true);assert.equal(one.emotion,'invalid');
 assert.equal(run(q).decision.roll,one.decision.roll);
 assert.equal(run({...q,phase:'finish',outcome:'unknown',text_finished:true,asset_id:'fixture'}).send_status,'unknown');
 assert.equal(run({...q,phase:'finish',outcome:'accepted',text_finished:true}).send_status,'unknown');
}));

test('main adapter reports persisted learning and invalid sub-operations separately',()=>fixture(root=>{
 const python=process.platform==='win32'?'python':'python3';
 const repository=fileURLToPath(new URL('../../../',import.meta.url));
 const brain=join(root,'muse-brain');
 const env={...process.env,PYTHONUTF8:'1',PYTHONPATH:repository,STICKER_PYTHON:python,STICKER_BRAIN_ROOT:brain};
 const init=spawnSync(python,['-c','from personal_bot import deploy; from pathlib import Path; import sys; root=Path(sys.argv[1]); deploy.init(root); deploy.enable(root, list(deploy.DEFAULT_FEATURES))',brain],{encoding:'utf8',env});
 assert.equal(init.status,0,init.stdout+init.stderr);
 // The packaged deployer separates code/state; emulate the host's CLI path
 // while executing the real packaged runtime, not a fake learning response.
 writeFileSync(join(brain,'brain.py'),'import runpy,sys\nfrom personal_bot import deploy\nsys.path.insert(0,str(deploy.RUNTIME))\nrunpy.run_path(str(deploy.RUNTIME / "brain.py"), run_name="__main__")\n');
 const q={turnId:'isolated-teaching',text:'Synthetic teaching: fixture-only means a shared joke. 不要发表情包',
  phase:'finalize',timestamp:Date.now()/1000,meme_updates:[
   {title:'Isolated shared joke',meaning:'A synthetic shared joke',aliases:['fixture-only'],basis:'explained',confidence:.9},
   {title:3}
  ]};
 const result=spawnSync(process.execPath,[adapter,'--root',root],{input:JSON.stringify(q),encoding:'utf8',env});
 assert.equal(result.status,0,result.stdout+result.stderr);
 const response=JSON.parse(result.stdout);
 assert.equal(response.humor_updates?.learning?.[0]?.status,'active');
 assert.equal(response.humor_updates.learning[1].ok,false);
 assert.equal(response.humor_updates.learning[1].status,'invalid');
 const search=spawnSync(python,[join(brain,'brain.py'),'--root',brain],{
  input:JSON.stringify({op:'meme_search',scope:'owner-private',text:'fixture-only'}),encoding:'utf8',env});
 assert.equal(search.status,0,search.stdout+search.stderr);
 assert.equal(JSON.parse(search.stdout).items[0].title,'Isolated shared joke');
 const run=input=>{
  const p=spawnSync(process.execPath,[adapter,'--root',root],{input:JSON.stringify(input),encoding:'utf8',env});
  assert.equal(p.status,0,p.stdout+p.stderr);return JSON.parse(p.stdout);
 };
 const context=run({...q,phase:'context'});
 assert.equal(Object.keys(context.context.emotion_template.emotion_deltas).length,48);
 const bad=run({...q,emotion_assessment:{version:2,additional_labels:[],appraisal:{event:'feedback',object:'self'}}});
 assert.equal(bad.pipeline_ok,false);
 assert.equal(bad.assessment_required,true);
 assert.match(bad.emotion_validation.detail,/additional_labels/);
 const full=context.context.emotion_template;full.emotion_deltas['好奇']=.01;
 const legacy=run({...q,turnId:'legacy-without-context',emotion_assessment:full});
 assert.equal(legacy.pipeline_ok,true);
 const valid=run({...q,emotion_assessment:full});
 assert.equal(valid.pipeline_ok,true);
 assert.equal(valid.assessment_required,false);
 assert.equal(valid.emotion,'updated');
 assert.equal(valid.context.emotion_effect.applied_labels.length,48);
 assert.equal(valid.decision.roll,response.decision.roll);
 assert.equal(run({...q,emotion_assessment:full}).emotion,'replayed');
}));
