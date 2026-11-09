from pathlib import Path
import sys,json,hashlib,tempfile,subprocess
D=Path('/private/tmp/hermes-factory-dashboard');H=Path('/private/tmp/hermes-timeline-integration');home=Path('/Users/example/.hermes')
files=[]
def add(source,target):
 files.append({'source':str(source),'destination':str(target),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'expected_sha256':hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None})
core=subprocess.check_output(['git','diff','--name-only','HEAD'],cwd=H,text=True).splitlines()+['hermes_cli/kanban_db_mutation_guard.py','hermes_cli/kanban_db_task_creation.py']
for rel in dict.fromkeys(core):
 if rel.endswith('.py') and not rel.startswith('tests/'):add(H/rel,home/'hermes-agent'/rel)
for folder in ('factory_dashboard','scripts','docs'):
 for source in (D/folder).rglob('*'):
  if source.is_file() and '__pycache__' not in source.parts:add(source,home/'factory-dashboard'/source.relative_to(D))
for name in ('factory_lib.py','factory_intake.py'):add(D/'integrations/factory_intake'/name,home/'scripts'/name)
for source in (D/'integrations/factory_workflows').rglob('*'):
 if not source.is_file():continue
 rel=source.relative_to(D/'integrations/factory_workflows')
 target=home/rel if rel.parts[0]=='profiles' else home/'factory-skills'/rel
 add(source,target)
sys.path.insert(0,str(D));from scripts.bundle_factory_plugin import bundle_plugin
bundle=Path(tempfile.mkdtemp(prefix='factory-workflow-release-'))/'factory-models';bundle_plugin(bundle)
homes=[home,*sorted(p.parent.parent.parent for p in (home/'profiles').glob('*/plugins/factory-models/plugin.yaml'))]
for owner in homes:
 for source in bundle.rglob('*'):
  if source.is_file():add(source,owner/'plugins/factory-models'/source.relative_to(bundle))
release={'home':str(home),'homes':[str(p) for p in homes],'files':files,'source_roots':{'dashboard':str(D),'hermes':str(H)}}
Path('/private/tmp/workflow-install-manifest.json').write_text(json.dumps(release,indent=2));print(len(files),'files;',len(homes),'homes')
