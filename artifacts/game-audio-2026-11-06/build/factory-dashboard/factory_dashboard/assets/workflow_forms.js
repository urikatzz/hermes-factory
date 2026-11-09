'use strict';
const FactoryWorkflowForms=(()=>{
 const allowedProfiles=(capabilities,kind)=>Object.keys(capabilities).filter(p=>capabilities[p].includes(kind));
 function selection(data,type){
  let chosen=data.defaults.templates[type],explicit=false;
  return {choose(id){chosen=id;explicit=true;},changeType(value){type=value;if(!explicit)chosen=data.defaults.templates[type];},
   refresh(updated){data=updated;if(!explicit)chosen=data.defaults.templates[type];},
   value(){const d=data.templates.find(t=>t.template_id===chosen);if(!d||d.archived)throw new Error('Choose an active workflow');return {workflow_id:d.template_id,workflow_revision:d.revision,workflow_defaults_revision:data.defaults.revision};},
   definition(){return data.templates.find(t=>t.template_id===chosen);},mismatch(){return this.definition()?.task_type!==type;}};
 }
 function summaryText(workflow){
  if(!workflow||workflow.legacy)return 'Legacy workflow';
  const d=workflow.definition||workflow;
  return `${d.name} · revision ${d.revision}\n${d.prepare.profile} → ${d.implement.profile} → [${d.reviewers.map(r=>r.profile).join(' + ')} + ${d.verify.profile}]\nRepair: ${d.repair.profile} · up to ${d.max_repairs} cycles`;
 }
 function renderSummary(container,workflow){
  const {el}=FactoryTimeline;
  const box=el('section',null,'workflow-summary');box.append(el('h3','Captured workflow'),el('pre',summaryText(workflow)));
  if(workflow?.state)box.append(el('p',`${workflow.state.phase} · ${workflow.state.reason||''}`,'muted'));
  box.append(el('p','Planned stages. The timeline below shows recorded runs only.','muted'));container.append(box);
 }
 async function openEditor(context){
  const {el}=FactoryTimeline;context.onOpen();
  const dialog=el('dialog',null,'profile-dialog workflow-dialog');dialog.append(el('h2','Workflow templates'),el('p','Saved revisions apply to new tasks. Existing tasks keep their captured workflow.','muted'));
  const feedback=el('p',null,'form-feedback');feedback.setAttribute('role','status');
  const choose=el('select');choose.setAttribute('aria-label','Workflow template');
  const form=el('div',null,'workflow-editor'),controls=el('div',null,'form-controls');
  dialog.append(choose,form,feedback,controls);document.body.append(dialog);dialog.showModal();
  let data,documentValue,busy=false;
  function close(){if(busy)return;dialog.close();dialog.remove();context.onClose();}
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  function button(label,action){const b=el('button',label,'button');b.type='button';b.onclick=async()=>{if(busy)return;busy=true;controls.querySelectorAll('button').forEach(x=>x.disabled=true);try{await action();}catch(error){feedback.textContent=error.message;}finally{busy=false;controls.querySelectorAll('button').forEach(x=>x.disabled=false);}};controls.append(b);return b;}
  function field(parent,label,tag,value,options){const wrapper=el('label',label),input=el(tag);if(options)for(const item of options){const o=el('option',item);o.value=item;input.append(o);}input.value=value??'';wrapper.append(input);parent.append(wrapper);return input;}
  function draw(doc){
   documentValue=structuredClone(doc);delete documentValue.archived;form.replaceChildren();
   const name=field(form,'Name','input',doc.name);name.maxLength=100;name.oninput=()=>documentValue.name=name.value;
   const description=field(form,'Description','textarea',doc.description);description.maxLength=1000;description.oninput=()=>documentValue.description=description.value;
   const type=field(form,'Suggested task type','select',doc.task_type,['feature','bug','chore','art','audio']);type.onchange=()=>documentValue.task_type=type.value;
   for(const [key,label] of [['prepare','1 · Preparation'],['implement','2 · Implementation'],['verify','Independent verification'],['repair','Repair after failed review']]){
    const section=el('fieldset');section.append(el('legend',label));form.append(section);
    const profile=field(section,'Profile','select',doc[key].profile,allowedProfiles(data.capabilities,key));profile.onchange=()=>documentValue[key].profile=profile.value;
    const notes=field(section,'Instructions','textarea',doc[key].instructions);notes.maxLength=4000;notes.oninput=()=>documentValue[key].instructions=notes.value;
   }
   const reviews=el('fieldset');reviews.append(el('legend','3 · Parallel review panel'));form.append(reviews);
   for(const profile of allowedProfiles(data.capabilities,'review')){
    const existing=doc.reviewers.find(r=>r.profile===profile),row=el('label',profile),check=el('input');check.type='checkbox';check.checked=!!existing;row.prepend(check);reviews.append(row);
    const notes=field(reviews,`${profile} focus`,'textarea',existing?.instructions||'');notes.maxLength=4000;notes.disabled=!check.checked;
    const update=()=>{documentValue.reviewers=documentValue.reviewers.filter(r=>r.profile!==profile);if(check.checked)documentValue.reviewers.push({key:existing?.key||profile,kind:'review',profile,instructions:notes.value});notes.disabled=!check.checked;};check.onchange=update;notes.oninput=update;
   }
   const limit=field(form,'Maximum repair cycles','select',doc.max_repairs,['0','1','2','3']);limit.onchange=()=>documentValue.max_repairs=Number(limit.value);
   form.append(el('p',doc.template_id?`Editing revision ${doc.revision}. Save creates a new revision.`:'New template · not saved yet.','muted'));
  }
  async function load(id){data=await context.api('/api/workflows');choose.replaceChildren();for(const d of data.templates){const o=el('option',`${d.name} · r${d.revision}${d.archived?' · archived':''}`);o.value=d.template_id;choose.append(o);}if(id)choose.value=id;if(!choose.value)choose.selectedIndex=0;draw(data.templates.find(t=>t.template_id===choose.value));feedback.textContent=data.enabled?'Workflow execution is active.':'Templates can be edited; execution is awaiting activation.';}
  choose.onchange=()=>draw(data.templates.find(t=>t.template_id===choose.value));
  button('Save revision',async()=>{const d=documentValue;const saved=await context.api('/api/workflows'+(d.template_id?'/'+d.template_id:''),d.template_id?'PUT':'POST',d);await load(saved.template_id);feedback.textContent='Saved for new tasks.';});
  button('New / duplicate',()=>{const d=structuredClone(documentValue);delete d.template_id;delete d.revision;d.name+=' copy';draw(d);});
  button('Use as type default',async()=>{if(!documentValue.template_id)throw new Error('Save the template first');await context.api('/api/workflow-defaults/'+documentValue.task_type,'PUT',{template_id:documentValue.template_id,revision:data.defaults.revision});await load(documentValue.template_id);});
  button('Archive / restore',async()=>{const d=data.templates.find(t=>t.template_id===documentValue.template_id);if(!d)throw new Error('Save the template first');await context.api(`/api/workflows/${d.template_id}/${d.archived?'restore':'archive'}`,'POST',{revision:d.revision});await load(d.template_id);});
  button('Reload',()=>load(documentValue?.template_id));
  const closeButton=el('button','Close','button');closeButton.type='button';closeButton.onclick=close;controls.append(closeButton);
  try{await load();}catch(error){feedback.textContent=error.message;}
 }
 return {openEditor,renderSummary,summaryText,allowedProfiles,selection};
})();
if(typeof module!=='undefined')module.exports=FactoryWorkflowForms;
