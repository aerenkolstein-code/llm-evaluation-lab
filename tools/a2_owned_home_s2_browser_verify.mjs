#!/usr/bin/env node
import vm from 'node:vm';

const url = process.argv[2];
if (!url) throw new Error('URL required');
const origin = new URL(url).origin;
const html = await (await fetch(origin + '/continuity')).text();
const script = await (await fetch(origin + '/continuity.js')).text();
if (!html.includes('Multi-topic') && !html.includes('Topics')) throw new Error('continuity page missing');

const backing = new Map();
const writes = [];
const localStorage = {
  getItem(k){ return backing.has(k) ? backing.get(k) : null; },
  setItem(k,v){ writes.push([String(k),String(v)]); backing.set(String(k),String(v)); },
  removeItem(k){ backing.delete(String(k)); }
};
let uuidNo = 1;
function uuid(){ const tail=String(uuidNo++).padStart(12,'0'); return `00000000-0000-4000-8000-${tail}`; }
function makeElements(){
  const ids=['session','active-topic','topic','switch','form','message','submit','resume','next','status','reply'];
  const e={};
  for(const id of ids) e[id]={id,value:id==='topic'?'topic-a':'',textContent:'',hidden:false,disabled:false,listeners:{},
    addEventListener(name,fn){this.listeners[name]=fn;}};
  return e;
}
const elements=makeElements();
const pageListeners={};
const realFetch=globalThis.fetch;
async function sandboxFetch(path, opts={}){
  const target=new URL(path, origin).toString();
  return realFetch(target, opts);
}
const sandbox={
  document:{getElementById:id=>elements[id]}, localStorage,
  location:{origin}, crypto:{randomUUID:uuid}, fetch:sandboxFetch,
  addEventListener:(n,fn)=>{pageListeners[n]=fn;}, console, JSON, RegExp, Number,
  setTimeout, clearTimeout, Promise, Error
};
vm.createContext(sandbox);
vm.runInContext(script,sandbox,{filename:'continuity.js'});
await new Promise(r=>setTimeout(r,100));
const key=[...backing.keys()].find(k=>k.startsWith('owned-home-v2:'));
if(!key) throw new Error('no v2 control key');
function parsed(){ return JSON.parse(backing.get(key)); }
function assertControl(label){
  const x=parsed(); const keys=Object.keys(x).sort();
  const want=['request_id','session_id','topic_id','turn_no'].sort();
  if(JSON.stringify(keys)!==JSON.stringify(want)) throw new Error(label+': unexpected persistent keys '+keys);
  const raw=backing.get(key);
  for(const bad of ['api_key','SECRET_BROWSER_SENTINEL','Synthetic evidence','message','fixture','context','trace','source body'])
    if(raw.includes(bad)) throw new Error(label+': raw/private content persisted');
  return x;
}
const initial=assertControl('initial');
const initialSession=initial.session_id;

// Credential-shaped input must never enter persistent browser storage even when rejected.
elements.message.value='api_key=SECRET_BROWSER_SENTINEL';
await elements.form.listeners.submit({preventDefault(){}});
await new Promise(r=>setTimeout(r,100));
const afterSecret=assertControl('after-secret');
if([...backing.values()].some(v=>v.includes('SECRET_BROWSER_SENTINEL'))) throw new Error('secret persisted');
if(elements.message.value!=='') throw new Error('message not cleared');

// Clear uncertain/rejected handle through New turn control, then submit safe text.
if(elements.next.listeners.click) elements.next.listeners.click();
await new Promise(r=>setTimeout(r,30));
elements.message.value='ordinary continuity message';
await elements.form.listeners.submit({preventDefault(){}});
await new Promise(r=>setTimeout(r,100));
const afterSafe=assertControl('after-safe');
if(afterSafe.session_id!==initialSession) throw new Error('session drift after safe turn');
if(elements.message.value!=='') throw new Error('safe message not cleared');

// Switch topic using actual served handler.
if(elements.next.listeners.click) elements.next.listeners.click();
elements.topic.value='topic-b';
await elements.switch.listeners.click();
await new Promise(r=>setTimeout(r,100));
const afterSwitch=assertControl('after-switch');
if(afterSwitch.session_id!==initialSession || afterSwitch.topic_id!=='topic-b') throw new Error('topic/session control drift');
const sessionText=elements.session.textContent, topicText=elements['active-topic'].textContent;

// Simulated reload: fresh DOM/JS realm, same browser storage. It must keep only control metadata and restore identity.
const elements2=makeElements();
const sandbox2={document:{getElementById:id=>elements2[id]},localStorage,location:{origin},crypto:{randomUUID:uuid},fetch:sandboxFetch,
  addEventListener:()=>{},console,JSON,RegExp,Number,setTimeout,clearTimeout,Promise,Error};
vm.createContext(sandbox2); vm.runInContext(script,sandbox2,{filename:'continuity-reload.js'});
await new Promise(r=>setTimeout(r,150));
const reloaded=assertControl('reload');
if(reloaded.session_id!==initialSession || reloaded.topic_id!=='topic-b') throw new Error('reload identity drift');
if(!elements2.session.textContent.includes(initialSession) || !elements2['active-topic'].textContent.includes('topic-b')) throw new Error('reload display identity drift');

console.log(JSON.stringify({status:'PASS',origin,control_keys:Object.keys(reloaded).sort(),session_stable:true,topic_after_reload:'topic-b',
  raw_browser_writes:0,secret_persistence:0,total_storage_writes:writes.length,session_text:sessionText,topic_text:topicText}));
