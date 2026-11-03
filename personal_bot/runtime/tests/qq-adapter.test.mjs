import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,mkdirSync,writeFileSync,readFileSync,existsSync,readdirSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {spawnSync} from 'node:child_process';
import {copyFileSync} from 'node:fs';
import {scopeFor, enhance, enqueueLearning} from '../qq-adapter.mjs';

test('scope is derived from actual target and verified prepared identity',()=>{
  const data={sender_id:'owner',text:'鲸鱼',reply_target:{scope:'group',targetId:'A'}};
  assert.equal(scopeFor(data,{sender_id:'owner',is_master:true}),'qq:group:A');
  data.reply_target={scope:'c2c',targetId:'owner'};
  assert.equal(scopeFor(data,{sender_id:'owner',is_master:true}),'owner-private');
  assert.equal(scopeFor(data,{sender_id:'owner',is_master:false}),'qq:c2c:owner');
  assert.throws(()=>scopeFor(data,{sender_id:'spoof',is_master:true}));
});

test('missing or off core degrades without changing input',()=>{
  const root=mkdtempSync(join(tmpdir(),'muse-adapter-'));
  try{
    const prep={inbox:{sender_id:'u',text:'hello',reply_target:{scope:'c2c',targetId:'u'}},sender_identity:{sender_id:'u'}};
    const before=JSON.stringify(prep);
    const result=enhance(prep,{root});
    assert.equal(result.disabled,true);
    assert.equal(JSON.stringify(prep),before);
  }finally{rmSync(root,{recursive:true,force:true});}
});

test('real Python recall returns only prepared target scope and corrupt DB degrades',()=>{
  const root=mkdtempSync(join(tmpdir(),'muse-adapter-'));
  try{
    copyFileSync(new URL('../brain.py',import.meta.url),join(root,'brain.py'));
    const python=process.platform==='win32'?'python':'python3';
    const run=q=>spawnSync(python,[join(root,'brain.py')],{input:JSON.stringify(q),encoding:'utf8'});
    assert.equal(run({op:'configure',enabled:true}).status,0);
    const cfg=JSON.parse(readFileSync(join(root,'config.json'),'utf8'));
    cfg.qq_enabled=true; writeFileSync(join(root,'config.json'),JSON.stringify(cfg));
    assert.equal(run({op:'remember',scope:'owner-private',text:'主人鲸鱼私密测试',source:'fixture:u',event_id:'e'}).status,0);
    const prep={inbox:{sender_id:'u',text:'鲸鱼',reply_target:{scope:'group',targetId:'A'}},sender_identity:{sender_id:'u',is_master:true}};
    assert.equal(enhance(prep,{root,python}).memories.length,0);
    prep.inbox.reply_target={scope:'c2c',targetId:'u'};
    assert.equal(enhance(prep,{root,python}).memories.length,1);
    writeFileSync(join(root,'data','brain.sqlite'),'corrupt');
    assert.equal(enhance(prep,{root,python}).degraded,true);
  }finally{rmSync(root,{recursive:true,force:true});}
});

test('learning queue is an idempotent source reference without plaintext',()=>{
  const root=mkdtempSync(join(tmpdir(),'muse-adapter-'));
  const bridge=join(root,'bridge');
  writeFileSync(join(root,'config.json'),JSON.stringify({enabled:true,qq_enabled:true,modules:{input:true}}));
  const processed=join(bridge,'inbox','processed');
  mkdirSync(processed,{recursive:true});
  const file=join(processed,'event.json');
  writeFileSync(file,JSON.stringify({id:'event-real',text:'PRIVATE-TEST',sender_id:'u',reply_target:{scope:'c2c',targetId:'u'}}));
  try{
    const a=enqueueLearning(bridge,'event.json',{root});
    const b=enqueueLearning(bridge,'event.json',{root});
    assert.equal(a.ok,true); assert.equal(b.ok,true);
    const files=readdirSync(join(root,'state','learning'));
    assert.equal(files.length,1);
    const record=readFileSync(join(root,'state','learning',files[0]),'utf8');
    assert.ok(!record.includes('PRIVATE-TEST'));
    assert.equal(JSON.parse(record).event_id,'event-real');
    assert.equal(enqueueLearning(bridge,'../escape.json',{root}).ok,false);
  }finally{rmSync(root,{recursive:true,force:true});}
});

test('source event metadata preserves actual bridge timestamp inside existing prepare call',async()=>{
  const {prepareRequest}=await import('../qq-adapter.mjs');
  const r=prepareRequest({id:'event1',ts:1700000000123,text:'谢谢',sender_id:'u'}, {record:{type:'bot'}}, 'owner-private');
  assert.equal(r.event_id,'event1');
  assert.equal(r.occurred_at,1700000000.123);
  assert.equal(r.actor,'bot');
  assert.equal(r.source,'qq:bridge');
  const missing=prepareRequest({text:'hello'}, {}, 'owner-private');
  assert.equal(missing.event_id,undefined);
  assert.equal(missing.occurred_at,undefined);
});

test('packaged code and private data use separate roots',()=>{
  const root=mkdtempSync(join(tmpdir(),'personal-bot-data-'));
  const python=process.platform==='win32'?'python':'python3';
  const codeRoot=new URL('..',import.meta.url).pathname.replace(/^\/([A-Za-z]:)/,'$1');
  try{
    writeFileSync(join(root,'config.json'),JSON.stringify({enabled:true,epoch:0,qq_enabled:true,modules:{memory:true,mood:true,style:true,input:true}}));
    const prep={inbox:{id:'separate',ts:Date.now(),sender_id:'u',text:'hello',reply_target:{scope:'c2c',targetId:'u'}},sender_identity:{sender_id:'u'}};
    const r=enhance(prep,{root,python});
    assert.equal(r.ok,true);assert.equal(existsSync(join(root,'brain.py')),false);
  }finally{rmSync(root,{recursive:true,force:true});}
});
