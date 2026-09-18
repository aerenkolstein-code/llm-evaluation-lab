#!/usr/bin/env node
import vm from 'node:vm';

const url = process.argv[2];
if (!url) throw new Error('URL required');
const origin = new URL(url).origin;
const html = await (await fetch(origin + '/models')).text();
const script = await (await fetch(origin + '/models.js')).text();
if (!html.includes('Local synthetic model workspace')) throw new Error('models page missing');

const backing = new Map();
const writes = [];
const localStorage = {
  getItem(k){ return backing.has(k) ? backing.get(k) : null; },
  setItem(k,v){ writes.push([String(k), String(v)]); backing.set(String(k), String(v)); },
  removeItem(k){ backing.delete(String(k)); }
};
let uuidNo = 1;
function uuid(){ const tail=String(uuidNo++).padStart(12,'0'); return '00000000-0000-4000-8000-' + tail; }
function makeElements(){
  const ids=['session','active-topic','topic','switch','model','apply-model','active-model',
    'form','message','submit','resume','next','status','reply','model-info'];
  const e={};
  for (const id of ids) e[id]={id,value:id==='topic'?'topic-a':id==='model'?'synthetic-small':'',
    textContent:'',hidden:false,disabled:false,listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}};
  return e;
}
const realFetch=globalThis.fetch;
async function sandboxFetch(path,opts={}){
  return realFetch(new URL(path, origin).toString(), opts);
}
function makeSandbox(elements){
  return {
    document:{getElementById:id=>elements[id]}, localStorage, location:{origin},
    crypto:{randomUUID:uuid}, fetch:sandboxFetch, addEventListener:()=>{}, console, JSON, RegExp, Number,
    setTimeout, clearTimeout, Promise, Error
  };
}
function storageKey(){
  const k=[...backing.keys()].find(k=>k.startsWith('owned-home-v3:'));
  if(!k) throw new Error('owned-home-v3 control key missing');
  return k;
}
function assertControl(label){
  const raw=backing.get(storageKey());
  const x=JSON.parse(raw);
  const keys=Object.keys(x).sort();
  const want=['profile_key','profile_version','request_id','session_id','topic_id','turn_no'].sort();
  if(JSON.stringify(keys)!==JSON.stringify(want)) throw new Error(label+': unexpected persisted fields '+keys);
  for(const bad of ['SECRET_MODEL_BROWSER_SENTINEL','ordinary model message','second model message','api_key','credential','provider body','Synthetic evidence']){
    if(raw.includes(bad)) throw new Error(label+': raw/private content persisted: '+bad);
  }
  return x;
}
async function settle(ms=120){ await new Promise(r=>setTimeout(r,ms)); }

const elements=makeElements();
const sandbox=makeSandbox(elements);
vm.createContext(sandbox);
vm.runInContext(script,sandbox,{filename:'models.js'});
await settle();

const initial=assertControl('initial');
const session=initial.session_id;
if(initial.profile_key!=='synthetic-small' || initial.profile_version!=='v1') throw new Error('initial profile mismatch');

elements.model.value='synthetic-large';
await elements['apply-model'].listeners.click();
let c=assertControl('after-large-select');
if(c.profile_key!=='synthetic-large') throw new Error('large profile intent not persisted');

elements.message.value='api_key=SECRET_MODEL_BROWSER_SENTINEL';
await elements.form.listeners.submit({preventDefault(){}});
await settle();
assertControl('after-secret');
if([...backing.values()].some(v=>v.includes('SECRET_MODEL_BROWSER_SENTINEL'))) throw new Error('credential-shaped text persisted');
if(elements.message.value!=='') throw new Error('secret message not cleared');

elements.message.value='ordinary model message';
await elements.form.listeners.submit({preventDefault(){}});
await settle(180);
c=assertControl('after-large-turn');
if(c.session_id!==session || c.profile_key!=='synthetic-large') throw new Error('session/profile drift after large turn');
if(!elements['active-model'].textContent.includes('synthetic-large')) throw new Error('server did not select large profile');
if(elements.message.value!=='') throw new Error('safe message not cleared');

if(!elements.next.listeners.click) throw new Error('new-turn handler missing');
elements.next.listeners.click();
await settle(30);

elements.model.value='synthetic-capable';
await elements['apply-model'].listeners.click();
elements.topic.value='topic-b';
await elements.switch.listeners.click();
await settle(30);
c=assertControl('after-capable-topic-select');
if(c.profile_key!=='synthetic-capable' || c.topic_id!=='topic-b' || c.session_id!==session) throw new Error('manual switch drift');

elements.message.value='second model message';
await elements.form.listeners.submit({preventDefault(){}});
await settle(180);
c=assertControl('after-capable-turn');
if(!elements['active-model'].textContent.includes('synthetic-capable')) throw new Error('server did not select capable profile');
if(c.session_id!==session || c.topic_id!=='topic-b') throw new Error('session/topic drift after capable turn');

const elements2=makeElements();
const sandbox2=makeSandbox(elements2);
vm.createContext(sandbox2);
vm.runInContext(script,sandbox2,{filename:'models-reload.js'});
await settle(220);
const reloaded=assertControl('reload');
if(reloaded.session_id!==session || reloaded.topic_id!=='topic-b' || reloaded.profile_key!=='synthetic-capable' || reloaded.profile_version!=='v1')
  throw new Error('reload control identity/profile drift');
if(!elements2.session.textContent.includes(session) || !elements2['active-topic'].textContent.includes('topic-b'))
  throw new Error('reload display identity drift');

console.log(JSON.stringify({
  status:'PASS', origin, control_fields:Object.keys(reloaded).sort(),
  manual_profile_switches:2, raw_browser_writes:0, secret_persistence:0,
  session_stable:true, topic_after_reload:'topic-b', profile_after_reload:'synthetic-capable/v1',
  total_storage_writes:writes.length
}));
