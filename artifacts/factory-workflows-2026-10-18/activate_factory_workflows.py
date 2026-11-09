"""Activate only the installed, verified workflow contract, preserving prior history."""
import json,sys,sqlite3
from pathlib import Path
home=Path('/Users/example/.hermes')
sys.path.insert(0,str(home/'factory-dashboard'));sys.path.insert(0,str(home/'hermes-agent'))
from factory_dashboard.workflow_runtime import workflow_readiness
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_templates import WorkflowTemplates
from hermes_cli import kanban_db,kanban_db_connect
from hermes_cli.kanban_db_mutation_guard import register_policy
from gateway import host_rendezvous as hr
r=hr.read_record(hr.ROLE_DESKTOP_SERVE)
assert r and r.pid!=12317,'Owning backend has not reloaded'
assert workflow_readiness()['ready'],'Installed enforcement is not ready'
backup=home/'backups/factory-workflows-20261018-230002'
manifest=json.loads((backup/'manifest.json').read_text())
pause=home/'ESTOP'
assert manifest['created_pause'] and json.loads(pause.read_text())['reason']=='Installing Factory workflow templates','Pause ownership changed'
conn=kanban_db_connect.connect(home/'kanban.db',board='default')
try:
 with kanban_db.write_txn(conn):
  assert not conn.execute("SELECT 1 FROM tasks WHERE status='running'").fetchone(),'Workers active'
  # Persist the consumer requirement before the first managed task, preventing
  # a missing creation hook from silently degrading new roots to legacy.
  register_policy(conn,'*','factory-workflow/v1')
finally:conn.close()
store=TaskSettingsStore(home/'state/factory/task-settings.db',create=False)
assert store.read_activation()['enabled'],'Model snapshot enforcement must remain active'
capture=WorkflowCapture(store,WorkflowTemplates(store));capture.set_enabled(True)
(backup/'activated.json').write_text(json.dumps({'workflows_enabled':True,'backend_pid':r.pid,'released_own_pause':True},indent=2))
pause.unlink()
print(json.dumps({'workflows_enabled':True,'released_own_pause':True,'backend_pid':r.pid}))
