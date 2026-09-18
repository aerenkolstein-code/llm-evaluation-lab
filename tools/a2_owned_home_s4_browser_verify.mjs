#!/usr/bin/env node
import vm from 'node:vm';

const url = process.argv[2];
if (!url) throw new Error('URL required');
const origin = new URL(url).origin;
const html = await (await fetch(origin + '/tools')).text();
const script = await (await fetch(origin + '/tools.js')).text();
if (!html.includes('Synthetic tool workspace')) throw new Error('tools page missing');

const backing = new Map();
const writes = [];
const calls = [];
const localStorage = {
  getItem(k){ return backing.has(k) ? backing.get(k) : null; },
  setItem(k,v){ writes.push([String(k),String(v)]); backing.set(String(k),String(v)); },
  removeItem(k){ backing.delete(String(k)); }
};
let uuidNo=1;
function uuid(){ const tail=String(uuidNo++).padStart(12,'0'); return '00000000-0000-4000-8000-'+tail; }
function makeElements(){
  const ids=['skill','apply-skill','active-skill','form','message','submit','resume','next','status','reply','tool-info'];
  const e={};
  for(const id of ids) e[id]={id,value:id==='skill'?'synthetic.compute':'',textContent:'',hidden:false,disabled:false,listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}};
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
function sandbox(elements){
  return {document:{getElementById:id=>elements[id]},localStorage,location:{origin},
    crypto:{randomUUID:uuid},fetch:sandboxFetch,addEventListener:()=>{},console,JSON,RegExp,Number,
    setTimeout,clearTimeout,Promise,Error};
}
function start(label){
  const elements=makeElements(); const s=sandbox(elements); vm.createContext(s);
  vm.runInContext(script,s,{filename:label}); return elements;
}
function key(){
  const k=[...backing.keys()].find(k=>k.startsWith('owned-home-v4:'));
  if(!k) throw new Error('owned-home-v4 key missing'); return k;
}
function control(label){
  const raw=backing.get(key()); const x=JSON.parse(raw);
  const got=Object.keys(x).sort();
  const want=['action_id','session_id','skill_id','skill_version','target_id','turn_no'].sort();
  if(JSON.stringify(got)!==JSON.stringify(want)) throw new Error(label+': bad fields '+got);
  for(const bad of ['SECRET_TOOL_BROWSER_SENTINEL','2,3','876543','credential','receipt','raw_body']){
    if(raw.includes(bad)) throw new Error(label+': raw/private persistence '+bad);
  }
  return x;
}
async function settle(ms=160){ await new Promise(r=>setTimeout(r,ms)); }
async function submit(elements,text){
  elements.message.value=text; await elements.form.listeners.submit({preventDefault(){}}); await settle();
}
async function next(elements){
  if(!elements.next.listeners.click) throw new Error('next handler missing');
  elements.next.listeners.click(); await settle(30);
}
async function select(elements,skill){
  elements.skill.value=skill; await elements['apply-skill'].listeners.click(); await settle(20);
  if(control('select-'+skill).skill_id!==skill) throw new Error('skill selection not persisted');
}

let elements=start('tools.js'); await settle();
const initial=control('initial'); const session=initial.session_id;

// Rejected credential-shaped UI input must never be persisted.
await submit(elements,'api_key=SECRET_TOOL_BROWSER_SENTINEL');
control('after-secret');
if([...backing.values()].some(v=>v.includes('SECRET_TOOL_BROWSER_SENTINEL'))) throw new Error('secret persisted');

// P0
await submit(elements,'2,3');
let c=control('p0');
if(c.session_id!==session) throw new Error('session drift p0');
let toolCalls=calls.filter(x=>x.body?.op==='tool_execute');
if(toolCalls.at(-1)?.data?.result?.status!=='SUCCESS' || toolCalls.at(-1).data.result.tool_executions!==1) throw new Error('P0 failed');

// P1
await next(elements); await select(elements,'synthetic.scoped_read'); await submit(elements,'');
toolCalls=calls.filter(x=>x.body?.op==='tool_execute');
if(toolCalls.at(-1)?.data?.result?.status!=='SUCCESS' || toolCalls.at(-1).data.result.tool_executions!==1) throw new Error('P1 failed');

// P2
await next(elements); await select(elements,'synthetic.reversible_write'); await submit(elements,'876543');
toolCalls=calls.filter(x=>x.body?.op==='tool_execute');
if(toolCalls.at(-1)?.data?.result?.status!=='SUCCESS' || toolCalls.at(-1).data.result.tool_executions!==1) throw new Error('P2 failed');
if(toolCalls.at(-1).data.result.tool_receipt?.readback?.status!=='VERIFIED') throw new Error('P2 readback not verified');

// P3
await next(elements); await select(elements,'synthetic.consequential_send'); await submit(elements,'');
toolCalls=calls.filter(x=>x.body?.op==='tool_execute');
if(toolCalls.at(-1)?.data?.result?.status!=='REQUIRE_HUMAN' || toolCalls.at(-1).data.result.tool_executions!==0) throw new Error('P3 not held');

// P4
await next(elements); await select(elements,'synthetic.critical'); await submit(elements,'');
toolCalls=calls.filter(x=>x.body?.op==='tool_execute');
if(toolCalls.at(-1)?.data?.result?.status!=='REQUIRE_HUMAN' || toolCalls.at(-1).data.result.tool_executions!==0) throw new Error('P4 not held');

const beforeReload=control('before-reload');
if(beforeReload.session_id!==session || beforeReload.skill_id!=='synthetic.critical') throw new Error('control drift before reload');
const elements2=start('tools-reload.js'); await settle(220);
const afterReload=control('reload');
if(afterReload.session_id!==session || afterReload.skill_id!=='synthetic.critical') throw new Error('reload drift');

const statuses=toolCalls.map(x=>x.data.result.status);
const executions=toolCalls.map(x=>x.data.result.tool_executions);
if(JSON.stringify(statuses)!==JSON.stringify(['SUCCESS','SUCCESS','SUCCESS','REQUIRE_HUMAN','REQUIRE_HUMAN'])) throw new Error('unexpected tool statuses '+statuses);
if(JSON.stringify(executions)!==JSON.stringify([1,1,1,0,0])) throw new Error('unexpected execution counts '+executions);

console.log(JSON.stringify({
  status:'PASS',origin,flows:5,statuses,executions,manual_skill_switches:4,
  control_fields:Object.keys(afterReload).sort(),persisted_control_fields:6,
  raw_body_storage:0,secret_persistence:0,session_stable:true,
  skill_after_reload:afterReload.skill_id,tool_execute_calls:toolCalls.length,
  observe_calls:calls.filter(x=>x.body?.op==='tool_observe').length,total_storage_writes:writes.length
}));
