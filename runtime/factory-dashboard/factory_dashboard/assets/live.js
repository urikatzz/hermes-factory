'use strict';
(() => {
 const {el,elapsed,buildTimeline,renderTimeline}=FactoryTimeline;
 const state={report:null,selected:null,attempt:null,editing:null,busy:false,query:'',filter:'all',lastRefresh:null,pendingSubmission:null};
 const main=document.getElementById('main'),connection=document.getElementById('connection');
 const dateLabel=value=>value===null||value===undefined?'Not recorded':new Date(value*1000).toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'})+' · '+Intl.DateTimeFormat().resolvedOptions().timeZone;
 const runStart=root=>{const starts=[root,...(root.stages||[])].flatMap(t=>t.attempts||[]).map(a=>a.started_at).filter(v=>typeof v==='number');return starts.length?Math.min(...starts):null;};
 const num=n=>typeof n==='number'?new Intl.NumberFormat('en',{notation:'compact',maximumFractionDigits:1}).format(n):'—';
 const button=(label,fn,cls='button')=>{const b=el('button',label,cls);b.type='button';b.onclick=fn;return b;};
 async function api(path,method='GET',body){
  const response=await fetch(path,{method,headers:{'Content-Type':'application/json','X-Factory-Token':document.querySelector('meta[name=factory-token]').content},body:body===undefined?undefined:JSON.stringify(body)});
  const data=await response.json();if(!response.ok){const error=new Error(data.error||`Request failed (${response.status})`);error.status=response.status;throw error;}return data;
 }
 function usageLines(container,u){
  FactoryFormat.costLines(u||{}).forEach(text=>container.append(el('p',text,'muted')));
  for(const [key,label] of [['input_tokens','Input'],['output_tokens','Output'],['cache_read_tokens','Cache read'],['cache_write_tokens','Cache write'],['reasoning_tokens','Reasoning']])container.append(el('p',`${label} tokens: ${num(u?.[key])}`,'muted'));
 }
 const OTEL_UI='http://127.0.0.1:9119/otel';
 const otelLink=(label,params)=>{const a=el('a',label,'otel-link');a.href=OTEL_UI+'?'+new URLSearchParams(params);a.target='_blank';a.rel='noopener noreferrer';return a;};
 function renderTraces(box,traces){
  box.append(el('h3',`Traces (${traces.length})`));
  for(const t of traces){
   const d=el('details',null,'otel-trace'),sum=el('summary');
   sum.append(el('span',`${t.errors?'✕ ':''}${t.root||'trace'} · ${t.spans} spans · ${elapsed((t.duration_ms||0)/1000)}${t.start_ns?' · '+new Date(t.start_ns/1e6).toLocaleTimeString():''}`));
   d.append(sum,otelLink('Open in OTel tab ↗',{tab:'traces',trace:t.trace_id}));
   for(const s of t.tree){const row=el('p',`${s.status==='ERROR'?'✕ ':''}${s.name} · ${elapsed((s.duration_ms||0)/1000)}`,s.status==='ERROR'?'error':'muted');row.style.paddingLeft=(s.depth*14)+'px';row.style.margin='2px 0';d.append(row);}
   box.append(d);
  }
 }
 const otelNote=error=>el('p',error.status===404?'OTel source not configured (start with --hermes-home).':'OTel store unavailable.','muted');
 async function renderAttemptOtel(panel,a){
  const box=el('div',null,'otel-box');panel.append(el('h3','OpenTelemetry (hermes_otel)'),box);
  if(!a.session_id){box.append(el('p','No linked session — no spans to match.','muted'));return;}
  box.append(el('p','Loading spans…','muted'));
  try{
   const o=await api('/api/otel/sessions/'+encodeURIComponent(a.session_id));if(state.attempt!==a.key)return;box.replaceChildren();
   if(!o.spans){box.append(el('p',`No spans recorded for session ${a.session_id}.`,'muted'));return;}
   box.append(el('p',`${o.spans} spans · ${o.traces} traces · ${o.errors} errors`),el('p',`LLM calls ${o.llm_calls} · tool calls ${o.tool_calls} · tokens ${num(o.tokens)}${o.cost_usd===null?'':' · '+FactoryFormat.money(o.cost_usd)}`,'muted'));
   if(o.models.length)box.append(el('p','Models: '+o.models.join(', '),'muted'));
   const tools=Object.entries(o.tools).sort((x,y)=>y[1]-x[1]).slice(0,6);if(tools.length)box.append(el('p','Top tools: '+tools.map(([t,n])=>`${t}×${n}`).join(', '),'muted'));
   box.append(otelLink('Open session in OTel tab ↗',{tab:'traces',session:a.session_id}));
   renderTraces(box,o.trace_list||[]);
  }catch(error){if(state.attempt===a.key)box.replaceChildren(otelNote(error));}
 }
 async function renderOtelOverview(panel){
  const box=el('div',null,'otel-box');panel.append(el('h3','OpenTelemetry · last 24h'),box);
  try{
   const o=await api('/api/otel');box.replaceChildren();
   if(!o.stores.length){box.append(el('p','No hermes_otel live store found.','muted'));return;}
   const c=k=>o.counts[k]?.count||0;
   box.append(el('p',`${c('span')} spans · ${c('metric')} metrics · ${c('log')} logs stored`),el('p',`${o.traces} traces across ${o.sessions} sessions in window`,'muted'));
   for(const [fam,v] of Object.entries(o.families).sort((x,y)=>y[1].spans-x[1].spans))box.append(el('p',`${fam}: ${v.spans} spans · ${v.errors} errors · ${elapsed(v.total_ms/1000)}`,'muted'));
   for(const e of o.recent_errors){const p=el('p',`✕ ${e.name} · session ${e.session_id||'—'} `,'error');if(e.trace_id)p.append(otelLink('trace ↗',{tab:'traces',trace:e.trace_id}));box.append(p);}
   box.append(otelLink('Open OTel tab ↗',{}));
  }catch(error){box.replaceChildren(otelNote(error));}
 }
 function renderAttempt(a){
  const panel=document.getElementById('inspector');panel.replaceChildren();state.attempt=a.key;
  panel.append(el('div','ATTEMPT DETAILS','eyebrow'),el('h2',a.label),el('p',`Attempt ${a.id} · ${a.profile||'Unassigned'}`,'muted'));
  const status=el('div',null,'detail-status');status.append(el('span',a.status||'Unknown','badge'),el('span',a.verdict||a.outcome||'No verdict recorded','badge'));panel.append(status);
  panel.append(el('h3','Model used'),el('p',a.model||'Not recorded'),el('p',a.provider||'Provider not recorded','muted'));
  if(a.dispatch_selection){panel.append(el('p',`Dispatched: ${a.dispatch_selection.provider} / ${a.dispatch_selection.model} · requested effort ${a.dispatch_selection.effort||'Not recorded'} · ${a.dispatch_selection.source} · revision ${a.dispatch_selection.revision}`,'muted'));}
  panel.append(el('h3','Recorded effort'),el('p',a.effort||'Not recorded'));

  panel.append(el('h3','Timing'),el('p',`Duration: ${elapsed(a.duration)}`));
  for(const [key,label] of [['started_at','Started'],['ended_at','Ended']])panel.append(el('p',`${label}: ${a[key]===null||a[key]===undefined?'Not recorded':new Date(a[key]*1000).toLocaleString()}`,'muted'));
  panel.append(el('h3','Usage & cost'));usageLines(panel,a.usage);
  if(a.summary){panel.append(el('h3','Summary'),el('pre',a.summary));}if(a.error)panel.append(el('p',a.error,'error'));
  renderAttemptOtel(panel,a);
  document.querySelectorAll('[data-attempt]').forEach(n=>n.classList.toggle('selected',n.dataset.attempt===a.key));
 }
 function renderOverview(root){
  const panel=document.getElementById('inspector');panel.replaceChildren();
  panel.append(el('div','RUN OVERVIEW','eyebrow'),el('h2','Delivery & evidence'),el('p',root.block_reason||'Select an execution bar to inspect an attempt.','muted'));
  if(root.requested_settings){const captured=root.requested_settings;panel.append(el('h3','Captured task settings'),el('p',`${captured.origin==='legacy_migration'?'Legacy settings captured':'Captured'} ${new Date(captured.captured_at).toLocaleString()} · revision ${captured.revision}`,'muted'),el('p','Requested settings; recorded session evidence is shown on each attempt.','muted'));for(const [role,value] of Object.entries(captured.roles))panel.append(el('p',`${role}: ${value.provider} / ${value.model} · effort ${value.effort}`,'muted'));}
  panel.append(el('h3','Latest verification'),el('p',root.latest_verification||'Not recorded'));
  if(root.delivery?.url){try{const url=new URL(root.delivery.url);if(['http:','https:'].includes(url.protocol)){const a=el('a','Open recorded delivery','delivery');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';panel.append(a);}}catch{}}
  panel.append(el('h3','Usage coverage'),el('p',`${root.usage?.linked_attempts||0} / ${root.usage?.attempts||0} attempts linked`,'muted'));usageLines(panel,root.usage);
  const warnings=state.report.warnings||[];if(warnings.length)panel.append(el('p',`${warnings.length} source warnings. Missing data remains unavailable.`,'error'));
  renderOtelOverview(panel);
 }
 function render(){
  if(!state.report||state.editing)return;
  const oldScroll=document.querySelector('.timeline-scroll')?.scrollLeft||0;
  const report=state.report;main.replaceChildren();
  const heading=el('div',null,'page-heading');const words=el('div');words.append(el('div','WORKSPACE / EXECUTIONS','eyebrow'),el('h1','Software factory'),el('p','Follow the work. Understand every handoff.','subtitle'));heading.append(words,el('span',report.demo?'DEMO WORKSPACE':'LOCAL WORKSPACE','workspace-badge'));main.append(heading);if(report.configuration.snapshot_mode){
   const context={api,onOpen:()=>{state.editing=true;},onClose:()=>{state.editing=null;refresh();},onSubmitted:result=>{state.pendingSubmission=result.submission_id;if(result.root_id)state.selected=result.root_id;}};
   if(report.configuration.workflow_templates)heading.append(button('Workflows',()=>FactoryWorkflowForms.openEditor(context),'button secondary'));
   context.workflows=!!report.configuration.workflow_templates;
   heading.append(button('Defaults for new tasks',()=>FactoryTaskForms.openDefaults(context),'button secondary'),button('New task',()=>FactoryTaskForms.openNewTask(context),'button primary'));
  }
  const running=report.parents.flatMap(r=>[r,...r.stages]).flatMap(t=>t.attempts||[]).filter(a=>a.status==='running');
  main.append(el('p',running.length?`Running now: ${running.map(a=>`${a.profile} · ${a.model||'model not recorded'} · effort ${a.effort||'not recorded'}`).join(' / ')}`:'No Factory attempts running now','subtitle'));
  const banner=el('div',report.configuration.mode,'preview-banner');main.append(banner);
  const layout=el('div',null,'workspace-layout'),sidebar=el('aside',null,'task-sidebar');
  const sideHead=el('div',null,'section-head');sideHead.append(el('h2','Tasks'),el('span',String(report.parents.length),'count'));sidebar.append(sideHead);
  const search=el('input');search.type='search';search.placeholder='Find a task…';search.value=state.query;search.setAttribute('aria-label','Search tasks');
  const filter=el('select');filter.setAttribute('aria-label','Filter task status');for(const value of ['all','running','blocked','done']){const opt=el('option',value==='all'?'All statuses':value);opt.value=value;filter.append(opt);}filter.value=state.filter;
  for(const submission of report.submissions||[]){if(!submission.root_id)sidebar.append(el('p',`${submission.title} · ${submission.state} · ${submission.ticket_id||'preparing'}`,'queued-chip'));}
  sidebar.append(search,filter);const list=el('div',null,'task-list');sidebar.append(list);
  function renderList(){list.replaceChildren();report.parents.filter(r=>(state.filter==='all'||r.status===state.filter)&&r.title.toLowerCase().includes(state.query.toLowerCase())).forEach(root=>{
   const b=button('',()=>{state.selected=root.id;state.attempt=null;state.editing=null;render();},'task-item'+(state.selected===root.id?' active':''));
   b.dataset.focusKey='task:'+root.id;
   b.append(el('span',root.status,'task-state '+root.status),el('strong',root.title.replace(/^FACTORY:\s*/,'')),el('small',`${root.stages.length} stages · ${root.execution_retries} retries`));b.append(el('small','Run: '+dateLabel(runStart(root))));list.append(b);
  });if(!list.children.length)list.append(el('p','No matching tasks.','muted'));}
  search.oninput=()=>{state.query=search.value;renderList();};filter.onchange=()=>{state.filter=filter.value;renderList();};renderList();
  sidebar.append(el('p',`${report.unlinked_tasks.length} unlinked tasks · ${report.coverage?.missing_attempts||0} attempts without usage links`,'sidebar-note'));
  const center=el('section',null,'run-panel');layout.append(sidebar,center);main.append(layout);
  const root=report.parents.find(r=>r.id===state.selected)||report.parents[0];
  if(!root){center.append(el('h2','No Factory tasks recorded'),el('p','Select a board containing Factory parent tasks.','muted'));return;}
  state.selected=root.id;
  const runHead=el('div',null,'run-heading');const title=el('div');title.append(el('div',`${root.id} / TIMELINE`,'eyebrow'),el('h2',root.title.replace(/^FACTORY:\s*/,'')));runHead.append(title,el('span',root.status,'badge status-'+root.status));center.append(runHead);center.append(el('p','Run started: '+dateLabel(runStart(root)),'subtitle'));if(root.project&&root.project.dir){const pr=root.project;center.append(el('p','Repo: '+(pr.repo||'unknown')+' · '+pr.dir+(pr.exists?'':' (folder not found)')+(pr.mode?' · '+pr.mode+' project':''),'subtitle'));}
  if(root.workflow)FactoryWorkflowForms.renderSummary(center,root.workflow);
  const metrics=el('div',null,'metrics');for(const [label,value] of [['Elapsed',elapsed(root.duration_seconds)],['Recorded estimate',root.usage?.estimated_usd===null?'Unavailable':FactoryFormat.money(root.usage?.estimated_usd)],['Input tokens',num(root.usage?.input_tokens)],['Output tokens',num(root.usage?.output_tokens)],['Attempts linked',`${root.usage?.linked_attempts||0}/${root.usage?.attempts||0}`]]){const item=el('div',null,'metric');item.append(el('span',label),el('strong',value));metrics.append(item);}center.append(metrics);
  const toolbar=el('div',null,'timeline-toolbar');toolbar.append(el('span','EXECUTION TIMELINE','eyebrow'));
  center.append(toolbar);
  const scroll=el('div',null,'timeline-scroll'),canvas=el('div',null,'timeline-canvas');scroll.append(canvas);center.append(scroll);
  const timeline=buildTimeline(root,Date.now());
  renderTimeline(canvas,timeline,a=>{if(!state.editing)renderAttempt(a);});
  center.append(el('p',`Bars show recorded attempts. ${timeline.unrecorded.length} completed tasks have no recorded attempts. Model and effort are read-only session evidence; costs reflect linked sessions only.`,'timeline-note'));
  const inspector=el('aside',null,'inspector');inspector.id='inspector';layout.append(inspector);
  const selected=timeline.attempts.find(a=>a.key===state.attempt);if(selected)renderAttempt(selected);else renderOverview(root);
  scroll.scrollLeft=oldScroll;
  const footer=el('footer',null,'page-footer');footer.append(el('span',`Board ${report.board.id} · Snapshot ${new Date(report.generated_at).toLocaleString()}`),el('span','Local data · No provider calls on refresh'));main.append(footer);
 }
 async function refresh(){
  if(state.busy||document.hidden)return;
  state.busy=true;
  try{
   const report=await api('/api/report');state.report=report;
   const pending=(report.submissions||[]).find(s=>s.submission_id===state.pendingSubmission);if(pending?.root_id){state.selected=pending.root_id;state.pendingSubmission=null;}state.lastRefresh=new Date();
   if(!state.selected)state.selected=report.parents[0]?.id;
   const active=document.activeElement,focusKey=active?.dataset.focusKey,attemptKey=active?.dataset.attempt;
   const paused=state.editing||['INPUT','SELECT'].includes(active?.tagName);
   if(!paused){
    render();
    if(focusKey||attemptKey){const replacement=[...main.querySelectorAll('button')].find(b=>focusKey?b.dataset.focusKey===focusKey:b.dataset.attempt===attemptKey);replacement?.focus({preventScroll:true});}
   }
   connection.classList.remove('stale');connection.textContent=paused?'● Refresh paused while editing':`● Updated ${state.lastRefresh.toLocaleTimeString()}`;
  }catch(error){connection.classList.add('stale');connection.textContent=`Refresh failed · ${state.lastRefresh?'last updated '+state.lastRefresh.toLocaleTimeString():'no data yet'}`;if(!state.report)main.replaceChildren(el('p',error.message,'error'));}
  finally{state.busy=false;}
 }
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 setInterval(refresh,2000);refresh();
})();
