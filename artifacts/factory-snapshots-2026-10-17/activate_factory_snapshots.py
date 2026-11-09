from pathlib import Path
import sys,sqlite3,json
home=Path('/Users/example/.hermes');state=home/'state/factory';backup=home/'backups/factory-snapshots-20261017-213525'
sys.path.insert(0,str(home/'factory-dashboard'))
from factory_dashboard.migration_sources import migration_for
from factory_dashboard.task_settings_store import TaskSettingsStore
migration=migration_for(home/'kanban.db','default',home,state/'model-catalog.json',state/'task-settings.db',Path('/private/tmp/hermes-timeline-preview/models.db'))
with sqlite3.connect(home/'kanban.db',timeout=10) as conn:
 conn.execute('BEGIN IMMEDIATE')
 preview=migration.inspect();migration.apply(preview['digest'])
 store=TaskSettingsStore(state/'task-settings.db',create=False)
 store.set_activation(True,store.read_activation()['revision'])
 conn.rollback()
manifest=json.loads((backup/'manifest.json').read_text())
pause=home/'ESTOP'
if manifest['created_pause']:
 data=json.loads(pause.read_text())
 assert data['reason']=='Installing immutable Factory task settings','Pause ownership changed; leave it in place'
 pause.unlink()
(backup/'activated.json').write_text(json.dumps({'activation':store.read_activation(),'migration':preview},indent=2))
print(json.dumps({'activation':store.read_activation(),'unfinished_roots':len(preview['roots']),'pause_released':manifest['created_pause']}))
