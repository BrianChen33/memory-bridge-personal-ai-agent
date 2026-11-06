// Local indexed media only. No draw, network, sender, or fabricated delivery.
import {readFileSync,writeFileSync,mkdirSync,renameSync,existsSync,lstatSync,openSync,closeSync,unlinkSync} from 'node:fs';
import {join} from 'node:path';
import {createHash,randomInt,randomUUID} from 'node:crypto';
import {setPaths,getDecision,saveDecision,settleDecision} from './sticker_decision.mjs';

const WINDOW=3600000;
function acquire(path){
  try{const fd=openSync(path,'wx',0o600);writeFileSync(fd,JSON.stringify({pid:process.pid,created:Date.now()}));return fd;}
  catch{
    const previous=read(path,null);
    if(!previous||!Number.isSafeInteger(previous.pid)||previous.pid<=0)return null;
    try{process.kill(previous.pid,0);return null;}
    catch(error){if(error.code!=='ESRCH')return null;}
    // Only a dead owner's lock can be retired. A slow live process keeps it.
    try{unlinkSync(path);}catch{return null;}
    try{const fd=openSync(path,'wx',0o600);writeFileSync(fd,JSON.stringify({pid:process.pid,created:Date.now()}));return fd;}catch{return null;}
  }
}
function read(path,fallback){try{return JSON.parse(readFileSync(path,'utf8'));}catch{return fallback;}}
function write(path,value){
  if(existsSync(path)&&lstatSync(path).isSymbolicLink())throw Error('media_state_symlink_refused');
  const temp=path+'.'+randomUUID()+'.tmp';
  writeFileSync(temp,JSON.stringify(value),{mode:0o600,flag:'wx'});renameSync(temp,path);
}
function setup(root){
  const dir=join(root,'stickers');mkdirSync(dir,{recursive:true});
  setPaths({configPath:join(dir,'config.json'),decisionDir:join(dir,'decisions')});
  return dir;
}
function localFile(dir,item){
  if(!/^[a-f0-9]{12}$/.test(item.hash))return null;
  const path=join(dir,'assets',item.hash+'.gif');
  try{
    if(lstatSync(path).isSymbolicLink()||lstatSync(path).size>8000000)return null;
    const bytes=readFileSync(path),magic=bytes.subarray(0,6).toString('ascii');
    return ['GIF87a','GIF89a'].includes(magic)&&createHash('sha1').update(bytes).digest('hex').startsWith(item.hash)?path:null;
  }catch{return null;}
}
export function prepareMedia(root,turnId,{query='',emotion=''}={}){
  const dir=setup(root),decision=getDecision('main',turnId);
  if(!decision)return {ok:false,error:'decision_required'};
  if(!decision.sampled)return {ok:true,status:'not_sampled'};
  if(decision.send_status!=='not_handed_off')return {ok:true,status:'already_settled',send_status:decision.send_status};
  const index=read(join(dir,'meta','nekowhale.json'),{});
  if(!Array.isArray(index.stickers))return {ok:false,status:'media_unavailable',error:'local_index_required',sampled:true};
  if(decision.asset_id){
    const item=index.stickers.find(item=>item.id===decision.asset_id),path=item&&localFile(dir,item);
    return path?{ok:true,status:'prepared',replayed:true,asset_id:item.id,path,order:'all_text_then_image',delivery:'unconfirmed'}:
      {ok:false,status:'media_unavailable',error:'prepared_asset_unavailable',sampled:true};
  }
  const lock=join(dir,'reply-media.lock'),fd=acquire(lock);
  if(fd===null)return {ok:false,status:'media_unavailable',error:'media_selection_busy',sampled:true};
  try{
    // Another local caller may have selected while we waited. Never select twice.
    const fresh=getDecision('main',turnId);
    if(fresh.asset_id)return prepareExisting(dir,index,fresh);
    const now=Date.now(),sent=read(join(dir,'recently_sent.json'),{}),reserved=read(join(dir,'recently_reserved.json'),{});
    const blocked=id=>Number.isFinite(sent[id])&&now-sent[id]<WINDOW||
      reserved[id]&&reserved[id].turn!==turnId&&now-reserved[id].at<WINDOW;
    const words=String(query).slice(0,300).split(/[\s，。！？,.!?]+/u).filter(Boolean).slice(0,16);
    const candidates=index.stickers.filter(item=>typeof item.id==='string'&&!blocked(item.id)).map(item=>({item,
      score:(item.emotion===emotion?10:0)+words.reduce((score,word)=>score+
        (String([item.text,...(item.tags||[]),item.use,item.desc].join(' ')).includes(word)?2:0),0)}));
    candidates.sort((a,b)=>b.score-a.score);
    // Loose matching is deliberate: a sampled round does not need a perfect fit.
    const local=[];
    for(const candidate of candidates){const path=localFile(dir,candidate.item);if(path)local.push({...candidate,path});if(local.length===10)break;}
    if(!local.length)return {ok:false,status:'media_unavailable',error:'no_eligible_local_asset',sampled:true};
    const chosen=local[randomInt(local.length)];
    const saved=saveDecision('main',turnId,{...fresh,asset_id:chosen.item.id,media_prepared_at:now});
    if(!saved.ok)return saved;
    for(const [id,entry] of Object.entries(reserved))if(!entry||now-entry.at>=WINDOW)delete reserved[id];
    reserved[chosen.item.id]={at:now,turn:turnId};write(join(dir,'recently_reserved.json'),reserved);
    // Compatibility avoidance ledger: this timestamp is a conservative reservation,
    // not a delivery receipt. Sidecar and decision remain explicitly unconfirmed.
    sent[chosen.item.id]=now;write(join(dir,'recently_sent.json'),sent);
    return {ok:true,status:'prepared',asset_id:chosen.item.id,path:chosen.path,candidates:local.length,
      order:'all_text_then_image',delivery:'unconfirmed',boundary:'local attachment prepared; neither sent nor accepted'};
  }finally{closeSync(fd);unlinkSync(lock);}
}
function prepareExisting(dir,index,decision){
  const item=index.stickers.find(item=>item.id===decision.asset_id),path=item&&localFile(dir,item);
  return path?{ok:true,status:'prepared',replayed:true,asset_id:item.id,path,delivery:'unconfirmed',order:'all_text_then_image'}:
    {ok:false,status:'media_unavailable',error:'prepared_asset_unavailable',sampled:true};
}
export function finishMedia(root,turnId,q){
  const dir=setup(root),decision=getDecision('main',turnId);
  if(!decision)return {ok:false,error:'decision_required'};
  if(typeof q.receipt!=='string'||!q.receipt.trim()||q.receipt.length>1000)
    return {ok:false,error:'actual_native_attempt_or_delivery_receipt_required'};
  if(q.asset_id!==undefined&&q.asset_id!==decision.asset_id)return {ok:false,error:'prepared_asset_binding_required'};
  if(['accepted','unknown'].includes(q.outcome)&&!decision.asset_id)return {ok:false,error:'prepared_asset_required'};
  const settled=settleDecision('main',turnId,{outcome:q.outcome,text_finished:q.text_finished,asset_id:decision.asset_id||null});
  if(!settled.ok)return settled;
  if(decision.asset_id&&['accepted','unknown'].includes(settled.send_status)){
    const sent=read(join(dir,'recently_sent.json'),{});
    // Replays keep the original attempt time, rather than extending the window.
    sent[decision.asset_id]=Math.max(Number(sent[decision.asset_id])||0,getDecision('main',turnId).settled_at);
    write(join(dir,'recently_sent.json'),sent);
  }else if(decision.asset_id&&['failed','text_only'].includes(settled.send_status)){
    const sent=read(join(dir,'recently_sent.json'),{}),reserved=read(join(dir,'recently_reserved.json'),{});
    if(reserved[decision.asset_id]?.turn===turnId){
      if(sent[decision.asset_id]===reserved[decision.asset_id].at)delete sent[decision.asset_id];
      delete reserved[decision.asset_id];
      write(join(dir,'recently_sent.json'),sent);write(join(dir,'recently_reserved.json'),reserved);
    }
  }
  return {...settled,delivery:QDelivery(settled.send_status),boundary:'accepted is host-reported, unknown never retries automatically'};
}
const QDelivery=status=>status==='accepted'?'host_reported_accepted':status;
