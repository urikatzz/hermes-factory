from pathlib import Path
import os,sys,tempfile,shutil,json
installed=Path('/Users/example/.hermes/hermes-agent')
sys.path.insert(0,str(installed));sys.path.insert(0,'/Users/example/.hermes/factory-dashboard')
with tempfile.TemporaryDirectory(prefix='installed-factory-') as temp:
 home=Path(temp);os.environ['HERMES_HOME']=str(home)
 from hermes_cli import kanban_db as kb,kanban_db_connect as kbc,kanban_db_dispatch as dispatch
 from hermes_cli.plugins import discover_plugins
 from hermes_cli.kanban_db_worker_model import prepare_worker_model
 from factory_dashboard.task_settings_store import TaskSettingsStore
 from factory_dashboard.task_settings import RoleSettings
 from factory_dashboard.factory_model_resolver import board_key
 import yaml
 assert Path(kb.__file__).resolve().is_relative_to(installed)
 kb.init_db();conn=kbc.connect();db=Path(conn.execute('PRAGMA database_list').fetchone()[2])
 store=TaskSettingsStore(home/'settings.db');store.seed_defaults({'developer':RoleSettings('test','original','medium')})
 catalog=home/'catalog.json';catalog.write_text(json.dumps({'profiles':{'developer':{'default':{'provider':'test','model':'original'},'models':[{'provider':'test','model':'original'},{'provider':'test','model':'new'}]}}}))
 shutil.copytree('/Users/example/.hermes/plugins/factory-models',home/'plugins/factory-models')
 config={'plugins':{'enabled':['factory-models'],'entries':{'factory-models':{'enabled':True,'settings':{'board_path':str(db),'snapshot_path':str(store.path),'catalog_path':str(catalog)}}}}}
 (home/'config.yaml').write_text(yaml.safe_dump(config));discover_plugins(force=True)
 root=kb.create_task(conn,title='FACTORY: installed smoke',assignee='developer')
 store.save_default('developer',RoleSettings('test','new','high'),1)
 child=kb.create_task(conn,title=f'FIX ({root})',assignee='developer')
 kb.promote_task(conn,child,actor='test');task=kb.claim_task(conn,child)
 resolved=prepare_worker_model(conn,task,str(home),'default');argv=dispatch._worker_argv(resolved,'developer',str(home))
 assert resolved.model_override=='original' and resolved.reasoning_effort=='medium'
 assert argv[argv.index('--reasoning')+1]=='medium'
 assert ('-m','original') in list(zip(argv,argv[1:]))
 print(json.dumps({'installed_source':str(Path(kb.__file__).parent),'model':resolved.model_override,'effort':resolved.reasoning_effort,'snapshot_id':store.snapshot_for_task(board_key(db,'default'),child).id,'workers_launched':0}))
 conn.close()
