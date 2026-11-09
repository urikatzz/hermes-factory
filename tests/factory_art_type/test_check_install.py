import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, REPO
from test_migration import legacy_install
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_game_art.migration import Migration

PROFILE = """model:
  provider: {provider}
  default: {model}
platform_toolsets:
  cli:
    - kanban
    - file
    - terminal
    - vision
kanban:
  dispatch_in_gateway: false
"""
ROOT_CONFIG = """kanban:
  dispatch_profiles:
    - factory-orchestrator
    - verifier
    - claude-reviewer
{extra}code_execution:
  timeout: 300
"""


class CheckInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / 'hermes'
        state = self.home / 'state/factory'
        state.mkdir(parents=True)
        legacy_install(state)
        (state / 'settings.db').rename(state / 'task-settings.db')
        (state / 'catalog.json').rename(state / 'model-catalog.json')
        Migration(DASHBOARD, state / 'task-settings.db', state / 'model-catalog.json').apply()
        store = TaskSettingsStore(state / 'task-settings.db', create=False)
        WorkflowCapture(store, WorkflowTemplates(store)).set_enabled(True)  # as on the live install
        bundle = self.home / 'plugins/factory-models'
        subprocess.run([sys.executable, str(DASHBOARD / 'scripts/bundle_factory_plugin.py'), str(bundle)], check=True,
                       capture_output=True)
        for name, provider, model in (('art-director', 'anthropic', 'claude-opus-5-5'),
                                      ('artist', 'openai-codex', 'gpt-6-luna'),
                                      ('art-reviewer', 'anthropic', 'claude-sonnet-5-5')):
            folder = self.home / 'profiles' / name
            folder.mkdir(parents=True)
            (folder / 'config.yaml').write_text(PROFILE.format(provider=provider, model=model))
            (folder / 'SOUL.md').write_text('# Role\n')
            shutil.copytree(bundle, folder / 'plugins/factory-models')
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(
            extra='    - art-director\n    - artist\n    - art-reviewer\n'))
        skills = self.home / 'factory-skills/worker'
        (skills / 'art-production').mkdir(parents=True)
        (skills / 'art-production/SKILL.md').write_text('---\nname: art-production\n---\n')
        (skills / 'art-review/scripts').mkdir(parents=True)
        shutil.copy(REPO / 'scripts/art_lint.py', skills / 'art-review/scripts/art_lint.py')

    def check(self):
        result = subprocess.run([sys.executable, str(REPO / 'scripts/check_game_art_install.py'), '--hermes-home',
                                 str(self.home)], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_a_complete_install_passes_with_the_expected_cards(self):
        code, report = self.check()
        self.assertEqual(code, 0, report['problems'])
        self.assertEqual(report['cards']['prepare'], {'assignee': 'art-director', 'workspace': 'scratch',
                                                      'skills': ['factory-worker']})
        self.assertEqual(report['cards']['implement']['workspace'], 'dir')

    def test_problems_are_reported(self):
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(extra=''))
        (self.home / 'profiles/artist/config.yaml').write_text(PROFILE.format(provider='copilot', model='x'))
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn('profile artist uses provider copilot', report['problems'])
        self.assertIn("root kanban.dispatch_profiles lacks ['art-director', 'art-reviewer', 'artist']", report['problems'])
