"""Installed release smoke checks; disposable boards, no process spawns."""
import importlib,json,os,shutil,subprocess,sys
from pathlib import Path
import pytest
import yaml
HOME=Path('/Users/example/.hermes')
DASHBOARD=HOME/'factory-dashboard'
sys.path.insert(0,str(DASHBOARD))
sys.path.insert(0,str(HOME/'hermes-agent'))
OWNERS=[HOME,*sorted(p.parent.parent.parent for p in (HOME/'profiles').glob('*/plugins/factory-models/plugin.yaml'))]


@pytest.mark.parametrize('owner',OWNERS,ids=lambda p:p.name)
def test_installed_owner_and_disposable_claim(owner,tmp_path,monkeypatch):
    settings=yaml.safe_load((owner/'config.yaml').read_text())['plugins']['entries']['factory-models']['settings']
    assert Path(settings['board_path']).resolve()==HOME/'kanban.db'
    assert Path(settings['snapshot_path']).resolve()==HOME/'state/factory/task-settings.db'
    check="import json;from factory_dashboard.workflow_runtime import workflow_readiness;r=workflow_readiness();assert r['ready'],r;print(json.dumps(r))"
    result=subprocess.run([sys.executable,'-c',check],cwd=HOME/'hermes-agent',env={**os.environ,'HERMES_HOME':str(owner),'PYTHONPATH':str(DASHBOARD),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stderr[-1500:]
    monkeypatch.setenv('HERMES_HOME',str(tmp_path/'home'));monkeypatch.setattr(Path,'home',lambda:tmp_path)
    local=tmp_path/'home';local.mkdir()
    shutil.copytree(owner/'plugins/factory-models',local/'plugins/factory-models',ignore=shutil.ignore_patterns('__pycache__'))
    from hermes_cli import kanban_db as kb,kanban_db_connect as kbc,plugins
    from factory_dashboard.task_settings_store import TaskSettingsStore
    from factory_dashboard.workflow_templates import WorkflowTemplates
    from factory_dashboard.workflow_capture import WorkflowCapture
    live=TaskSettingsStore(HOME/'state/factory/task-settings.db',create=False)
    store=TaskSettingsStore(tmp_path/'settings.db');store.seed_defaults(live.read_defaults().roles)
    capture=WorkflowCapture(store,WorkflowTemplates(store));capture.initialize();capture.set_enabled(True)
    kb.init_db();conn=kbc.connect()
    try:
        path=Path(conn.execute('PRAGMA database_list').fetchone()[2])
        settings={**settings,'board_path':str(path),'snapshot_path':str(store.path),'new_project_root':str(tmp_path/'projects')}
        (local/'config.yaml').write_text(yaml.safe_dump({'plugins':{'enabled':['factory-models'],'entries':{'factory-models':{'enabled':True,'settings':settings}}}}))
        plugins.discover_plugins(force=True)
        root=kb.create_task(conn,title='FACTORY: installed smoke',body='TYPE: chore',assignee='factory-orchestrator')
        assert kb.get_task(conn,root).status=='blocked'
        with pytest.raises(ValueError):kb.complete_task(conn,root,result='forced',force=True)
        consumer=next(p for p in plugins.get_plugin_manager()._plugins.values() if p.manifest.name=='factory-models')
        package=consumer.module.__name__+'.factory_dashboard.'
        state=importlib.import_module(package+'workflow_state').WorkflowState()
        controller=importlib.import_module(package+'workflow_controller').WorkflowController(kb,state,tmp_path/'projects')
        controller.reconcile(conn,root)
        tid=conn.execute('SELECT task_id FROM factory_workflow_stages WHERE root_id=?',(root,)).fetchone()[0]
        task=kb.claim_task(conn,tid)
        from hermes_cli.kanban_db_worker_model import prepare_worker_model
        from hermes_cli.kanban_db_dispatch import _worker_argv
        resolved=prepare_worker_model(conn,task,str(tmp_path),'default')
        choice=live.read_defaults().roles['developer']
        argv=_worker_argv(resolved,'developer',None)
        assert ('-m',choice.model) in list(zip(argv,argv[1:]))
        assert argv[argv.index('--provider')+1]==choice.provider
        assert argv[argv.index('--reasoning')+1]==choice.effort
        manager=plugins.get_plugin_manager();saved=list(manager._hooks['before_kanban_task_mutation']);manager._hooks['before_kanban_task_mutation']=[]
        try:
            with pytest.raises(ValueError,match='unavailable'):kb.complete_task(conn,root,result='forced',force=True)
        finally:manager._hooks['before_kanban_task_mutation']=saved
    finally:conn.close()
