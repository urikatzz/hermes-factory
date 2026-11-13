"""Synthetic handoffs on a real disposable Hermes board; never launches a model."""
import importlib.util
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'runtime/factory-dashboard'))
sys.path.insert(0,str(Path.home()/'.hermes/hermes-agent'))


def main():
    with tempfile.TemporaryDirectory(prefix='factory-project-native-') as directory:
        home=Path(directory).resolve()
        os.environ['HERMES_HOME']=str(home)
        os.environ['HERMES_RUNTIME_DIR']=str(home/'runtime')
        os.environ['HERMES_KANBAN_DB']=str(home/'kanban.db')
        from hermes_cli import kanban_db as kb,kanban_db_connect as kbc,plugins
        from factory_dashboard.task_settings_store import TaskSettingsStore
        from factory_dashboard.task_settings import RoleSettings
        from factory_dashboard.workflow_capture import WorkflowCapture
        from factory_dashboard.workflow_templates import WorkflowTemplates
        from factory_dashboard.project_policy import V2_PROFILES
        from factory_dashboard.workflow_controller import WorkflowController
        from factory_dashboard.workflow_state import WorkflowState
        from install_project_workflows import activate_templates
        store=TaskSettingsStore(home/'settings.db')
        store.seed_defaults({p:RoleSettings('test','model','high') for p in V2_PROFILES})
        capture=WorkflowCapture(store,WorkflowTemplates(store));capture.initialize();capture.set_enabled(True)
        activate_templates(store)
        path=kb.init_db(home/'kanban.db')
        conn=kbc.connect(path)
        settings=dict(board_path=str(path),snapshot_path=str(store.path),board_id='default',new_project_root=str(home/'projects'))
        spec=importlib.util.spec_from_file_location('project_native_plugin',REPO/'runtime/factory-dashboard/integrations/hermes_factory_models/__init__.py',submodule_search_locations=[str(REPO/'runtime/factory-dashboard/integrations/hermes_factory_models')])
        # The real bundle uses relative imports; build and load that package.
        bundle_spec=importlib.util.spec_from_file_location('native_bundle_builder',REPO/'runtime/factory-dashboard/scripts/bundle_factory_plugin.py')
        bundler=importlib.util.module_from_spec(bundle_spec);bundle_spec.loader.exec_module(bundler)
        out=bundler.bundle_plugin(home/'bundle')
        spec=importlib.util.spec_from_file_location('project_native_plugin',out/'__init__.py',submodule_search_locations=[str(out)])
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
        callbacks={}
        class Context:
            def get_config(self,key,default=None):return settings.get(key,default)
            def register_hook(self,name,callback):callbacks[name]=callback
        module.register(Context())
        with patch.object(plugins,'has_hook',lambda name: name in callbacks),patch.object(plugins,'iter_hook_callbacks',lambda name: [callbacks[name]] if name in callbacks else []),patch.object(kb,'_fire_task_hook'):
            root=kb.create_task(conn,title='FACTORY: native v2',body='TYPE: feature\nPROJECT_MODE: new\nPROJECT_DIR: auto\nREQUEST: Small code task',assignee='factory-orchestrator')
            assert kb.get_task(conn,root).status=='blocked'
            try:
                kb.complete_task(conn,root,result='bypass',force=True)
                raise AssertionError('Root bypass unexpectedly succeeded')
            except ValueError:
                pass
            # Controller and hooks must share the bundle's context-variable namespace.
            WorkflowController=importlib.import_module(spec.name+'.factory_dashboard.workflow_controller').WorkflowController
            WorkflowState=importlib.import_module(spec.name+'.factory_dashboard.workflow_state').WorkflowState
            controller=WorkflowController(kb,WorkflowState(),home/'projects')
            controller.reconcile(conn,root)
            row=dict(conn.execute('SELECT * FROM factory_workflow_stages WHERE root_id=?',(root,)).fetchone())
            assert row['profile']=='factory-orchestrator'
            claimed=kb.claim_task(conn,row['task_id'])
            assert claimed is not None
            assert conn.execute('SELECT active_run_id FROM factory_workflow_stages WHERE task_id=?',(claimed.id,)).fetchone()[0]==claimed.current_run_id
            completed=0
            for _ in range(24):
                stages=[dict(r) for r in conn.execute("SELECT s.* FROM factory_workflow_stages s JOIN tasks t ON t.id=s.task_id WHERE s.root_id=? AND t.status IN ('ready','running') ORDER BY t.created_at,s.stage_key",(root,))]
                for stage in stages:
                    task=kb.get_task(conn,stage['task_id'])
                    task=kb.claim_task(conn,task.id) if task.status=='ready' else task
                    assert task is not None
                    # Synthetic launch/completion evidence belongs only to this disposable test.
                    kb._append_event(conn,task.id,'worker_registered',{'synthetic_test':True},run_id=task.current_run_id)
                    kind=stage['kind']
                    verdict={'prepare':'DONE','implement':'DONE','verify':'PASS','review':'NO_BLOCKING_FINDINGS','repair':'DONE'}[kind]
                    manifest='none' if kind=='prepare' else 'abcdef123456'
                    artifacts=[]
                    def retain(name,data):
                        aid=kb.store_attachment_bytes(conn,task.id,name,data,uploaded_by='synthetic-test')
                        artifacts.append(kb.get_attachment(conn,aid).stored_path)
                    if kind=='prepare':
                        retain('RETRO.md' if stage['profile']=='factory-retro' else 'PLAN-REVIEW.md' if stage['stage_key']=='project-plan-review' else 'PLAN.md',b'AC1: Test behavior\n')
                    if stage['profile']=='architect':
                        retain('project-plan.json',json.dumps(dict(tasks=[dict(id='code',title='Native small task',owner='developer',dependencies=[],acceptance={'AC1':'Test behavior'},needs=dict(art=False,audio=False,ui=False,ux=False))])).encode())
                    if kind in ('review','verify'):
                        retain('report.md',b'Synthetic passing report, not a model evaluation.\n')
                    if kind=='verify':
                        retain('src-'+manifest+'.tgz',b'synthetic snapshot identity fixture')
                    metadata=dict(contract='factory-worker/v2',workflow_contract='factory-workflow/v1',root=root,
                        stage_key=stage['stage_key'],stage=kind.upper(),cycle=stage['cycle']+1,verdict=verdict,
                        manifest_sha12=manifest,artifacts=artifacts,ac_ids=['AC1'],ac_results={'AC1':'pass'},
                        release_audit='PASS',publish_commands=['git status'],checks_failed=0,findings=[])
                    if stage['profile']=='factory-orchestrator':
                        metadata['project_scope']=dict(art=False,audio=False,ui=False,ux=False)
                    summary=f'VERDICT={verdict} STAGE={kind.upper()} CYCLE={stage["cycle"]+1} MANIFEST={manifest}'
                    assert kb.complete_task(conn,task.id,result='Synthetic test completion',summary=summary,metadata=metadata,expected_run_id=task.current_run_id,fire_lifecycle_hook=False)
                    completed+=1
                controller.reconcile(conn,root)
                if kb.get_task(conn,root).status=='done':break
            assert kb.get_task(conn,root).status=='done',WorkflowState().read_root(conn,root)
            assert any(r[0]=='factory-retro' for r in conn.execute('SELECT profile FROM factory_workflow_stages'))
            assert conn.execute("SELECT 1 FROM factory_workflow_stages WHERE stage_key='project-plan-review'").fetchone()
            print(json.dumps(dict(native_board=True,root_guard=True,v2_scope_card=True,stage_claim_guard=True,
                                  plan_review=True,full_task_cycle=True,final_integration=True,retro=True,synthetic_stages=completed,model_calls=0)))
        conn.close()


if __name__=='__main__':
    sys.path.insert(0,str(REPO/'scripts'))
    main()
