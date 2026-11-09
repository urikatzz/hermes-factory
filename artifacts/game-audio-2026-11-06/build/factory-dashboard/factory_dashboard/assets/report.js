'use strict';
(() => {
const report = JSON.parse(document.getElementById('report-data').textContent);
const get = id => document.getElementById(id);
const el = (tag, text, cls) => { const n=document.createElement(tag); if(text!==undefined&&text!==null)n.textContent=String(text); if(cls)n.className=cls; return n; };
const fmt = n => typeof n==='number' ? new Intl.NumberFormat('en-US',{maximumFractionDigits:2}).format(n) : '—';
const money = n => typeof n==='number' ? FactoryFormat.money(n) : 'Unavailable';
const date = n => typeof n==='number' ? new Date(n*1000).toLocaleString() : 'Time not recorded';
const duration = n => typeof n!=='number' ? 'Not recorded' : n<60 ? Math.round(n)+'s' : n<3600 ? Math.round(n/60)+'m' : (n/3600).toFixed(1)+'h';
const badge = (value) => el('span',value||'Not recorded','badge '+String(value||'').toLowerCase().replace(/[^a-z_]/g,''));
const append = (node,...kids) => {kids.forEach(k=>node.append(k));return node;};
function fact(label,value){return append(el('div',null,'fact'),el('label',label),el('strong',value??'Not recorded'));}
function link(url){try{const u=new URL(url);if(!['http:','https:'].includes(u.protocol)||u.username||u.password)return null;const a=el('a',url);a.href=u.href;a.target='_blank';a.rel='noopener noreferrer';return a;}catch{return null;}}
function costBlock(u){const n=el('div',null,'cost-breakdown');FactoryFormat.costLines(u).forEach(line=>n.append(el('div',line,'code')));return n;}
function usageCoverage(u){return `${u.linked_attempts??0}/${u.attempts??0} attempts linked · ${u.missing_attempts??0} unavailable`;}

function tokens(u){const box=el('div',null,'token-grid');[['Input','input_tokens'],['Output','output_tokens'],['Cache read','cache_read_tokens'],['Cache write','cache_write_tokens'],['Reasoning','reasoning_tokens']].forEach(([name,key])=>{const n=fact(name,fmt(u[key]));n.append(el('div',`${u[key+'_known_sessions']??0}/${u.sessions} sessions`,'code'));box.append(n);});return box;}
const u=report.summary.usage,c=report.coverage;
get('snapshot-info').append(el('strong','BOARD / '+report.board.id),el('div','Generated '+new Date(report.generated_at).toLocaleString()),el('div','Regenerate this file to refresh'));
const cards=[['Known actual spend',money(u.actual_usd),`${u.actual_known_sessions} of ${u.sessions} linked sessions report actual USD`],['Recorded estimates',money(u.estimated_usd),`${u.estimated_known_sessions} sessions · separate from actual spend`],['Subscription included',fmt(u.included_sessions)+' sessions','Dollar amount unavailable for included usage'],['Usage coverage',`${c.linked_attempts} / ${c.attempts}`,`${c.missing_attempts} attempts unavailable · ${c.shared_sessions} shared sessions`]];
cards.forEach(([name,value,note])=>get('summary').append(append(el('div',null,'stat-card'),el('div',name,'stat-label'),el('div',value,'stat-value'),el('div',note,'stat-note'))));
const metric=[['Parent tasks',fmt(report.summary.root_count)],['Card completion',report.summary.card_completion_rate===null?'—':(report.summary.card_completion_rate*100).toFixed(0)+'%'],['Median completed cycle',duration(report.summary.median_cycle_seconds)],['Execution retries',fmt(report.summary.execution_retries)],['Failed attempts',fmt(report.summary.failed_attempts)],['Blocked tasks',fmt(report.summary.blocked_tasks)],['Active attempts',fmt(report.summary.active_attempts)],['Failed verdicts without attempts',fmt(report.summary.failed_stage_verdicts_without_attempt)]];
Object.entries(report.summary.roots_by_status).forEach(([status,count])=>metric.push(['Roots '+status,fmt(count)]));
metric.forEach(([name,value])=>get('metrics').append(append(el('span'),el('strong',value+' '),document.createTextNode(name))));
const all=[...report.parents.map(t=>({...t,isParent:true})),...report.unlinked_tasks.map(t=>({...t,isParent:false}))];
let selected=all[0]?.id;
[...new Set(all.map(t=>t.status).filter(Boolean))].sort().forEach(s=>{const o=el('option',s);o.value=s;get('status-filter').append(o);});
function renderList(){
 const list=get('task-list');
 const focused=document.activeElement?.dataset?.taskId;
 list.replaceChildren();
 const query=get('search').value.toLowerCase(),status=get('status-filter').value;
 const visible=all.filter(t=>(status==='all'||t.status===status)&&[t.title,t.id,t.assignee,t.block_reason].filter(Boolean).join(' ').toLowerCase().includes(query));
 if(!visible.some(t=>t.id===selected)){selected=visible[0]?.id;renderDetail(visible[0]);}
 get('task-count').textContent=visible.length;
 if(!visible.length)list.append(el('p',all.length?'No matching tasks.':'No tasks recorded.','empty'));
 for(const parent of [true,false]){
  const group=visible.filter(t=>t.isParent===parent);if(!group.length)continue;
  list.append(el('p',parent?'PARENT TASKS':'UNLINKED TASKS','list-label'));
  group.forEach(t=>{const b=el('button',null,'task-button');b.type='button';b.dataset.taskId=t.id;b.setAttribute('aria-pressed',String(t.id===selected));
   b.append(el('span',t.title,'task-title'),append(el('span',null,'task-meta'),el('span',t.id),badge(t.status)),el('span',t.isParent?`${t.stages.length} stages · ${t.execution_retries} retries · ${duration(t.duration_seconds)}`:'No established parent · '+(t.assignee||'Unassigned'),'task-extra'));
   if(t.block_reason)b.append(el('span','Blocked: '+t.block_reason,'task-extra'));
   if(t.isParent){b.append(el('span',usageCoverage(t.usage),'task-extra'),el('span',FactoryFormat.costLines(t.usage).join(' · '),'task-extra'),el('span','Delivery: '+t.delivery.state,'task-extra'));}
   b.addEventListener('click',()=>{selected=t.id;renderList();renderDetail(t);});list.append(b);
  });
 }
 if(focused){const button=[...list.querySelectorAll('button')].find(b=>b.dataset.taskId===focused);if(button)button.focus();}
}
function attemptView(a){
 const n=el('div',null,'attempt');n.append(append(el('div',null,'attempt-head'),el('strong','Attempt '+a.id),el('span',a.profile||'Profile not recorded','code'),badge(a.status),badge(a.verdict||a.outcome)));
 n.append(el('p',`${date(a.started_at)} · ${duration(a.duration_seconds)} · ${a.model||'Model unavailable'} · ${a.provider||'Provider unavailable'}`));
 if(a.error)n.append(el('div',a.error,'notice'));
 if(a.usage_state==='unavailable')n.append(el('p','Usage unavailable — no unambiguous worker session link.'));
 else {if(a.usage_state==='shared')n.append(el('div','Shared session: values below describe the whole session, not this attempt. Counted once overall.','notice'));n.append(costBlock(a.usage),tokens(a.usage),el('div','Session '+a.session_id,'code'));}
 if(a.timeout_seconds)n.append(el('p',`Recorded command/run limit: ${a.timeout_seconds}s`));
 if(a.summary){const d=el('details');d.append(el('summary','Recorded summary'),el('pre',a.summary));n.append(d);}return n;
}
function taskCard(t){
 const n=el('article',null,'stage-card');n.append(append(el('div',null,'stage-header'),el('strong',t.stage.label+(t.stage.cycle?' · cycle '+t.stage.cycle:'')),append(el('div',null,'chips'),badge(t.status),...(t.verdict?[badge(t.verdict)]:[]))));
 n.append(el('div',`${t.id} · ${t.assignee||'Unassigned'} · ${t.attempts.length} recorded attempts`,'stage-sub'));
 if(t.block_reason)n.append(el('div',t.block_reason,'notice'));
 if(!t.attempts.length)n.append(el('p','No attempt or usage record.','code'));
 t.attempts.forEach(a=>n.append(attemptView(a)));
 t.artifacts.forEach(a=>n.append(el('div','Manifest '+a.manifest+' · run '+a.run_id,'code')));
 t.sandbox.forEach(e=>n.append(el('div',`Sandbox cleanup: ${e.result.cleanup_outcome||'Not finalized'} · ${e.result.result_path||'No retained result recorded'}`,'code')));return n;
}
function renderDetail(t){
 const detail=get('detail');detail.replaceChildren();if(!t){detail.append(el('p','Select a task to inspect its records.','empty'));return;}
 const head=append(el('div',null,'detail-top'),append(el('div'),el('div',t.isParent?'PARENT RUN':'UNLINKED TASK','eyebrow'),el('h2',t.title,'detail-title'),el('div',t.id,'code')),badge(t.status));detail.append(head);
 if(!t.isParent)detail.append(el('p','No established parent is recorded for this task.','code'));
 if(t.block_reason)detail.append(el('div',t.block_reason,'notice'));
 const facts=append(el('div',null,'fact-grid'),fact('Elapsed',duration(t.duration_seconds)),fact('Assigned to',t.assignee),fact('Recorded verdict',t.verdict),fact('Latest independent verification',t.latest_verification),fact('Recorded branch',t.branch),fact('Repository checks / merge','Not established by this report'));detail.append(facts);
 detail.append(el('h3','Usage attributable to this task'),costBlock(t.usage),el('p',usageCoverage(t.usage),'code'),tokens(t.usage));
 if(t.usage.shared_sessions)detail.append(el('div',`${t.usage.shared_sessions} shared session(s) excluded from task allocation. See shared usage below.`,'notice'));
 if(t.isParent){detail.append(el('h3',`Stages & attempts · ${t.stages.length} stages · ${t.fix_stages} fix stages`));if(t.attempts.length)detail.append(taskCard({...t,stage:{label:'Root task',cycle:null}}));t.stages.forEach(s=>detail.append(taskCard(s)));if(!t.stages.length)detail.append(el('p','No linked stages recorded.','empty'));}
 else detail.append(taskCard(t));
 const timeline=el('details');timeline.open=true;timeline.append(el('summary',`Recorded timeline · ${t.timeline.length} events`));const ul=el('ol',null,'timeline');
 t.timeline.forEach(e=>{const li=el('li');li.append(el('strong',e.kind||'Unknown event'),el('div',`${date(e.timestamp)} · ${e.source} · ${e.task_id} / run ${e.run_id??'not recorded'}`,'code'));if(Object.keys(e.details).length)li.append(el('pre',JSON.stringify(e.details,null,2),'event-detail'));ul.append(li);});
 timeline.append(ul);if(!t.timeline.length)timeline.append(el('p','No events recorded. This is not a complete trace of agent actions.','code'));detail.append(timeline);
 if(t.delivery){detail.append(el('h3','Delivery evidence'));const a=link(t.delivery.url);detail.append(a||el('p','Delivery URL: Not recorded','code'));if(a)detail.append(el('p','Recorded URL only. Merge and check status are not established.','code'));}
}
get('search').addEventListener('input',renderList);get('status-filter').addEventListener('change',renderList);
renderList();renderDetail(all[0]);
get('warning-count').textContent=report.warnings.length+' warnings';
get('coverage').append(el('p',`${c.linked_attempts} of ${c.attempts} attempts have worker-session usage. ${c.unique_sessions} unique sessions counted overall; ${c.shared_sessions} shared. Missing usage is not treated as zero.`),tokens(u),el('p','Card completion = done roots / non-archived roots. Median cycle = creation to completion for valid completed roots. Retries = extra recorded attempts per child stage; FIX stages are separate. Failed attempts = explicit failed/blocked/error outcome or failed stage verdict, counted once per attempt.'));
report.shared_sessions.forEach(s=>{const n=el('div',null,'source-row');n.append(el('strong','Shared session '+s.session_id),el('p',(s.profile_aliases||[s.profile]).join(', ')),costBlock(s.usage),el('div',s.references.map(r=>r.task_id+'/run '+r.run_id).join(' · '),'code'));get('shared').append(n);});
report.sources.forEach(s=>get('sources').append(append(el('div',null,'source-row'),el('div',s.path,'code'),el('div',`${s.status} · read ${s.read_at}`))));
report.warnings.forEach(w=>get('warnings').append(el('div',`${w.kind} · ${w.source}${w.record!==undefined&&w.record!==null?' · '+w.record:''}`,'warning')));
if(report.warnings.length)get('source-details').open=true;
})();
