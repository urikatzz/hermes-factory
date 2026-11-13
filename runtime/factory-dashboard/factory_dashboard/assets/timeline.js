'use strict';
const FactoryTimeline = (() => {
 const colors=['#b5a0ff','#6ed6dc','#ed9db9','#e1b779','#8bd3a8','#9fb8ee'];
 const valid=n=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
 const elapsed=n=>n===null?'Unknown':n<60?`${Math.round(n)}s`:`${Math.floor(n/60)}m ${Math.round(n%60)}s`;
 function buildTimeline(root,nowMillis){
  const lanes=[],byRole=new Map(),attempts=[],unrecorded=[];
  const laneFor=role=>{if(!byRole.has(role)){const lane={id:role,label:role,color:colors[lanes.length%colors.length],attempts:[],queued:[]};byRole.set(role,lane);lanes.push(lane);}return byRole.get(role);};
  for(const task of [root,...(root.stages||[])]){
   const title=task.stage?.label||'Orchestrate';
   for(const a of task.attempts||[]){
    const start=valid(a.started_at)?a.started_at:null;
    const end=valid(a.ended_at)?a.ended_at:(a.status==='running'&&start!==null?nowMillis/1000:null);
    const duration=start!==null&&end!==null&&end>=start?end-start:null;
    const item={...a,key:`${task.id}:${a.id}`,label:title,start,end:duration===null?null:end,duration,track:0};
    laneFor(a.profile||task.assignee||'Unassigned').attempts.push(item);attempts.push(item);
   }
   if(!(task.attempts||[]).length&&task.assignee){
    if(['done','archived'].includes(task.status))unrecorded.push(task.id);

   }
  }
  for(const lane of lanes){
   const ends=[];
   for(const a of lane.attempts.filter(a=>a.duration!==null).sort((a,b)=>(a.start??Infinity)-(b.start??Infinity))){
    let track=ends.findIndex(end=>a.start!==null&&end<=a.start);
    if(track<0)track=ends.length;
    a.track=track;ends[track]=a.end??Infinity;
   }
   lane.tracks=Math.max(1,ends.length);
  }
  const events=(root.timeline||[]).filter(e=>valid(e.timestamp));
  const times=attempts.flatMap(a=>[a.start,a.end]).concat(events.map(e=>e.timestamp)).filter(valid);
  const start=times.length?Math.min(...times):nowMillis/1000;
  const end=times.length?Math.max(...times):start+60;
  return {lanes,attempts,events,unrecorded,start,end:Math.max(start+60,end)};
 }
 function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined&&text!==null)node.textContent=text;if(className)node.className=className;return node;}
 function renderTimeline(container,timeline,onSelectAttempt){
  container.replaceChildren();
  const span=timeline.end-timeline.start;
  const head=el('div',null,'timeline-row axis-row');head.append(el('div','AGENT / MODEL','lane-label axis-label'));
  const axis=el('div',null,'lane-track axis');
  for(let i=0;i<=6;i++){const tick=el('span',elapsed(span*i/6),'tick');tick.style.left=`${i/6*100}%`;axis.append(tick);}head.append(axis);container.append(head);
  if(timeline.events.length){
   const row=el('div',null,'timeline-row event-row');row.append(el('div','Recorded events','lane-label'));
   const track=el('div',null,'lane-track');
   timeline.events.forEach(e=>{const mark=el('span',null,'event-mark');mark.style.left=`${(e.timestamp-timeline.start)/span*100}%`;mark.title=`${e.kind} · ${new Date(e.timestamp*1000).toLocaleString()}`;track.append(mark);});
   row.append(track);container.append(row);
  }
  for(const lane of timeline.lanes){
   const row=el('div',null,'timeline-row');row.style.setProperty('--lane-color',lane.color);
   const label=el('div',null,'lane-label');const role=el('strong',lane.label,'role-name');label.append(role);
   const pairs=[...new Set(lane.attempts.map(a=>`${a.model||'Not recorded'} · effort ${a.effort||'Not recorded'}`))];
   label.append(el('small',pairs.length>1?'Multiple recorded settings':'Recorded settings','model-source'));
   for(const pair of pairs)label.append(el('span',pair,'model-link'));
   row.append(label);const track=el('div',null,'lane-track');track.style.minHeight=`${Math.max(120,lane.tracks*85+30)}px`;
   for(const a of lane.attempts){
    if(a.duration===null)continue;
    const button=el('button',null,'phase '+(a.status||'unknown'));button.type='button';button.dataset.attempt=a.key;
    const start=a.start===null?0:(a.start-timeline.start)/span*100;
    button.style.left=`${Math.min(97,Math.max(0,start))}%`;
    button.style.width=`${a.duration===null?14:Math.max(3,Math.min(100-start,a.duration/span*100))}%`;
    button.style.top=`${15+a.track*85}px`;
    button.title=`${a.label} · attempt ${a.id} · ${a.model||'Not recorded'} · effort ${a.effort||'Not recorded'} · ${elapsed(a.duration)}`;
    const top=el('div',null,'phase-top');top.append(el('strong',a.label),el('span',elapsed(a.duration)));button.append(top,el('div',a.verdict||a.outcome||a.status,'phase-state'),el('div',(a.model||'Model unavailable')+' · effort '+(a.effort||'not recorded'),'phase-model'));
    button.setAttribute('aria-label',button.title);button.addEventListener('click',()=>onSelectAttempt(a));track.append(button);
   }
   if(lane.queued.length){const queued=el('div',null,'queued');if(lane.attempts.length)queued.style.marginTop=`${lane.tracks*85+30}px`;lane.queued.forEach(q=>queued.append(el('span',`${q.label} · ${q.status||'No recorded attempt'}`,'queued-chip')));track.append(queued);}
   const unknown=lane.attempts.filter(a=>a.duration===null);
   if(unknown.length){const list=el('div',null,'unknown-attempts');list.style.marginTop=`${lane.tracks*85+25}px`;list.append(el('small','Timing unavailable'));
    for(const a of unknown){const b=el('button',`${a.label} · attempt ${a.id} · ${a.status}`,'button secondary');b.type='button';b.dataset.attempt=a.key;b.onclick=()=>onSelectAttempt(a);list.append(b);}track.append(list);}
   row.append(track);container.append(row);
  }
  if(!timeline.lanes.length)container.append(el('p','No recorded agent attempts.','empty'));
 }
 return {buildTimeline,renderTimeline,elapsed,el};
})();
if(typeof module!=='undefined'&&module.exports)module.exports=FactoryTimeline;
