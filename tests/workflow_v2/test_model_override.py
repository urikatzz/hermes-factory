from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard'))
from factory_dashboard.frozen_resolver import FrozenFactoryResolver  # noqa: E402
from factory_dashboard.model_policy import ConfigurationError  # noqa: E402
from factory_dashboard.task_settings import RoleSettings  # noqa: E402


class Snapshot:
    id = 'snap1'; origin = 'captured'; defaults_revision = 3; legacy_card_settings = {}

    def __init__(self):
        self.roles = {'fixer': RoleSettings('anthropic', 'claude-sonnet', 'medium'), 'developer': RoleSettings('anthropic', 'claude-sonnet', 'low')}


class Store:
    def snapshot_for_task(self, identity, task_id):
        return Snapshot()

    def root_for_snapshot(self, identity, snapshot_id):
        return 'root1'


class ModelOverrideResolverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'kanban.db'
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE factory_project_execution(root_id TEXT PRIMARY KEY, document TEXT)')
        self.validated = []
        self.resolver = FrozenFactoryResolver(Store(), self.db, 'default', lambda choice, role: self.validated.append((choice, role)))

    def document(self, **document):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('INSERT OR REPLACE INTO factory_project_execution VALUES(?,?)', ('root1', json.dumps(document)))

    def resolve(self, role):
        return self.resolver.resolve(dict(id='t_card', assignee=role, title='x'), self.db, 'default')

    def test_without_an_override_the_captured_snapshot_decides(self):
        self.document()
        found = self.resolve('fixer')
        self.assertEqual((found['provider'], found['model'], found['effort'], found['source']), ('anthropic', 'claude-sonnet', 'medium', 'captured'))

    def test_a_recorded_human_override_replaces_the_model_for_that_profile_only(self):
        self.document(model_overrides=dict(fixer=dict(provider='openai-codex', model='gpt-5', effort='high')))
        fixer, developer = self.resolve('fixer'), self.resolve('developer')
        self.assertEqual((fixer['provider'], fixer['model'], fixer['effort'], fixer['source']), ('openai-codex', 'gpt-5', 'high', 'human-override'))
        self.assertEqual((developer['model'], developer['source']), ('claude-sonnet', 'captured'))
        self.assertEqual(self.validated[0], (RoleSettings('openai-codex', 'gpt-5', 'high'), 'fixer'))  # the catalog still judges it

    def test_the_catalog_can_refuse_an_override(self):
        self.document(model_overrides=dict(fixer=dict(provider='openai-codex', model='nonexistent', effort='high')))
        def refuse(choice, role):
            raise ConfigurationError('Model is not configured and compatible for every affected profile')
        self.resolver = FrozenFactoryResolver(Store(), self.db, 'default', refuse)
        with self.assertRaises(ConfigurationError):
            self.resolve('fixer')

    def test_a_board_without_project_documents_still_resolves(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('DROP TABLE factory_project_execution')
        self.assertEqual(self.resolve('fixer')['source'], 'captured')


if __name__ == '__main__':
    unittest.main()
