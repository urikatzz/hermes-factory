from dataclasses import asdict
import json
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

from board_fixture import REPO
sys.path.insert(0,str(REPO/'scripts'))
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.project_policy import V2_PROFILES


class ReleaseTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('yaml'), 'Installer uses the Hermes Python environment with PyYAML')
    def test_private_install_backs_up_and_refuses_stale_preview(self):
        import yaml
        import shutil
        from install_project_workflows import release_files,preview,install
        with tempfile.TemporaryDirectory() as directory:
            home=Path(directory)/'home';home.mkdir()
            shutil.copytree(REPO/'runtime/factory-dashboard',home/'factory-dashboard',ignore=shutil.ignore_patterns('__pycache__'))
            store=TaskSettingsStore(home/'state/factory/task-settings.db')
            roles={p:RoleSettings('test','model','high') for p in V2_PROFILES if p!='factory-retro'}
            store.seed_defaults(roles)
            capture=WorkflowCapture(store,WorkflowTemplates(store));capture.initialize();capture.set_enabled(True)
            (home/'state/factory/model-catalog.json').write_text(json.dumps(dict(profiles={p:dict(default=dict(provider='test',model='model'),models=[dict(provider='test',model='model')]) for p in roles})))
            for owner in [home,*[home/'profiles'/p for p in roles]]:
                (owner/'plugins/factory-models').mkdir(parents=True)
                (owner/'config.yaml').write_text(yaml.safe_dump(dict(model=dict(provider='test',default='model'),kanban=dict(dispatch_profiles=[]))))
                (owner/'SOUL.md').write_text('# Original role\n')
            worker=home/'factory-skills/worker/factory-worker/SKILL.md';worker.parent.mkdir(parents=True)
            worker.write_text('---\nname: factory-worker\n---\nOriginal contract\n')
            files,_=release_files(home);expected=preview(home,files)
            config=home/'profiles/architect/config.yaml';original=config.read_text();config.write_text(original+'# Concurrent change\n')
            with self.assertRaisesRegex(ValueError,'stale'):
                install(home,expected,Path(directory)/'rejected-backup')
            config.write_text(original)
            result=install(home,expected,Path(directory)/'backup')
            self.assertTrue((Path(result['backup'])/'task-settings.db').is_file())
            self.assertIn('factory-retro',store.read_defaults().roles)
            self.assertEqual(capture.preview({'type':'feature'}).execution_version,2)
            self.assertTrue((home/'profiles/factory-retro/plugins/factory-models/factory_dashboard/project_controller.py').is_file())
            for role in ('architect','art-director','art-reviewer','claude-reviewer'):
                self.assertIn('vision',yaml.safe_load((home/'profiles'/role/'config.yaml').read_text())['platform_toolsets']['cli'],role)
                self.assertIn('Authority, highest first',(home/'profiles'/role/'SOUL.md').read_text())
            self.assertNotIn('vision',yaml.safe_load((home/'profiles/developer/config.yaml').read_text()).get('platform_toolsets',{}).get('cli',[]))
            files,_=release_files(home)
            self.assertEqual(preview(home,files)['changes'],[])

    def test_activation_only_creates_new_revisions_and_preserves_snapshots(self):
        from install_project_workflows import activate_templates
        with tempfile.TemporaryDirectory() as directory:
            store=TaskSettingsStore(Path(directory)/'settings.db')
            store.seed_defaults({p:RoleSettings('test','model','high') for p in V2_PROFILES})
            templates=WorkflowTemplates(store)
            capture=WorkflowCapture(store,templates);capture.initialize();capture.set_enabled(True)
            sid=store.capture_task('board','old','test',workflow_selection={'type':'feature'})
            old=store.get_snapshot(sid)
            self.assertEqual(old.workflow.execution_version,1)
            activate_templates(store)
            updated=capture.preview({'type':'feature'})
            self.assertEqual(updated.execution_version,2)
            self.assertEqual(updated.revision,old.workflow.revision+1)
            self.assertEqual(store.get_snapshot(sid).workflow.execution_version,1)
            activate_templates(store)
            self.assertEqual(capture.preview({'type':'feature'}).revision,updated.revision)

    def test_the_previous_managed_block_upgrades_to_the_authority_block_in_place(self):
        from install_project_workflows import BASE,MANAGED,managed_text
        upgraded=managed_text('Role intro\n\n'+BASE+'# Rest\n')
        self.assertEqual(upgraded,'Role intro\n\n'+MANAGED+'# Rest\n')
        self.assertEqual(managed_text(upgraded),upgraded)
        from install_project_workflows import _PREVIOUS_AUTHORITY
        self.assertEqual(managed_text('Role intro\n\n'+_PREVIOUS_AUTHORITY+'# Rest\n'),upgraded)
        self.assertIn('never blocks for lacking vision',MANAGED)

    def test_plugin_bundle_contains_project_controller_and_policy(self):
        import importlib.util
        path=REPO/'runtime/factory-dashboard/scripts/bundle_factory_plugin.py'
        spec=importlib.util.spec_from_file_location('project_bundle',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'plugin';module.bundle_plugin(out)
            self.assertTrue((out/'factory_dashboard/project_controller.py').is_file())
            self.assertTrue((out/'factory_dashboard/project_policy.py').is_file())


if __name__ == '__main__': unittest.main()
