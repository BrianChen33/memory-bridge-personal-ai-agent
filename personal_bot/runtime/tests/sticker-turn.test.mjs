import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
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
