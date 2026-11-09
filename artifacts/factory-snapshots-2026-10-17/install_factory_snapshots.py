"""Install verified Factory artifacts with backups and a short new-work pause."""
from pathlib import Path
import os,sys,shutil,subprocess,json,sqlite3,hashlib,datetime
D=Path('/private/tmp/hermes-factory-dashboard');H=Path('/private/tmp/hermes-timeline-integration')
home=Path('/Users/example/.hermes');installed=home/'hermes-agent'
base='d923a5eb487a17c0a68801bba9ef0f56c81040a8'
assert subprocess.check_output(['git','-C',str(installed),'rev-parse','HEAD'],text=True).strip()==base
changed=['hermes_cli/kanban_db.py','hermes_cli/kanban_db_dispatch.py','hermes_cli/plugins.py']
added=['hermes_cli/kanban_db_task_creation.py','hermes_cli/kanban_db_worker_model.py']
for rel in changed:
 assert (installed/rel).read_bytes()==subprocess.check_output(['git','-C',str(H),'show',base+':'+rel]),rel+' changed since review'
for rel in added:assert not (installed/rel).exists(),rel+' already exists'
with sqlite3.connect('file:'+str(home/'kanban.db')+'?mode=ro',uri=True) as c:
 assert c.execute("SELECT count(*) FROM tasks WHERE status='running'").fetchone()[0]==0,'Workers active; do not install'
backup=home/'backups'/('factory-snapshots-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True,mode=0o700)
files=[]
def save(path):
 rel=path.relative_to(home);target=backup/rel;target.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():shutil.copy2(path,target)
 files.append({'path':str(path),'existed':path.exists()})
for rel in changed+added:save(installed/rel)
save(home/'scripts/factory_lib.py')
homes=[home,*sorted(p.parent for p in (home/'profiles').glob('*/config.yaml'))]
for profile in homes:
 assert not (profile/'plugins/factory-models').exists(),'Plugin already installed; inspect before replacing'
 save(profile/'config.yaml')
pause=home/'ESTOP';created_pause=not pause.exists()
if created_pause:pause.write_text(json.dumps({'reason':'Installing immutable Factory task settings','engaged_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}))
(backup/'manifest.json').write_text(json.dumps({'files':files,'created_pause':created_pause,'base':base},indent=2))
try:
 for rel in changed+added:shutil.copy2(H/rel,installed/rel)
 shutil.copy2(D/'integrations/factory_intake/factory_lib.py',home/'scripts/factory_lib.py')
 state=home/'state/factory';state.mkdir(parents=True,exist_ok=True)
 shutil.copy2('/private/tmp/hermes-timeline-preview/catalog.json',state/'model-catalog.json')
 deploy=home/'factory-dashboard';assert not deploy.exists(),'Dashboard deployment exists'
 deploy.mkdir()
 shutil.copytree(D/'factory_dashboard',deploy/'factory_dashboard',ignore=shutil.ignore_patterns('__pycache__'))
 shutil.copytree(D/'scripts',deploy/'scripts',ignore=shutil.ignore_patterns('__pycache__'))
 sys.path.insert(0,str(D));sys.path.insert(0,str(installed))
 from scripts.bundle_factory_plugin import bundle_plugin
 from hermes_cli.config import atomic_config_replace
 import yaml
 settings={'board_path':str(home/'kanban.db'),'board_id':'default','snapshot_path':str(state/'task-settings.db'),'catalog_path':str(state/'model-catalog.json')}
 for profile in homes:
  bundle_plugin(profile/'plugins/factory-models')
  path=profile/'config.yaml';config=yaml.safe_load(path.read_text()) or {};plugins=config.setdefault('plugins',{})
  enabled=plugins.setdefault('enabled',[])
  if 'factory-models' not in enabled:enabled.append('factory-models')
  plugins.setdefault('entries',{})['factory-models']={'enabled':True,'settings':settings}
  atomic_config_replace(path,config)
 from factory_dashboard.migration_sources import migration_for
 from factory_dashboard.task_settings_store import TaskSettingsStore
 migration=migration_for(home/'kanban.db','default',home,state/'model-catalog.json',state/'task-settings.db',Path('/private/tmp/hermes-timeline-preview/models.db'))
 with sqlite3.connect(home/'kanban.db',timeout=10) as conn:
  conn.execute('BEGIN IMMEDIATE')
  preview=migration.inspect();(backup/'migration.json').write_text(json.dumps(preview,indent=2));migration.apply(preview['digest'])
  conn.rollback()
 # Fresh processes verify discovery in every creating/dispatching profile.
 check="from hermes_cli.plugins import has_hook; assert has_hook('before_kanban_task_create'); assert has_hook('resolve_kanban_worker_model'); print('hooks ready')"
 for profile in homes:
  result=subprocess.run([sys.executable,'-c',check],cwd=installed,env={**os.environ,'HERMES_HOME':str(profile),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
  if result.returncode:raise RuntimeError('Hook verification failed for '+str(profile)+': '+result.stderr[-1200:])
 (backup/'installed.json').write_text(json.dumps({'profiles':[str(p) for p in homes],'settings':settings,'dashboard':str(deploy)},indent=2))
 print(json.dumps({'backup':str(backup),'profiles_verified':len(homes),'activation':False,'pause_created':created_pause}))
except Exception:
 print('Installation incomplete. New-work pause remains in place; see '+str(backup),file=sys.stderr)
 raise
