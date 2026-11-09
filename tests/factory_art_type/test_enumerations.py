import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, SKILLS
from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.task_submission import TaskSubmissionService
from factory_dashboard.workflow_capture import WorkflowCapture, intake_selection
from factory_dashboard.workflow_service import WorkflowService
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_dashboard.workflow_types import CAPABILITIES

ASSETS = DASHBOARD / 'factory_dashboard/assets'


class Projects:
    def list_projects(self):
        return [{'id': 'game', 'label': 'game'}]


def payload(kind):
    return dict(submission_id='0b0e5c1e-58a4-4c55-9df1-3f7c2c8b1f00', defaults_revision=1, title='Paint the hero',
                project='game', type=kind, prompt='Paint the hero sprite.', acceptance='')


class EnumerationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.store = TaskSettingsStore(Path(temp.name) / 'settings.db')
        self.templates = WorkflowTemplates(self.store)
        self.capture = WorkflowCapture(self.store, self.templates)
        self.capture.initialize()
        self.store.seed_defaults({p: RoleSettings('anthropic', 'claude-opus-5-5', 'high') for p in CAPABILITIES})

    def test_submission_accepts_art_and_rejects_unknown_types(self):
        service = TaskSubmissionService(self.store, Projects(), 'board', lambda roles: None)
        service._validate(payload('art'))
        with self.assertRaisesRegex(ConfigurationError, 'Invalid task type'):
            service._validate(payload('sound'))

    def test_art_tickets_select_the_game_art_workflow(self):
        body = 'FACTORY_TICKET v2\n' + json.dumps({'PROJECT': 'game', 'TYPE': 'art', 'ACCEPTANCE': '', 'REQUEST': 'x'})
        self.assertEqual(intake_selection({'body': body}), {'type': 'art'})
        self.assertEqual(self.capture.preview({'type': 'art'}).name, 'Game Art')
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported task type'):
            self.capture.preview({'type': 'sound'})

    def test_captured_art_snapshot_freezes_the_game_art_definition(self):
        self.capture.set_enabled(True)
        snapshot = self.store.get_snapshot(
            self.store.capture_task('board', 't_art', 'direct_root', workflow_selection={'type': 'art'}))
        self.assertEqual(snapshot.workflow.implement.profile, 'artist')
        self.assertIn('art-director', snapshot.roles)

    def test_dashboard_lists_the_new_profiles(self):
        listing = WorkflowService(self.templates, self.capture, self.store, lambda: {'ready': True}).list()
        self.assertEqual(listing['capabilities']['artist'], ('implement', 'repair'))
        self.assertIn('art', listing['defaults']['templates'])

    def test_both_forms_offer_the_art_type(self):
        self.assertIn("doc.task_type,['feature','bug','chore','art'])", (ASSETS / 'workflow_forms.js').read_text())
        self.assertIn("options(type,['feature','bug','chore','art'].map(", (ASSETS / 'task_forms.js').read_text())

    @unittest.skipUnless(shutil.which('node'), 'node not installed')
    def test_forms_still_parse(self):
        for name in ('workflow_forms.js', 'task_forms.js'):
            result = subprocess.run(['node', '--check', str(ASSETS / name)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_orchestrator_skill_names_the_art_type(self):
        text = (SKILLS / 'orchestrator/software-factory/SKILL.md').read_text()
        self.assertIn('`TYPE: feature|bug|chore|art`', text)
        self.assertIn('TYPE: feature | bug | chore | art', text)
        self.assertIn('art = the art-director plan', text)
