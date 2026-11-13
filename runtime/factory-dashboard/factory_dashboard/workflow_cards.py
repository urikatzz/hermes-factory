"""Stage bodies preserve existing worker workspace and artifact contracts."""
import json
from pathlib import Path
from .model_policy import ConfigurationError


def build_stage_card(definition, stage_key, cycle, context, inputs, *, stage_spec=None):
    stages=[definition.prepare,definition.implement,definition.verify,definition.repair,*definition.reviewers]
    stage=stage_spec or next((s for s in stages if s.key==stage_key),None)
    if not stage:
        raise ConfigurationError('Unknown workflow stage')
    project=context['project_dir']
    if not Path(project).is_absolute():
        raise ConfigurationError('Workflow project directory must be absolute')
    name={'prepare':'PLAN','implement':'IMPLEMENT','repair':'FIX','verify':'VERIFY','review':stage.profile.upper()}[stage.kind]
    if stage.kind=='verify' and cycle:name='REVERIFY'
    root=context['root_id']
    body=[f'WHAT: {name.title()} for {definition.name}, round {cycle+1}.',
          f'ROOT {root} | STAGE {name} | CYCLE {cycle+1} | PROJECT_MODE {context.get("project_mode","existing")}',
          f'PROJECT_DIR {project}',f'MANIFEST {context.get("manifest","none")}',
          f'BASELINE {context.get("baseline","none")}   BASELINE_TGZ {context.get("baseline_tgz","none")}',
          'INPUTS '+json.dumps(inputs),
          f'WORKFLOW {definition.template_id} REVISION {definition.revision} STAGE_KEY {stage.key} KIND {stage.kind}',
          'SCOPE '+json.dumps(context.get('scope',[])), 'INSTRUCTIONS '+stage.instructions,
          'DECISIONS '+json.dumps(context.get('blocking',[])), 'PROJECT CONSTRAINTS '+context.get('root_header','')]
    if stage.kind=='prepare':
        body.extend(['Create PLAN.md with numbered AC1..ACn and a Manifest include list. Attach PLAN.md; do not modify PROJECT_DIR. Include .factory/PLAN.md and .factory/include.txt in the manifest contract; PLAN.md is the retained attachment and .factory/PLAN.md is its implementation destination.',
                     'REQUEST '+context.get('request',''),'USER_ACCEPTANCE '+context.get('acceptance','')])
    elif stage.kind in ('implement','repair'):
        body.append('Read the attached PLAN.md and implement its acceptance criteria. Materialize the plan and .factory/include.txt in PROJECT_DIR, run required gates, and rebuild the manifest.')
    else:
        body.append('Read the supplied plan and review the exact manifest in a scratch snapshot. Retain report.md and evidence artifacts before completing.')
    if stage.kind=='verify':
        body.append('Run the gate, all acceptance checks and release audit. Record release_audit PASS/FAIL, snapshot path and publish_commands; do not publish.')
    body.append('Managed handoff: contract=factory-worker/v2, workflow_contract=factory-workflow/v1, stage_key='+stage.key+'. Use the header STAGE and CYCLE; include real acceptance, manifest and retained evidence metadata. Required stages and limits cannot be waived.')
    writer=stage.kind in ('implement','repair')
    return dict(title=f'{name} ({root})',body='\n'.join(body),assignee=stage.profile,
                workspace_kind='dir' if writer else 'scratch',workspace_path=project if writer else None,
                skills=['factory-worker'],max_runtime_seconds=3600 if writer else 2400,
                parents=inputs,creator_task_id=root,created_by='factory-workflow',
                idempotency_key=f'workflow-{root}-{stage.key}-{cycle}')
