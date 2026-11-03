import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,copyFileSync,readdirSync,rmSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
import {enqueueLearning} from '../qq-adapter.mjs';
import {drainLearning} from '../learn.mjs';

test('learning consumes source with prepared identity and never promotes statement to confirmed fact',()=>{
 const root=mkdtempSync(join(tmpdir(),'muse-learn-'));
 try{
  const bridge=join(root,'bridge'),processed=join(bridge,'inbox','processed');
  mkdirSync(processed,{recursive:true});
  copyFileSync(new URL('../brain.py',import.meta.url),join(root,'brain.py'));
  const python=process.platform==='win32'?'python':'python3';
  const run=q=>spawnSync(python,[join(root,'brain.py')],{input:JSON.stringify(q),encoding:'utf8'});
  run({op:'configure',enabled:true});
  const cfg=JSON.parse(readFileSync(join(root,'config.json'),'utf8'));cfg.qq_enabled=true;
  writeFileSync(join(root,'config.json'),JSON.stringify(cfg));
  writeFileSync(join(processed,'e.json'),JSON.stringify({id:'e1',ts:1700000000123,text:'主人说喜欢游泳',sender_id:'owner',reply_target:{scope:'c2c',targetId:'owner'}}));
  // A fixture adapter with the actual prepare output contract. Production helper is
  // tested separately on Muse VM; this isn't claimed as a production-chain test.
  writeFileSync(join(bridge,'qq-prepare.mjs'),`import fs from 'node:fs';const inbox=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));console.log(JSON.stringify({inbox,sender_identity:{sender_id:inbox.sender_id,is_master:true,record:null}}));`);
  assert.equal(enqueueLearning(bridge,'e.json',{root}).ok,true);
  for(let i=0;i<20;i++){
   writeFileSync(join(root,'state','learning','0'.repeat(62)+i.toString(16).padStart(2,'0')+'.json'),JSON.stringify({event_id:'broken',source_file:join(root,'missing')}));
  }
  const quarantined=drainLearning({root,bridgeDir:bridge,python});
  assert.equal(quarantined.failed,20);
  assert.equal(readdirSync(join(root,'state','learning-failed')).length,20);
  const r=drainLearning({root,bridgeDir:bridge,python});
  assert.equal(r.learned,1);
  const recalled=JSON.parse(run({op:'recall',scope:'owner-private',text:'游泳'}).stdout).memories;
  assert.equal(recalled[0].evidence,'observed');
  assert.equal(recalled[0].occurred_at,1700000000.123);
  assert.equal(recalled[0].kind,'episode');
  assert.equal(drainLearning({root,bridgeDir:bridge,python}).learned,0);
  assert.equal(readdirSync(join(root,'state','learning')).length,0);
 }finally{rmSync(root,{recursive:true,force:true});}
});
