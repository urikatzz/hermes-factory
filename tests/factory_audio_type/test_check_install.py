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
from factory_game_audio.migration import Migration

PROFILE = """model:
  provider: {provider}
  default: {model}
platform_toolsets:
  cli:
    - kanban
    - file
    - terminal
{vision}kanban:
  dispatch_in_gateway: false
"""
ROOT_CONFIG = """kanban:
  dispatch_profiles:
    - factory-orchestrator
    - verifier
    - claude-reviewer
    - art-director
    - artist
    - art-reviewer
{extra}code_execution:
  timeout: 300
"""
AUDIO = (('audio-director', 'anthropic', 'claude-opus-5-5'), ('sound-designer', 'openai-codex', 'gpt-6-luna'),
         ('audio-reviewer', 'anthropic', 'claude-sonnet-5-5'))


class CheckInstallTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name) / 'hermes'
        state = self.home / 'state/factory'
        state.mkdir(parents=True)
        legacy_install(state)  # the live shape today: Game Art installed, no audio
        (state / 'settings.db').rename(state / 'task-settings.db')
        (state / 'catalog.json').rename(state / 'model-catalog.json')
        Migration(DASHBOARD, state / 'task-settings.db', state / 'model-catalog.json').apply()
        store = TaskSettingsStore(state / 'task-settings.db', create=False)
        WorkflowCapture(store, WorkflowTemplates(store)).set_enabled(True)  # as on the live install
        bundle = self.home / 'plugins/factory-models'
        subprocess.run([sys.executable, str(DASHBOARD / 'scripts/bundle_factory_plugin.py'), str(bundle)], check=True,
                       capture_output=True)
        for name, provider, model in AUDIO:
            folder = self.home / 'profiles' / name
            folder.mkdir(parents=True)
            vision = '    - vision\n' if name == 'audio-reviewer' else ''
            (folder / 'config.yaml').write_text(PROFILE.format(provider=provider, model=model, vision=vision))
            (folder / 'SOUL.md').write_text('# Role\n')
            shutil.copytree(bundle, folder / 'plugins/factory-models')
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(
            extra='    - audio-director\n    - sound-designer\n    - audio-reviewer\n'))
        skills = self.home / 'factory-skills/worker'
        for skill in ('audio-review', 'audio-production'):
            (skills / skill / 'scripts').mkdir(parents=True)
            (skills / skill / 'SKILL.md').write_text(f'---\nname: {skill}\n---\n')
        shutil.copy(REPO / 'scripts/audio_lint.py', skills / 'audio-review/scripts/audio_lint.py')
        shutil.copy(REPO / 'scripts/sfx_synth.py', skills / 'audio-production/scripts/sfx_synth.py')

    def check(self):
        result = subprocess.run([sys.executable, str(REPO / 'scripts/check_game_audio_install.py'), '--hermes-home',
                                 str(self.home)], capture_output=True, text=True)
        return result.returncode, json.loads(result.stdout)

    def test_a_complete_install_passes_with_the_expected_cards(self):
        code, report = self.check()
        self.assertEqual(code, 0, report['problems'])
        self.assertEqual(report['cards']['prepare'], {'assignee': 'audio-director', 'workspace': 'scratch',
                                                      'skills': ['factory-worker']})
        self.assertEqual(report['cards']['implement'], {'assignee': 'sound-designer', 'workspace': 'dir',
                                                        'skills': ['factory-worker']})
        self.assertEqual(report['cards']['audio-reviewer']['assignee'], 'audio-reviewer')

    def test_problems_are_reported(self):
        (self.home / 'config.yaml').write_text(ROOT_CONFIG.format(extra=''))
        (self.home / 'profiles/sound-designer/config.yaml').write_text(PROFILE.format(provider='copilot', model='x', vision=''))
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn('profile sound-designer uses provider copilot', report['problems'])
        self.assertIn('profile sound-designer uses copilot/x, expected openai-codex/gpt-6-luna', report['problems'])
        self.assertIn("root kanban.dispatch_profiles lacks ['audio-director', 'audio-reviewer', 'sound-designer']",
                      report['problems'])

    def test_a_missing_audio_review_skill_is_exactly_the_problem(self):
        (self.home / 'factory-skills/worker/audio-review/SKILL.md').unlink()
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(report['problems'], ['audio-review skill is not installed'])

    def test_art_must_stay_a_type_default(self):
        state = self.home / 'state/factory'
        from factory_game_art.migration import Migration as ArtMigration
        ArtMigration(DASHBOARD, state / 'task-settings.db', state / 'model-catalog.json').rollback()
        code, report = self.check()
        self.assertEqual(code, 1)
        self.assertIn('art is no longer a type default', report['problems'])


if __name__ == '__main__':
    unittest.main()
