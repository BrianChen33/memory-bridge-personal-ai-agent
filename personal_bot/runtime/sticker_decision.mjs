// One immutable decision per trusted turn. All topics participate.
import {readFileSync,writeFileSync,existsSync,mkdirSync,renameSync,unlinkSync,openSync,closeSync} from 'node:fs';
import {join,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {sharedIntensity,probabilityFromIntensity} from './sticker_emotion.mjs';
const HERE=dirname(fileURLToPath(import.meta.url));
let CONFIG_PATH=join(HERE,'..','config.json'),DECISION_DIR=join(HERE,'..','decisions');
export function setPaths({configPath,decisionDir}) {if(configPath) CONFIG_PATH=configPath;if(decisionDir) DECISION_DIR=decisionDir;}
export function getPaths(){return {configPath:CONFIG_PATH,decisionDir:DECISION_DIR};}
export function validateProbability(p){return typeof p==='number'&&Number.isFinite(p)&&p>=0&&p<=1;}
export function validateScopeTurn(scope,turnId){return {ok:typeof scope==='string'&&scope.length>0&&scope.length<=160&&typeof turnId==='string'&&turnId.length>0&&turnId.length<=256&&scope!=='undefined'&&turnId!=='undefined'};}
function pathFor(scope,id){return join(DECISION_DIR,createHash('sha256').update(`${scope}:${id}`).digest('hex').slice(0,16)+'.json');}
export function loadConfig(){
  try{
    if(process.env.STICKERS_ENABLED==='0') return {enabled:false,_source:'env'};
    const cfg=JSON.parse(readFileSync(CONFIG_PATH,'utf8'));
    const b=cfg.policy?.base_probability??.40,m=cfg.policy?.max_probability??1;
    if(!validateProbability(b)||!validateProbability(m)||b>m||typeof (cfg.enabled??true)!=='boolean') throw Error();
    return {enabled:cfg.enabled!==false,base_probability:b,max_probability:m,_source:'config'};
  }catch{return {enabled:false,_source:'error',_error:'config_unavailable_or_invalid'};}
}
export function loadDecision(scope,id){
  if(!validateScopeTurn(scope,id).ok) return null;
  try{return JSON.parse(readFileSync(pathFor(scope,id),'utf8'));}catch{return null;}
}
export const getDecision=loadDecision;
export function hasDecision(scope,id){return loadDecision(scope,id)!==null;}
export function saveDecision(scope,id,value){
  if(!validateScopeTurn(scope,id).ok) return {ok:false,error:'invalid_turn'};
  try{
    mkdirSync(DECISION_DIR,{recursive:true});
    const target=pathFor(scope,id),temp=target+'.'+process.pid+'.tmp';
    const record={scope,turn_id:id,decided_at:Date.now(),...value};
    writeFileSync(temp,JSON.stringify(record),{mode:0o600});renameSync(temp,target);
    return {ok:true,record};
  }catch{return {ok:false,error:'decision_persist_failed'};}
}
export function removeDecision(scope,id){
  if(!validateScopeTurn(scope,id).ok)return false;
  try{unlinkSync(pathFor(scope,id));return true;}catch{return false;}
}
export function decide(opts){
  const {scope,turnId,mood=null,globalMood=null,event_id=null,input_hash=null,assessment_status='missing',randomFn=Math.random}=opts;
  if(!validateScopeTurn(scope,turnId).ok)return {sampled:false,mode:'error',reason:'invalid_turn',probability:null};
  const cached=loadDecision(scope,turnId);
  if(cached){
    if(cached.input_hash&&input_hash&&cached.input_hash!==input_hash)return {sampled:false,mode:'error',reason:'input_conflict',probability:null};
    return {...cached,cached:true};
  }
  mkdirSync(DECISION_DIR,{recursive:true});
  const lock=pathFor(scope,turnId)+'.lock';let fd;
  try{fd=openSync(lock,'wx',0o600);}catch{return {sampled:false,mode:'error',reason:'decision_busy_or_storage_error',probability:null};}
  try{
    const again=loadDecision(scope,turnId);if(again)return {...again,cached:true};
    const cfg=loadConfig();let mode=opts.sampling_mode??(opts.isExplicitRequest?'direct':'auto');
    if(!['direct','skip','auto'].includes(mode))return {sampled:false,mode:'error',reason:'invalid_sampling_mode',probability:null};
    let roll=null,probability=null,sampled=false,reason;
    if(cfg._error){mode='error';reason=cfg._error;}
    else if(!cfg.enabled){mode='disabled';reason='disabled_by_config';}
    else if(mode==='skip')reason='skip_request';
    else if(mode==='direct'){sampled=true;reason='direct_request';}
    else{
      const intensity=sharedIntensity(globalMood,mood);
      probability=probabilityFromIntensity(intensity.intensity,cfg);
      roll=randomFn();
      if(typeof roll!=='number'||!Number.isFinite(roll)||roll<0||roll>=1) return {sampled:false,mode:'error',reason:'invalid_random_value',probability:null};
      sampled=roll<probability;reason=intensity.available?'emotion_intensity':'degraded_to_base';
    }
    const value={sampled,reason,probability,roll,mode,event_id,input_hash,assessment_status,
      degraded:!['updated','unchanged','replayed'].includes(assessment_status),requires_context_match:false,
      order:'all_text_then_image',send_status:'not_handed_off'};
    const saved=saveDecision(scope,turnId,value);
    return saved.ok?saved.record:{sampled:false,mode:'error',reason:saved.error,probability:null};
  }finally{closeSync(fd);try{unlinkSync(lock);}catch{}}
}
export function settleDecision(scope,id,{outcome,text_finished,asset_id=null}){
  const previous=loadDecision(scope,id);
  if(!previous)return {ok:false,error:'decision_required'};
  if(previous.send_status&&previous.send_status!=='not_handed_off')return {ok:true,replayed:true,send_status:previous.send_status};
  if(text_finished!==true||!['accepted','failed','unknown','text_only'].includes(outcome))return {ok:false,error:'invalid_handoff'};
  if(!previous.sampled&&outcome!=='text_only')return {ok:false,error:'no_image_planned'};
  const result=saveDecision(scope,id,{...previous,send_status:outcome,asset_id,settled_at:Date.now()});
  return result.ok?{ok:true,send_status:outcome}:result;
}
