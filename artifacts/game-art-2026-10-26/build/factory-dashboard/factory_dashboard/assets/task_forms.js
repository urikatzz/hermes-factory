'use strict';
const FactoryTaskForms=(()=>{
 const {el}=FactoryTimeline;
 const button=(text,fn)=>{const b=el('button',text,'button');b.type='button';b.onclick=fn;return b;};
 function modal(context,title){
  context.onOpen();const dialog=el('dialog',null,'profile-dialog');dialog.append(el('h2',title));
  const feedback=el('p',null,'form-feedback');feedback.setAttribute('role','status');
  const controls=el('div',null,'form-controls');
  let busy=false;
  function close(){if(busy)return;dialog.close();dialog.remove();context.onClose();}
  controls.append(button('Close',close));
  dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  document.body.append(dialog);dialog.showModal();
  return {dialog,feedback,controls,close,setBusy(value){busy=value;controls.querySelectorAll('button').forEach(b=>b.disabled=value);}};
 }
 function field(dialog,label,tag='input'){
  const wrapper=el('label',label),input=el(tag);wrapper.append(input);dialog.append(wrapper);return input;
 }
 function options(select,values,current){select.replaceChildren();for(const [value,label] of values){const option=el('option',label);option.value=value;select.append(option);}if(current!==undefined)select.value=current;}
 async function openDefaults(context){
  const m=modal(context,'Defaults for new tasks');
  m.dialog.append(el('p','Changes apply only to tasks submitted or created after saving. Existing tasks, later stages and retries keep their captured settings.','muted'));
  const role=field(m.dialog,'Profile','select'),model=field(m.dialog,'Provider / model','select'),effort=field(m.dialog,'Reasoning effort','select');
  let data;
  function populate(){const current=data.roles[role.value];options(model,data.role_choices[role.value].map(v=>[JSON.stringify(v),`${v.provider} / ${v.model}`]),JSON.stringify({provider:current.provider,model:current.model}));options(effort,data.effort_choices.map(v=>[v,v]),current.effort);}
  async function reload(){data=await context.api('/api/defaults');options(role,Object.keys(data.roles).sort().map(v=>[v,v]),role.value||undefined);if(!role.value)role.selectedIndex=0;populate();save.disabled=!data.activation.enabled;m.feedback.textContent=data.activation.enabled?'Saved defaults for new tasks.':'Read-only until snapshot enforcement is active.';}
  role.onchange=populate;
  const save=button('Save defaults',async()=>{
   m.setBusy(true);
   try{data=await context.api('/api/defaults/'+encodeURIComponent(role.value),'PUT',{revision:data.revision,selection:JSON.parse(model.value),effort:effort.value});m.feedback.textContent='Saved. Existing task settings are unchanged.';}
   catch(error){m.feedback.textContent=error.message+' Reload defaults before retrying.';}
   finally{m.setBusy(false);save.disabled=!data?.activation.enabled;}
  });
  m.controls.prepend(save,button('Reload defaults',()=>reload().catch(error=>m.feedback.textContent=error.message)));
  m.dialog.append(m.feedback,m.controls);
  try{await reload();}catch(error){save.disabled=true;m.feedback.textContent=error.message;}
 }
 async function openNewTask(context){
  const m=modal(context,'New Factory task');
  m.dialog.append(el('p','Submit to the existing Factory queue. The scheduler may start it automatically when capacity is available. All profile settings are frozen on submission.','muted'));
  const title=field(m.dialog,'Title'),project=field(m.dialog,'Project','select'),type=field(m.dialog,'Type','select'),prompt=field(m.dialog,'Task prompt','textarea'),acceptance=field(m.dialog,'Acceptance criteria','textarea');
  title.maxLength=200;prompt.rows=7;acceptance.rows=3;
  options(type,['feature','bug','chore','art'].map(v=>[v,v]));
  const review=el('pre',null,'settings-review');m.dialog.append(review);
  let identity=crypto.randomUUID();let defaults,prepared=null,accepted=false,workflowData,workflowSelection;
  const workflow=context.workflows?field(m.dialog,'Workflow','select'):null;
  const workflowNote=el('pre',null,'settings-review');if(workflow)m.dialog.append(workflowNote);
  function showWorkflow(){if(!workflowSelection)return;workflow.value=workflowSelection.value().workflow_id;workflowNote.textContent=FactoryWorkflowForms.summaryText(workflowSelection.definition())+(workflowSelection.mismatch()?'\nThis workflow differs from the selected task type.':'');}
  if(workflow){workflow.onchange=()=>{workflowSelection.choose(workflow.value);showWorkflow();};type.onchange=()=>{workflowSelection.changeType(type.value);showWorkflow();};}
  const inputs=[title,project,type,prompt,acceptance,...(workflow?[workflow]:[])];
  function payload(){return {submission_id:identity,defaults_revision:defaults.revision,title:title.value,project:project.value,type:type.value,prompt:prompt.value,acceptance:acceptance.value,...(workflowSelection?workflowSelection.value():{})};}
  function showSettings(data){review.textContent=Object.entries(data.roles).map(([role,v])=>`${role}: ${v.provider} / ${v.model} · ${v.effort}`).join('\n');}
  async function success(result){accepted=true;submit.disabled=true;inputs.forEach(i=>i.disabled=true);m.feedback.textContent=`Accepted into Factory queue · ${result.ticket_id||result.root_id}.`;context.onSubmitted(result);}
  const submit=button('Submit to Factory queue',async()=>{
   m.setBusy(true);
   try{
    if(!prepared){const candidate=payload();const preview=await context.api('/api/submissions/preview','POST',candidate);showSettings(preview);prepared=candidate;inputs.forEach(i=>i.disabled=true);}
    const result=await context.api('/api/submissions','POST',prepared);await success(result);
   }catch(error){
    if(prepared){
     try{const status=await context.api('/api/submissions/'+identity);if(status.ticket_id){await success(status);}else{m.feedback.textContent=error.message+' Retry submission to recover this same request.';}}
     catch(statusError){
      if(statusError.status===400&&statusError.message==='Submission not found'){prepared=null;inputs.forEach(i=>i.disabled=false);m.feedback.textContent=error.message+' Your prompt is preserved; update the request and retry.';}
      else m.feedback.textContent=error.message+' Retry submission with the same request identity.';
     }
    }else m.feedback.textContent=error.message+' Your prompt is preserved; reload settings if defaults changed.';
   }finally{m.setBusy(false);submit.disabled=accepted||!defaults?.activation.enabled||(workflow&&!workflowData?.enabled);}
  });
  const reload=button('Reload settings & projects',async()=>{
   if(prepared){m.feedback.textContent='This request is already prepared. Retry submission to recover it.';return;}
   try{await load();}catch(error){m.feedback.textContent=error.message;}
  });
  async function load(){
   const [current,projects]=await Promise.all([context.api('/api/defaults'),context.api('/api/projects')]);defaults=current;
   const selected=project.value;options(project,projects.map(p=>[p.id,p.label]));if(projects.some(p=>p.id===selected))project.value=selected;
   if(workflow){workflowData=await context.api('/api/workflows');if(workflowSelection)workflowSelection.refresh(workflowData);else workflowSelection=FactoryWorkflowForms.selection(workflowData,type.value);options(workflow,workflowData.templates.filter(t=>!t.archived).map(t=>[t.template_id,`${t.name} · r${t.revision}`]));showWorkflow();}
   showSettings(defaults);submit.disabled=!defaults.activation.enabled||(workflow&&!workflowData?.enabled);
   m.feedback.textContent=defaults.activation.enabled?'Review the profile settings above before submitting.':'Submission is disabled until snapshot enforcement is active.';
  }
  const edit=button('Edit unqueued request',async()=>{
   if(accepted)return;
   if(prepared){
    m.setBusy(true);
    try{
     const status=await context.api('/api/submissions/'+identity+'/cancel','POST',{});
     if(status.ticket_id){await success(status);return;}
     if(status.state!=='cancelled')throw new Error('Request state is uncertain; retry submission.');
     identity=crypto.randomUUID();prepared=null;inputs.forEach(i=>i.disabled=false);await load();
     m.feedback.textContent='Unqueued request cancelled. Your prompt is preserved; choose a project and submit a new request.';
    }catch(error){m.feedback.textContent=error.message;}
    finally{m.setBusy(false);submit.disabled=accepted||!defaults?.activation.enabled||(workflow&&!workflowData?.enabled);}
   }
  });
  m.controls.prepend(submit,reload,edit);m.dialog.append(m.feedback,m.controls);submit.disabled=true;
  try{await load();}catch(error){m.feedback.textContent=error.message;}
 }
 return {openDefaults,openNewTask};
})();
