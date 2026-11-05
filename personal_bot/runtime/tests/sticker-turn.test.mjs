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
}));
