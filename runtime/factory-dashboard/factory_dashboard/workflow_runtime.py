"""Compose workflow services without loading or launching any provider."""
from contextlib import closing
from pathlib import Path
import sqlite3
from urllib.parse import quote
from .workflow_capture import WorkflowCapture
from .workflow_templates import WorkflowTemplates
from .workflow_service import WorkflowService, WorkflowDashboard
from .workflow_state import WorkflowState


def workflow_readiness():
    try:
        from hermes_cli import plugins, kanban_db_mutation_guard
    except ImportError:
        return dict(ready=False,guard_version=0,missing_hooks=['Workflow runtime is not installed'])
    plugins.discover_plugins()
    manager=plugins.get_plugin_manager()
    consumer=next((p for p in manager._plugins.values() if p.manifest.name=='factory-models' and p.enabled and not p.error),None)
    hooks=('before_kanban_task_create','before_kanban_task_mutation','on_kanban_dispatch_tick','kanban_task_completed','resolve_kanban_worker_model')
    missing=[name for name in hooks if not consumer or name not in consumer.hooks_registered or not plugins.has_hook(name)]
    version=getattr(kanban_db_mutation_guard,'GUARD_VERSION',0)
    contract=getattr(consumer.module,'WORKFLOW_CONTRACT_VERSION',0) if consumer else 0
    return dict(ready=not missing and version==1 and contract==1,guard_version=version,workflow_version=contract,missing_hooks=missing)


def compose_workflows(dashboard,store,board_identity,board_path,readiness):
    templates=WorkflowTemplates(store)
    capture=WorkflowCapture(store,templates);capture.initialize()
    def read_state(root_id):
        with closing(sqlite3.connect('file:'+quote(str(Path(board_path).resolve()))+'?mode=ro',uri=True)) as conn:
            conn.row_factory=sqlite3.Row
            state=WorkflowState().read_root(conn,root_id)
            if not state:
                return None
            result = {k:state[k] for k in ('phase','cycle','reason')}
            if state['definition'].get('execution_version', 1) == 2 and conn.execute("SELECT 1 FROM sqlite_master WHERE name='factory_project_execution'").fetchone():
                import json
                row = conn.execute('SELECT document FROM factory_project_execution WHERE root_id=?', (root_id,)).fetchone()
                if row:
                    project = json.loads(row[0])
                    result['project'] = dict(mode=project['mode'], tasks=len(project['tasks']),
                        completed=sum(t['id'] != 'integration' for t in project['completed']),
                        active_stages=project['active_keys'], retro=project.get('retro'))
            return result
    return WorkflowDashboard(dashboard,WorkflowService(templates,capture,store,readiness),store,board_identity,read_state)
