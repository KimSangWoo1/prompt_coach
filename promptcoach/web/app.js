'use strict';
const $ = id => document.getElementById(id);
const state = {boot:null, current:null, support:null, parent:null, rows:[], history:null, chart:'prompt', createKind:null, detail:null, page:'write', pending:null, draftEpoch:0, supportSource:null};
const techniqueName = id => state.boot.techniques.find(t=>t.id===id)?.name || id;
function node(tag, text='', cls='') { const n=document.createElement(tag); if(text!==null)n.textContent=text; if(cls)n.className=cls; return n; }
function clear(id){const n=typeof id==='string'?$(id):id; n.replaceChildren();return n;}
function notice(message,error=false){const n=$('notice');n.textContent=message;n.className='notice'+(error?' error':'');}
function hideNotice(){$('notice').classList.add('hidden');}
async function api(path,data,signal){
 const response=await fetch(path,{...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Prompt-Coach':'1'},body:JSON.stringify(data)}),signal});
 const payload=await response.json(); if(!response.ok)throw new Error(payload.error||'요청에 실패했습니다.');return payload;
}
async function busy(button, fn){
 const old=button?.textContent; const controls=[...document.querySelectorAll('button,input,textarea,select')].map(x=>[x,x.disabled]);
 controls.forEach(([x])=>x.disabled=true);document.body.classList.add('busy');if(button)button.textContent='처리 중…';
 try{await fn();}catch(e){notice(e.message||'처리 중 오류가 발생했습니다.',true);}finally{controls.forEach(([x,v])=>x.disabled=v);document.body.classList.remove('busy');if(button)button.textContent=old;updateStale();}
}
function options(id,items,empty=null,selected){
 const s=$(id),old=selected??s.value; s.replaceChildren(); if(empty!==null){const o=node('option',empty);o.value='';s.append(o);} for(const v of items){const o=node('option',v.name);o.value=v.id;s.append(o);} if([...s.options].some(o=>o.value===old))s.value=old;
}
let draftTimer;
function scheduleDraftSave(){clearTimeout(draftTimer);$('char-count').textContent=`${$('prompt-text').value.length.toLocaleString()}자`;updateStale();draftTimer=setTimeout(saveDraft,250);}
function saveDraft(){
 clearTimeout(draftTimer);
 try{localStorage.setItem('promptcoach.draft',JSON.stringify({title:$('prompt-title').value,text:$('prompt-text').value,context:$('prompt-context').value,task:$('task').value,project:$('project').value,member:$('member').value,session:$('session').value,parent:state.parent}));$('draft-status').textContent='초안을 이 브라우저에 저장했습니다.';}catch(e){$('draft-status').textContent='브라우저 초안 저장 공간이 부족합니다. 내용은 편집기에 유지되니 복사해 보관하세요.';}
 $('char-count').textContent=`${$('prompt-text').value.length.toLocaleString()}자`;updateStale();
}
function refreshContext(desired={}){
 options('project',state.boot.projects,null,desired.project);options('member',state.boot.members,null,desired.member);
 const sessions=state.boot.sessions.filter(s=>s.project_id===$('project').value&&s.member_id===$('member').value);
 options('session',sessions,sessions.length?'세션 선택':'＋ 버튼으로 세션을 만드세요',desired.session);
 $('project-guidelines').textContent='프로젝트 규칙: '+(state.boot.projects.find(p=>p.id===$('project').value)?.guidelines||'등록된 규칙 없음');
 updateStale();
}
function setPage(page){
 state.page=page;document.querySelectorAll('.page').forEach(p=>p.classList.toggle('hidden',p.id!==`page-${page}`));
 document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('active',n.dataset.page===page));
 $('breadcrumb').textContent='WORKSPACE / '+({write:'프롬프트 작성',history:'성장 기록',learn:'기법 라이브러리',settings:'평가 설정'}[page]);hideNotice();
 if(page==='history')loadHistory().catch(e=>notice(e.message,true));
 if(page==='settings')renderSettings();
 window.scrollTo({top:0,behavior:'smooth'});
}
function draftSnapshot(){return {text:$('prompt-text').value,context:$('prompt-context').value,task:$('task').value,session_id:$('session').value,project_id:$('project').value,epoch:state.draftEpoch};}
function sameDraft(source){const now=draftSnapshot();return !!source&&Object.keys(now).every(key=>source[key]===now[key]);}
function updateStale(){
 const current=state.current,empty=!$('prompt-text').value.trim();
 const stale=!!current&&(current.text!==$('prompt-text').value||current.context!==$('prompt-context').value||current.task!==$('task').value||current.session_id!==$('session').value);
 $('stale').classList.toggle('hidden',!stale);
 $('support').disabled=empty||!!state.pending;$('evaluate').disabled=empty||!!state.pending;$('copy-prompt').disabled=empty;
 $('cancel-ai').classList.toggle('hidden',!state.pending);
 const supportChanged=!!state.support&&!sameDraft(state.supportSource);
 $('apply-support').disabled=!state.support||supportChanged;
 $('support-source-status').textContent=supportChanged?'요청 이후 초안이 바뀌었습니다. 현재 편집 내용은 유지됩니다. 개선안을 별도로 복사하거나 Support를 다시 요청하세요.':'개선안은 자동 적용되지 않습니다. 확인 후 가져오거나 복사하세요.';
 $('revision-tag').textContent=state.parent?'기존 기록의 새 버전':'자동 저장되는 초안';
}
async function aiRequest(button,fn){
 if(state.pending)return;
 const request={controller:new AbortController(),button,label:button.textContent};state.pending=request;button.textContent='응답 기다리는 중…';
 $('ai-status').textContent='AI 처리 중 · 계속 작성하거나 바로 복사할 수 있습니다.';updateStale();
 try{await fn(request.controller.signal,request);}catch(e){if(e.name!=='AbortError')notice((e.message||'AI 요청에 실패했습니다.')+' 초안은 그대로이며 편집과 복사를 계속할 수 있습니다.',true);}
 finally{if(state.pending===request){state.pending=null;button.textContent=request.label;$('ai-status').textContent='Support와 점검은 필요할 때만 사용하세요.';updateStale();}}
}
function cancelAI(){const request=state.pending;if(!request)return;state.pending=null;request.controller.abort();request.button.textContent=request.label;$('ai-status').textContent='대기를 취소했습니다. 이미 전송한 요청은 AI 서버에서 계속 처리될 수 있습니다.';updateStale();}
async function writeClipboard(text){
 try{await navigator.clipboard.writeText(text);}catch(e){const area=node('textarea');area.value=text;document.body.append(area);area.select();const copied=document.execCommand('copy');area.remove();if(!copied)throw new Error('브라우저에서 복사 권한을 허용하거나 편집기의 내용을 직접 복사해 주세요.');}
}
async function copyPrompt(){
 const text=$('prompt-text').value;if(!text.trim())return;
 const parts=[];const rules=state.boot.projects.find(p=>p.id===$('project').value)?.guidelines||'';
 if(rules.trim())parts.push('프로젝트 규칙:\n'+rules);if($('prompt-context').value.trim())parts.push('배경 자료:\n'+$('prompt-context').value);
 const output=parts.length?[...parts,'요청:\n'+text].join('\n\n'):text;
 try{await writeClipboard(output);notice(parts.length?'프롬프트와 배경·프로젝트 규칙을 복사했습니다. 사용할 AI에 붙여넣으세요.':'프롬프트를 복사했습니다. 사용할 AI에 붙여넣으세요.');}catch(e){notice(e.message,true);}
}
function resultView(record,container){
 container.replaceChildren();const r=record.result;
 const top=node('div',null,'score-header'),number=node('div',String(r.score),'score-number '+r.grade);number.append(node('small',' / 100'));
 const right=node('div');right.append(node('span',r.grade.toUpperCase(),'pill '+r.grade),node('p',record.engine,'small muted'));top.append(number,right);container.append(top,node('p',r.summary,'summary'));
 const basis=node('p',`기준 ${r.rubric} · ${record.engine.startsWith('local:')?'AI 아님 · 표현 기반 점검':'AI 의미 평가 · 실제 성과 보장 아님'}`,'small muted');container.append(basis);
 for(const d of r.dimensions){
  const div=node('div',null,'dimension'),row=node('div',null,'row');row.append(node('span',d.label),node('span',d.applicable?`${d.score} / 5`:'N/A · 계산 제외'));div.append(row);
  if(d.applicable){const p=node('progress');p.max=5;p.value=d.score;p.setAttribute('aria-label',`${d.label} ${d.score}점`);div.append(p);}
  const details=node('details'),summary=node('summary','판단 근거');details.append(summary,node('p',d.reason));if(d.evidence)details.append(node('p',(d.evidence_verified===false?'AI의 해석: ':'원문 인용: ')+d.evidence,d.evidence_verified===false?'':'quote'));if(d.improvement)details.append(node('p',d.improvement));div.append(details);container.append(div);
 }
}
function list(title,items){const div=node('div');div.append(node('h3',title));const ul=node('ul');for(const x of items)ul.append(node('li',x));if(!items.length)div.append(node('p','해당 항목 없음','small muted'));else div.append(ul);return div;}
function renderFeedback(){
 const r=state.current.result,root=clear('feedback');
 const left=node('div');left.append(list('잘 전달한 점',r.strengths),list('확인하면 좋은 질문',r.questions));root.append(left);
 const right=node('div');right.append(node('h3','추천하는 기법'));
 for(const rec of r.recommendations){const item=node('div',null,'feedback-item');item.append(node('strong',techniqueName(rec.id)),node('p',rec.reason),node('p',rec.example,'quote'));right.append(item);}
 if(!r.recommendations.length)right.append(node('p','현재 작업에서 추가로 권할 기법이 없습니다.','muted'));
 right.append(node('h3','표현에서 감지한 기법 후보'));
 for(const t of r.techniques){const item=node('details',null,'feedback-item');item.append(node('summary',techniqueName(t.id)),node('p',t.explanation),node('p',(t.evidence_verified===false?'AI의 해석: ':'원문 인용: ')+t.evidence,t.evidence_verified===false?'':'quote'));right.append(item);}
 if(!r.techniques.length)right.append(node('p','현재 요청에 별도로 표시할 기법이 없습니다.','muted'));
 right.append(node('p','실제 기법 실행 여부나 전체 능력을 확정하는 결과가 아닙니다.','small muted'));root.append(right);$('feedback-card').classList.remove('hidden');
}
async function evaluate(){
 if(!$('prompt-text').value.trim())return;
 const source=draftSnapshot();const payload={...source,title:$('prompt-title').value,parent_id:state.parent,request_id:crypto.randomUUID(),allow_remote:$('remote-consent').checked};delete payload.epoch;
 await aiRequest($('evaluate'),async(signal,request)=>{
  const result=await api('/api/evaluate',payload,signal);if(state.pending!==request)return;
  if(source.epoch!==state.draftEpoch||source.session_id!==$('session').value||source.project_id!==$('project').value){notice('이전 초안의 점검이 끝났습니다. 현재 작성 내용은 유지됩니다.');return;}
  state.current=result;state.parent=result.id||null;
  $('result-empty').classList.add('hidden');$('result').classList.remove('hidden');resultView(result,$('result'));renderFeedback();saveDraft();
  notice(result.stored===false?'참고 점검이 끝났습니다. 점수는 접힌 선택 점검에서 볼 수 있습니다.':'참고 점검을 이력에 저장했습니다. 작성·복사는 점검 결과와 관계없이 사용할 수 있습니다.');
 });
}
async function support(){
 if(!$('prompt-text').value.trim())return;
 const source=draftSnapshot(),payload={...source,allow_remote:$('remote-consent').checked};delete payload.epoch;
 await aiRequest($('support'),async(signal,request)=>{
  const r=await api('/api/support',payload,signal);if(state.pending!==request)return;state.support=r;state.supportSource=source;
  $('support-engine').textContent=r.engine;clear('support-changes').append(list('개선한 부분',r.changes));$('improved-prompt').textContent=r.improved_prompt;clear('support-questions').append(list('확인하면 좋은 내용',r.questions));$('support-result').classList.remove('hidden');
  notice(sameDraft(source)?'개선안이 준비됐습니다. 확인 후 가져오거나 복사하세요.':'이전 초안에 대한 개선안이 준비됐습니다. 현재 편집 내용은 유지했습니다.');
 });
}
function resetDraft(){state.draftEpoch++;state.current=null;state.parent=null;state.support=null;for(const id of ['prompt-title','prompt-text','prompt-context'])$(id).value='';$('task').value='auto';$('result-empty').classList.remove('hidden');$('result').classList.add('hidden');$('feedback-card').classList.add('hidden');$('support-result').classList.add('hidden');saveDraft();hideNotice();}
function contextChanged(){state.draftEpoch++;state.current=null;state.parent=null;state.support=null;$('result-empty').classList.remove('hidden');$('result').classList.add('hidden');$('feedback-card').classList.add('hidden');$('support-result').classList.add('hidden');saveDraft();}
function openCreate(kind){state.createKind=kind;$('create-title').textContent={projects:'프로젝트 추가',members:'작성자 추가',sessions:'연습 세션 시작'}[kind];$('create-name').value='';$('create-guidelines').value='';$('guidelines-label').classList.toggle('hidden',kind!=='projects');$('create-dialog').showModal();$('create-name').focus();}
async function create(event){
 event.preventDefault();const kind=state.createKind;const data={name:$('create-name').value,guidelines:$('create-guidelines').value,project_id:$('project').value,member_id:$('member').value};
 await busy(null,async()=>{const item=await api('/api/'+kind,data);state.boot=await api('/api/bootstrap');const desired={project:$('project').value,member:$('member').value,session:$('session').value};desired[{projects:'project',members:'member',sessions:'session'}[kind]]=item.id;refreshContext(desired);if(kind==='sessions'){state.current=null;state.parent=null;$('result-empty').classList.remove('hidden');$('result').classList.add('hidden');$('feedback-card').classList.add('hidden');$('support-result').classList.add('hidden');}renderFilters();$('create-dialog').close();saveDraft();notice('새 항목을 만들었습니다.');});
}
function renderSettings(){const s=state.boot.settings;$('provider').value=s.provider;$('base-url').value=s.base_url;$('timeout').value=s.timeout;$('api-key').value='';$('clear-key').checked=false;providerGuide(s.model);}
function keyStatus(){
 const s=state.boot.settings,p=$('provider').value,same=p===s.provider&&$('base-url').value.replace(/\/+$/,'')===s.base_url.replace(/\/+$/,'');
 $('key-status').textContent=['local','ollama'].includes(p)?'이 평가 방식에는 API 키가 필요하지 않습니다.':!same?'공급자·API 주소별로 키를 분리합니다. 설정 저장 후 이 주소의 키 등록 여부를 확인할 수 있습니다.':s.api_key_configured?'이 공급자·주소의 API 키 설정됨 · 키는 파일이나 DB에 저장하지 않습니다.':'이 공급자·주소의 API 키 미설정 · 키를 입력하거나 공급자 환경변수를 설정해 주세요.';
}
function providerGuide(selectedModel){
 const provider=$('provider').value;
 const guides={local:'규칙 기반 점검은 키워드와 구조의 존재를 보는 오프라인 보조 기능입니다. AI가 아니며, 의미·사실·예시의 품질을 이해하지 못합니다. 설치 직후 연습용으로 사용할 수 있습니다.',ollama:'로컬 AI 사용: Ollama 설치 후 터미널에서 ollama pull qwen3:8b-q4_K_M 를 실행하고 서버를 켜세요. 모델과 JSON 스키마 지원 여부에 따라 결과가 다릅니다. 모델 다운로드 이후 평가 데이터는 로컬 Ollama로 전달됩니다.',openai:'외부 AI 사용: 기본 주소 https://api.openai.com/v1, 모델 예시 gpt-4.1-mini. JSON Schema 구조화 출력을 지원하는 모델이 필요합니다. 실제 이용 가능한 모델·요금은 계정에서 확인하세요. API 키는 환경변수 OPENAI_API_KEY 또는 이 화면에서 설정할 수 있습니다. 앱을 종료하면 화면에서 입력한 키는 사라집니다.'};
 guides.anthropic='Claude 사용: API 주소 https://api.anthropic.com/v1. 드롭다운에서 모델을 선택하세요. ANTHROPIC_API_KEY 환경변수 또는 이 화면에서 Claude API 키를 설정할 수 있습니다. 평가와 Support에 API 이용료가 발생할 수 있습니다. 입력한 키는 앱 종료 시 사라집니다.';
 $('provider-guide').textContent=guides[provider];
 const preset=state.boot.providers[provider],saved=state.boot.settings;
 const models=[...new Set([...preset.models,preset.model,...(saved.provider===provider?[saved.model]:[])])];
 options('model',models.map(id=>({id,name:id})),null,selectedModel||preset.model);$('model').disabled=provider==='local';keyStatus();
}
function refreshEngine(){const s=state.boot.settings;$('engine-pill').textContent=s.provider==='local'?'규칙 기반 점검 · AI 아님':`${state.boot.providers[s.provider].name} · ${s.model}`;$('remote-consent-wrap').classList.toggle('hidden',!['openai','anthropic'].includes(s.provider));$('remote-consent').checked=false;}
async function saveSettings(){await busy($('save-settings'),async()=>{const r=await api('/api/settings',{provider:$('provider').value,model:$('model').value,base_url:$('base-url').value,timeout:Number($('timeout').value),api_key:$('api-key').value,clear_key:$('clear-key').checked});state.boot.settings=r;refreshEngine();renderSettings();notice('설정을 저장했습니다. API 키는 파일에 기록하지 않습니다.');});}
function renderLibrary(){
 const root=clear('technique-cards');state.boot.techniques.forEach((t,i)=>{
  const card=node('article',null,'card');card.append(node('span',String(i+1).padStart(2,'0'),'eyebrow'),node('h2',t.name),node('p',t.description),node('p','사용: '+t.when),node('div','한계: '+t.limitation,'small'));
  const examples=state.boot.examples?.[t.id]||[];
  if(examples.length){
   const label=node('label','예시 선택','example-selector'),select=node('select');select.setAttribute('aria-label',t.name+' 예시 선택');
   const empty=node('option','예시를 선택하세요');empty.value='';select.append(empty);
   examples.forEach((example,index)=>{const option=node('option',example.title);option.value=String(index);select.append(option);});label.append(select);
   const preview=node('div',null,'technique-example hidden'),prompt=node('pre'),explanation=node('p',null,'example-explanation');preview.id='example-'+t.id;preview.setAttribute('aria-live','polite');select.setAttribute('aria-controls',preview.id);
   preview.append(node('h3','예시 프롬프트'),prompt,node('h3','적용 포인트'),explanation);
   select.addEventListener('change',()=>{const example=select.value===''?null:examples[Number(select.value)];preview.classList.toggle('hidden',!example);prompt.textContent=example?.prompt||'';explanation.textContent=example?.explanation||'';});card.append(label,preview);
  }
  root.append(card);
 });
 const practice=clear('practice');const cases=[['단순 요청','예시나 역할 없이도 명확하게 요청해 보세요.','“오늘도 수고했어”를 자연스러운 영어 한 문장으로 번역해줘.','simple'],['개발 요청','환경·변경 범위·검증 기준을 보완해 보세요.','Unity UI 로딩 버그를 고쳐줘.','development'],['글쓰기 요청','독자와 목적, 결과 형식을 구체화해 보세요.','우리 팀의 신규 기능을 소개하는 글을 작성해줘.','writing']];
 cases.forEach(([title,desc,text,task])=>{const card=node('article',null,'card');const button=node('button','연습 시작하기 →','secondary');button.addEventListener('click',()=>{if($('prompt-text').value.trim()&&!confirm('현재 편집 중인 초안을 연습 예제로 바꿀까요? 저장한 평가 기록은 유지됩니다.'))return;resetDraft();$('prompt-title').value=title+' 연습';$('prompt-text').value=text;$('task').value=task;saveDraft();setPage('write');});card.append(node('h2',title),node('p',desc),button);practice.append(card);});
 const table=makeTable(['평가 항목','가중치','확인할 내용'],Object.values(state.boot.dimensions).map(d=>[d.label,String(d.weight),d.description]));clear('rubric-table').append(table);
}
function makeTable(headers,rows){const table=node('table'),thead=node('thead'),tr=node('tr');headers.forEach(h=>tr.append(node('th',h)));thead.append(tr);table.append(thead);const body=node('tbody');rows.forEach(values=>{const row=node('tr');values.forEach(v=>{const td=node('td');if(v instanceof Node)td.append(v);else td.textContent=String(v??'');row.append(td);});body.append(row);});table.append(body);return table;}
function renderFilters(){options('filter-project',state.boot.projects,'전체 프로젝트');options('filter-member',state.boot.members,'전체 작성자');options('filter-session',state.boot.sessions,'전체 세션');}
function filterQuery(){const p=new URLSearchParams();for(const [id,key] of [['filter-project','project_id'],['filter-member','member_id'],['filter-session','session_id'],['filter-engine','engine'],['filter-start','start'],['filter-end','end'],['filter-latest','latest']])if($(id).value)p.set(key,$(id).value);return p.toString();}
let historyRequest=0;
async function loadHistory(){
 const id=++historyRequest;
 // Discover engine options from all records while preserving the selected mode.
 const all=await api('/api/history?latest=0');if(id!==historyRequest)return;
 const engines=[...new Set(all.rows.map(r=>r.engine))].map(x=>({id:x,name:x}));options('filter-engine',engines,'전체 평가 방식');
 const data=await api('/api/history?'+filterQuery());if(id!==historyRequest)return;state.history=data;state.rows=data.rows;$('export-json').href='/api/export?'+filterQuery();renderHistory();
}
function renderHistory(){
 const h=state.history,s=h.summary,m=clear('metrics');const good=s.grades.good||0;
 for(const [label,value,caption] of [['평가 기록',s.count,'선택한 필터 기준'],['작성 준비도 평균',s.average??'—','100점 환산 · 실제 성과 아님'],['GOOD 비율',s.count?Math.round(good/s.count*100)+'%':'—',`${good}건 / ${s.count}건`],['연습 세션',h.sessions.length,'기록이 있는 세션']]){const card=node('div',null,'metric');card.append(node('span',label,'caption'),node('div',String(value),'value'),node('span',caption,'caption'));m.append(card);}
 const warnings=[];if(s.engines.length>1||s.rubrics.length>1)warnings.push('서로 다른 평가 방식 또는 기준이 섞여 있습니다. 점수를 직접 비교하려면 평가 방식 필터를 선택하세요.');if(s.count<5)warnings.push('기록이 적습니다. 현재 값은 연습 이력의 요약이며 개인의 능력 판정이 아닙니다.');$('history-warning').textContent=warnings.join(' ');$('history-warning').classList.toggle('hidden',!warnings.length);
 const dist=clear('distribution');for(const g of ['good','normal','bad']){const d=node('div',null,'distribution-row '+g),row=node('div',null,'row');row.append(node('span',g.toUpperCase()),node('span',`${s.grades[g]||0}건`));const p=node('progress');p.max=s.count||1;p.value=s.grades[g]||0;p.setAttribute('aria-label',`${g} ${p.value}건`);d.append(row,p);dist.append(d);}
 const rows=[...h.rows].reverse().map(r=>{const badge=node('span',r.grade.toUpperCase(),'pill '+r.grade);const button=node('button','상세 보기','secondary');button.addEventListener('click',()=>openRecord(r));return [r.created_at.slice(0,16).replace('T',' '),r.title,`v${r.revision}`,r.member_name,r.session_name,r.score,badge,r.engine,button];});
 clear('history-table').append(makeTable(['일시 KST','프롬프트','버전','작성자','세션','점수','등급','평가 방식','보기'],rows));if(!rows.length)$('history-table').append(node('p','아직 기록이 없습니다. 프롬프트를 점검하거나 필터를 변경해 보세요.','muted'));
 $('history-count').textContent=`${s.count}건`;
 for(const [id,items] of [['session-table',h.sessions],['member-table',h.members]])clear(id).append(makeTable([id==='session-table'?'세션':'작성자','기록','평균','Good / Normal / Bad'],items.map(x=>[x.name,x.count,x.average,`${x.good} / ${x.normal} / ${x.bad}`])));
 renderChart();
}
function svg(tag,attrs,text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs||{}).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;return n;}
function renderChart(){
 const root=clear('trend-chart');if(!state.history)return;
 const h=state.history;const data=state.chart==='prompt'?h.rows.map((r,i)=>({label:r.title,value:r.score,detail:`${r.title} · v${r.revision} · ${r.score}점 · ${r.engine}`,index:i+1})):h[state.chart==='session'?'sessions':'daily'].map((r,i)=>({label:r.name,value:r.average,detail:`${r.name} · 평균 ${r.average}점 · ${r.count}건`,index:i+1}));
 if(!data.length){root.append(node('p','점검을 시작하면 추이가 표시됩니다.','empty'));return;}
 const width=620,height=240,left=38,right=18,top=18,bottom=35;const chart=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':`${state.chart} 기준 작성 준비도 그래프, ${data.length}개 점. 정확한 값은 아래 이력과 요약 표에서 확인할 수 있습니다.`});
 const y=v=>top+(100-v)/100*(height-top-bottom),x=i=>left+(data.length===1?.5:i/(data.length-1))*(width-left-right);
 for(const score of [0,25,50,75,100]){chart.append(svg('line',{x1:left,y1:y(score),x2:width-right,y2:y(score),stroke:'#e9edf5'}),svg('text',{x:5,y:y(score)+3,fill:'#98a4b6','font-size':9},String(score)));}
 for(const score of [55,80])chart.append(svg('line',{x1:left,y1:y(score),x2:width-right,y2:y(score),stroke:score===80?'#c9e7dd':'#eadfbe','stroke-dasharray':'4 5'}));
 chart.append(svg('polyline',{points:data.map((d,i)=>`${x(i)},${y(d.value)}`).join(' '),fill:'none',stroke:'#647ee9','stroke-width':2.4}));
 data.forEach((d,i)=>{const circle=svg('circle',{cx:x(i),cy:y(d.value),r:4,fill:d.value>=80?'#148c76':d.value>=55?'#cf9b39':'#da727a',tabindex:0});circle.append(svg('title',{},d.detail));chart.append(circle);if(i===0||i===data.length-1||data.length<=8)chart.append(svg('text',{x:x(i),y:height-12,'text-anchor':'middle',fill:'#8a98ae','font-size':9},state.chart==='prompt'?`#${d.index}`:d.label.slice(0,11)));});root.append(chart);
}
function openRecord(r){state.detail=r;const root=clear('record-detail');root.append(node('h3',`${r.title} · v${r.revision}`),node('p',`${r.project_name} / ${r.member_name} / ${r.session_name} · ${r.created_at.slice(0,16).replace('T',' ')} KST`,'muted'),node('pre',r.text));if(r.context)root.append(node('h3','배경 자료'),node('pre',r.context));if(r.result.project_context)root.append(node('h3','평가 당시 프로젝트 규칙'),node('pre',r.result.project_context));const result=node('div');resultView(r,result);root.append(result);root.append(list('개선 질문',r.result.questions));$('record-dialog').showModal();}
function loadRecord(){state.draftEpoch++;const r=state.detail;refreshContext({project:r.project_id,member:r.member_id,session:r.session_id});$('prompt-title').value=r.title;$('prompt-text').value=r.text;$('prompt-context').value=r.context;$('task').value=r.task;state.current=r;state.parent=r.id;state.support=null;$('result-empty').classList.add('hidden');$('result').classList.remove('hidden');resultView(r,$('result'));renderFeedback();$('support-result').classList.add('hidden');$('record-dialog').close();saveDraft();setPage('write');notice('저장된 기록을 불러왔습니다. 수정 후 점검하면 새 버전으로 저장합니다.');}
async function init(){
 try{
  state.boot=await api('/api/bootstrap');let draft={};try{draft=JSON.parse(localStorage.getItem('promptcoach.draft')||'{}');}catch(e){}
  state.parent=draft.parent||null;refreshContext(draft);if(!$('session').value)state.parent=null;$('prompt-title').value=draft.title||'';$('prompt-text').value=draft.text||'';$('prompt-context').value=draft.context||'';$('task').value=draft.task||'auto';saveDraft();refreshEngine();renderFilters();renderLibrary();renderSettings();
  document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>setPage(b.dataset.page)));
  for(const id of ['prompt-title','prompt-text','prompt-context','task'])$(id).addEventListener('input',scheduleDraftSave);
  for(const id of ['project','member'])$(id).addEventListener('change',()=>{refreshContext();contextChanged();});$('session').addEventListener('change',contextChanged);
  $('evaluate').addEventListener('click',evaluate);$('support').addEventListener('click',support);$('copy-prompt').addEventListener('click',copyPrompt);$('cancel-ai').addEventListener('click',cancelAI);window.addEventListener('pagehide',saveDraft);
  $('copy-improved').addEventListener('click',async()=>{if(!state.support)return;try{await writeClipboard(state.support.improved_prompt);notice('개선안을 복사했습니다.');}catch(e){notice(e.message,true);}});
  $('apply-support').addEventListener('click',()=>{if(!state.support||!sameDraft(state.supportSource))return;$('prompt-text').value=state.support.improved_prompt;state.supportSource=draftSnapshot();saveDraft();$('prompt-text').focus();window.scrollTo({top:0,behavior:'smooth'});notice('개선안을 편집기로 가져왔습니다. 필요한 부분만 수정한 뒤 바로 복사하세요. 점검은 선택입니다.');});
  $('clear-draft').addEventListener('click',()=>{if($('prompt-text').value.trim()&&!confirm('현재 초안을 비우고 새 프롬프트를 시작할까요? 저장된 기록은 유지됩니다.'))return;resetDraft();});
  for(const kind of ['project','member','session'])$('new-'+kind).addEventListener('click',()=>openCreate(kind+'s'));
  $('cancel-create').addEventListener('click',()=>$('create-dialog').close());$('create-form').addEventListener('submit',create);
  $('provider').addEventListener('change',()=>{const p=$('provider').value,s=state.boot.settings,defaults=p===s.provider?s:state.boot.providers[p];$('base-url').value=defaults.base_url;$('api-key').value='';$('clear-key').checked=false;providerGuide(defaults.model);});
  $('base-url').addEventListener('input',keyStatus);
  $('save-settings').addEventListener('click',saveSettings);
  for(const id of ['filter-project','filter-member','filter-session','filter-engine','filter-start','filter-end','filter-latest'])$(id).addEventListener('change',()=>loadHistory().catch(e=>notice(e.message,true)));
  document.querySelectorAll('[data-chart]').forEach(b=>b.addEventListener('click',()=>{state.chart=b.dataset.chart;document.querySelectorAll('[data-chart]').forEach(x=>x.classList.toggle('active',x===b));renderChart();}));
  $('close-record').addEventListener('click',()=>$('record-dialog').close());$('load-record').addEventListener('click',loadRecord);
 }catch(e){notice('앱을 불러오지 못했습니다. '+e.message,true);}
}
init();
