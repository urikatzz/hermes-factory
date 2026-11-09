"""Read installed workflow selection and build stage cards without launching workers."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT))
sys.path.insert(0,'/Users/example/.hermes/factory-dashboard')
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_cards import build_stage_card
from factory_ecc.guidance import transform_workflow

store=TaskSettingsStore('/Users/example/.hermes/state/factory/task-settings.db',create=False)
templates=WorkflowTemplates(store)
capture=WorkflowCapture(store,templates)
checks=[]
for kind in ('feature','bug','chore'):
    definition=capture.preview({'type':kind})
    document=asdict(definition)
    assert transform_workflow(document)==document,'Installed guidance missing'
    for stage_kind in ('prepare','implement','repair'):
        stage=getattr(definition,stage_kind)
        card=build_stage_card(definition,stage.key,0,dict(project_dir='/private/tmp/ecc-card-check',root_id='check-only'),[])
        assert 'INSTRUCTIONS '+stage.instructions in card['body']
        assert card['assignee']==stage.profile
        checks.append(dict(task_type=kind,stage_kind=stage_kind,template_id=definition.template_id,
            revision=definition.revision,profile=stage.profile,
            instructions_sha256=hashlib.sha256(stage.instructions.encode()).hexdigest()))
out=Path(__file__).with_name('stage-card-verification.json')
out.write_text(json.dumps(dict(checks=checks,worker_processes_launched=0,model_calls=0),indent=2)+'\n')
print(f'{len(checks)} installed stage card checks passed; zero worker/model launches')
