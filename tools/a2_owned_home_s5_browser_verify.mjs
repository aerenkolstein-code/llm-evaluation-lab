#!/usr/bin/env node
import vm from 'node:vm';

const url = process.argv[2];
if (!url) throw new Error('URL required');
const origin = new URL(url).origin;
const html = await (await fetch(origin + '/human')).text();
const script = await (await fetch(origin + '/human.js')).text();
if (!html.includes('Human decision')) throw new Error('human page missing');

const backing = new Map();
const writes = [];
const calls = [];
const localStorage = {
  getItem(k){ return backing.has(k) ? backing.get(k) : null; },
  setItem(k,v){ writes.push([String(k),String(v)]); backing.set(String(k),String(v)); },
  removeItem(k){ backing.delete(String(k)); }
};
let uuidNo=1;
function uuid(){
  const tail=String(uuidNo++).padStart(12,'0');
  return '00000000-0000-4000-8000-' + tail;
}
function makeElements(){
  const ids=['create','form','message','submit','resume','cancel','next','status','reply'];
  const e={};
  for(const id of ids) e[id]={
    id,value:'',textContent:'',hidden:false,disabled:false,listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}
  };
  return e;
}
const realFetch=globalThis.fetch;
async function sandboxFetch(path,opts={}){
  const target=new URL(path,origin).toString();
  const body=opts.body ? JSON.parse(opts.body) : null;
  const response=await realFetch(target,opts);
  let data=null; try { data=await response.clone().json(); } catch(_){}
  calls.push({path:new URL(target).pathname,body,data});
  return response;
}
function makeSandbox(elements){
  return {
    document:{getElementById:id=>elements[id]},localStorage,location:{origin},
    crypto:{randomUUID:uuid},fetch:sandboxFetch,addEventListener:()=>{},console,JSON,RegExp,Number,Date,
    setTimeout,clearTimeout,Promise,Error
  };
}
function start(label){
  const elements=makeElements(); const s=makeSandbox(elements); vm.createContext(s);
  vm.runInContext(script,s,{filename:label}); return elements;
}
function storageKey(){
  const k=[...backing.keys()].find(k=>k.startsWith('owned-home-v5:'));
  if(!k) throw new Error('owned-home-v5 key missing');
  return k;
}
function assertControl(label){
  const raw=backing.get(storageKey());
  const x=JSON.parse(raw);
  const got=Object.keys(x).sort();
  const want=['created_at','expires_at','id'].sort();
  if(JSON.stringify(got)!==JSON.stringify(want)) throw new Error(label+': unexpected persisted fields '+got);
  for(const bad of ['CONTINUE','HOLD','CANCEL','UNSURE','response','trace','receipt','SECRET_HUMAN_BROWSER_SENTINEL','raw']){
    if(raw.includes(bad)) throw new Error(label+': raw/derived content persisted: '+bad);
  }
  return x;
}
async function settle(ms=180){ await new Promise(r=>setTimeout(r,ms)); }

let elements=start('human.js');
await settle(30);
if(!elements.create.listeners.click) throw new Error('create handler missing');
await elements.create.listeners.click();
await settle();
let control=assertControl('created');
const id=control.id;
if(!calls.at(-1)?.data?.result || calls.at(-1).data.result.status!=='WAITING') throw new Error('human request not WAITING');

elements.message.value=' CONTINUE ';
await elements.form.listeners.submit({preventDefault(){}});
await settle();
control=assertControl('responded');
if(control.id!==id) throw new Error('request identity drift after response');
if(calls.at(-1)?.data?.result?.status!=='RESPONSE_DURABLE') throw new Error('response not durable');

await elements.resume.listeners.click();
await settle();
control=assertControl('resumed');
const finalCall=calls.at(-1)?.data?.result;
if(finalCall?.status!=='STOP' || finalCall?.continuation_count!==1 || finalCall?.continuations_this_call!==1)
  throw new Error('one-hop resume did not STOP exactly once');

const elements2=start('human-reload.js');
await settle(240);
const reload=assertControl('reload');
if(reload.id!==id) throw new Error('reload identity drift');
const observed=calls.at(-1)?.data?.result;
if(observed?.status!=='STOP' || observed?.continuation_count!==1 || observed?.continuations_this_call!==0)
  throw new Error('reload did not observe terminal state');

if([...backing.values()].some(v=>v.includes('CONTINUE'))) throw new Error('human response persisted in browser storage');

console.log(JSON.stringify({
  status:'PASS',origin,request_id:id,control_fields:Object.keys(reload).sort(),
  persisted_control_fields:3,raw_response_storage:0,derived_output_storage:0,secret_persistence:0,
  session_identity_stable:true,continuation_count:1,duplicate_continuations:0,
  final_status:observed.status,
  call_ops:calls.map(x=>x.body?.op).filter(Boolean),
  total_storage_writes:writes.length
}));
