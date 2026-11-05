// Run with: node --test tests/web_support.test.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

class Element {
 constructor(){this.value='';this.textContent='';this.disabled=false;this.checked=false;this.children=[];this.listeners={};this.dataset={};const classes=new Set();this.classList={add:c=>classes.add(c),toggle:(c,on)=>on?classes.add(c):classes.delete(c),contains:c=>classes.has(c)};}
 append(...nodes){this.children.push(...nodes);}
 replaceChildren(...nodes){this.children=[...nodes];}
 addEventListener(event,fn){(this.listeners[event]??=[]).push(fn);}
 async dispatch(event){for(const fn of this.listeners[event]||[])await fn({preventDefault(){}});}
 setAttribute(){}
}
const items = [
 {topic:'관리할 UI',reason:'대상에 따라 초안이 달라집니다.',question:'어떤 UI를 관리하나요?'},
 {topic:'담당할 동작',reason:'담당 범위를 확인해야 합니다.',question:'어떤 동작을 담당하나요?'}
];
function result(clarifications=items){return {clarifications,improved_prompt:'이 전체 교체안은 선택 반영에 사용하지 않음',changes:[],questions:[],engine:'ollama:test'};}
async function setup(){
 const elements=new Map(),timers=new Map(),calls=[],storage=new Map();let clockId=0;
 const el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
 const boot={settings:{provider:'ollama',model:'test',base_url:'http://127.0.0.1:11434'},projects:[],techniques:[]};
 const context=vm.createContext({
  document:{getElementById:el,createElement:()=>new Element(),querySelectorAll:()=>[],body:{classList:{add(){},remove(){}}}},
  window:{addEventListener(){},scrollTo(){}},
  localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v)},
  setTimeout:fn=>{timers.set(++clockId,fn);return clockId;},clearTimeout:id=>timers.delete(id),
  AbortController,console,
  fetch:async(url,options)=>{calls.push({url,options});return {ok:true,json:async()=>url==='/api/bootstrap'?boot:result()};}
 });
 const code=fs.readFileSync(path.join(__dirname,'../promptcoach/web/app.js'),'utf8');
 vm.runInContext(code.replace(/\ninit\(\);\s*$/,''),context);
 // Exercise the real init event wiring; unrelated catalog/history rendering is outside this check.
 vm.runInContext('refreshContext=()=>{};refreshEngine=()=>{};renderFilters=()=>{};renderLibrary=()=>{};renderSettings=()=>{};',context);
 await vm.runInContext('init()',context);
 calls.length=0;
 const run=code=>vm.runInContext(code,context);
 const flush=async()=>{const pending=[...timers.values()];timers.clear();for(const fn of pending)await fn();};
 return {el,run,context,calls,storage,flush};
}

test('typing, pausing, context edits and task changes never request AI',async()=>{
 const a=await setup();
 for(const id of ['prompt-text','prompt-context','task']){a.el(id).value='작성 중';await a.el(id).dispatch('input');await a.flush();await a.el(id).dispatch('blur');await a.flush();}
 assert.equal(a.calls.length,0);
 assert.match(a.storage.get('promptcoach.draft'),/작성 중/);
 await a.el('support').dispatch('click');
 assert.equal(a.calls.length,1);
 assert.equal(a.calls[0].url,'/api/support');
});

test('manual Support preserves original and applies only checked items and supplied answers',async()=>{
 const a=await setup(),original='\n유니티에서 사용할 UIManager 초안 만들어줘\n';a.el('prompt-text').value=original;
 await a.run('support()');
 assert.equal(a.el('prompt-text').value,original);
 assert.equal(a.el('apply-support').disabled,true);
 assert.equal(a.el('improved-prompt').textContent,original);
 assert.equal(a.run('state.supportChoices[0].check.checked'),false);
 a.run('state.supportChoices[0].check.checked=true;state.supportChoices[0].answer.value="기존 인벤토리 패널"');
 await a.run('state.supportChoices[0].check.dispatch("change")');
 assert.equal(a.el('apply-support').disabled,false);
 assert.equal(a.el('improved-prompt').textContent,original+'\n\n관리할 UI: 기존 인벤토리 패널');
 assert.match(a.el('support-changes').children[0].children[1].textContent,/이유: 대상에 따라/);
 await a.el('apply-support').dispatch('click');
 assert.equal(a.el('prompt-text').value,original+'\n\n관리할 UI: 기존 인벤토리 패널');
 assert.ok(!a.el('prompt-text').value.includes('담당할 동작'));
 await a.flush();assert.equal(a.calls.length,1);
});

test('selected unanswered item adds a slot without inventing a requirement',async()=>{
 const a=await setup();a.el('prompt-text').value='UI 초안';await a.run('support()');
 a.run('state.supportChoices[1].check.checked=true;updateStale();applySupport()');
 assert.equal(a.el('prompt-text').value,'UI 초안\n\n[직접 입력: 담당할 동작]');
});

test('slow request keeps writing and copy enabled, discards stale response, and never auto retries',async()=>{
 const a=await setup();let finish;
 a.context.fetch=()=>new Promise(resolve=>finish=()=>resolve({ok:true,json:async()=>result()}));
 a.el('prompt-text').value='원래 초안';const pending=a.run('support()');
 assert.equal(a.el('prompt-text').disabled,false);assert.equal(a.el('copy-prompt').disabled,false);
 a.el('prompt-text').value='대기 중 새로 작성';await a.el('prompt-text').dispatch('input');await a.flush();
 finish();await pending;await a.flush();
 assert.equal(a.el('prompt-text').value,'대기 중 새로 작성');
 assert.equal(a.run('state.support'),null);
 assert.match(a.el('notice').textContent,/지난 제안은 표시하지/);
});

test('changing source disables old choices and prevents stale application',async()=>{
 const a=await setup();a.el('prompt-text').value='첫 초안';await a.run('support()');
 a.run('state.supportChoices[0].check.checked=true');a.el('prompt-text').value='새 초안';await a.el('prompt-text').dispatch('input');
 assert.equal(a.el('apply-support').disabled,true);assert.equal(a.run('state.supportChoices[0].answer.disabled'),true);
 a.run('applySupport()');assert.equal(a.el('prompt-text').value,'새 초안');
});

test('no missing information leaves original untouched with no selectable additions',async()=>{
 const a=await setup();a.context.fetch=async()=>({ok:true,json:async()=>result([])});
 a.el('prompt-text').value='고마워를 영어 한 문장으로 번역해줘';await a.run('support()');
 assert.equal(a.el('apply-support').disabled,true);
 assert.match(a.el('support-changes').children[0].textContent,/핵심 누락이 없습니다/);
 assert.equal(a.el('prompt-text').value,'고마워를 영어 한 문장으로 번역해줘');
});

test('cancelled response and failed request cannot replace or clear draft',async()=>{
 const a=await setup();let finish;
 a.context.fetch=()=>new Promise(resolve=>finish=()=>resolve({ok:true,json:async()=>result()}));
 a.el('prompt-text').value='유지할 초안';const pending=a.run('support()');a.run('cancelAI()');finish();await pending;
 assert.equal(a.run('state.support'),null);assert.equal(a.el('prompt-text').value,'유지할 초안');
 a.context.fetch=async()=>{throw new Error('서버 연결 실패');};await a.run('support()');
 assert.equal(a.el('prompt-text').value,'유지할 초안');assert.equal(a.el('copy-prompt').disabled,false);
 assert.match(a.el('notice').textContent,/서버 연결 실패/);
});
