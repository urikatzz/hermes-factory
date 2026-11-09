import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from factory_copy import DASHBOARD, LIVE, REPO
from factory_dashboard.model_catalog import ModelCatalog
from factory_dashboard.model_policy import ConfigurationError, ModelSelection
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.task_settings_store import TaskSettingsStore, encode
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_game_art.migration import NEW_ROLES as ART_ROLES, Migration as ArtMigration
from factory_game_audio.migration import NEW_ROLES, Migration

OLD_ROLES = {
    'architect': ('anthropic', 'claude-opus-5-5', 'high'), 'claude-reviewer': ('anthropic', 'claude-opus-5-5', 'high'),
    'codex-reviewer': ('openai-codex', 'gpt-6-sol', 'high'), 'developer': ('openai-codex', 'gpt-6-luna', 'medium'),
    'factory-orchestrator': ('openai-codex', 'gpt-6-astra', 'medium'), 'fixer': ('anthropic', 'claude-opus-5-5', 'high'),
    'security-reviewer': ('openai-codex', 'gpt-6.1-sol', 'high'), 'ui-reviewer': ('copilot', 'gemini-3.1-pro-preview', 'high'),
    'ux-reviewer': ('anthropic', 'claude-fable-5-1', 'high'), 'verifier': ('anthropic', 'claude-sonnet-5', 'high'),
}
CHOICES = [('anthropic', 'claude-opus-5-5'), ('anthropic', 'claude-sonnet-5'), ('openai-codex', 'gpt-6-luna'),
           ('openai-codex', 'gpt-6-sol'), ('copilot', 'gpt-5-mini')]
MIGRATE = REPO / 'scripts/migrate_game_audio.py'


def legacy_install(root, art=True):
    """A settings store and catalog shaped like the live install before this change: no audio anywhere, and the
    Game Art migration already applied (art=True, the live state today) or not applied at all (art=False)."""
    store = TaskSettingsStore(root / 'settings.db')
    WorkflowCapture(store, WorkflowTemplates(store)).initialize()
    with store._connect() as conn:
        mapping = json.loads(conn.execute('SELECT templates FROM factory_workflow_defaults').fetchone()[0])
        for kind in ('art', 'audio'):
            template = mapping.pop(kind)
            conn.execute('DELETE FROM factory_workflow_revisions WHERE template_id=?', (template,))
            conn.execute('DELETE FROM factory_workflow_templates WHERE id=?', (template,))
        conn.execute('UPDATE factory_workflow_defaults SET templates=?', (encode(mapping),))
    store.seed_defaults({role: RoleSettings(*value) for role, value in OLD_ROLES.items()})
    catalog = {'profiles': {role: {'default': {'provider': p, 'model': m},
                                   'models': [{'provider': p, 'model': m, 'compatible': True}]
                                   + [{'provider': cp, 'model': cm, 'compatible': True}
                                      for cp, cm in CHOICES if (cp, cm) != (p, m)]}
                            for role, (p, m, _) in OLD_ROLES.items()}}
    (root / 'catalog.json').write_text(json.dumps(catalog, indent=2))
    if art:
        ArtMigration(DASHBOARD, root / 'settings.db', root / 'catalog.json').apply()
    return store


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class MigrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = legacy_install(self.root)
        self.templates = WorkflowTemplates(self.store)
        self.migration = Migration(DASHBOARD, self.root / 'settings.db', self.root / 'catalog.json')

    def test_preview_lists_everything_and_writes_nothing(self):
        before = (digest(self.root / 'settings.db'), digest(self.root / 'catalog.json'))
        self.assertEqual(self.migration.preview(), {
            'catalog_add': sorted(NEW_ROLES), 'roles_add': sorted(NEW_ROLES), 'defaults_revision': 2,
            'template': None, 'type_default': None})
        self.assertEqual((digest(self.root / 'settings.db'), digest(self.root / 'catalog.json')), before)

    def test_apply_adds_catalog_roles_template_and_default(self):
        heads = {doc['template_id']: doc['revision'] for doc in self.templates.list()}
        receipt = self.migration.apply()
        self.assertEqual(receipt['catalog_added'], sorted(NEW_ROLES))
        self.assertEqual(receipt['roles_added'], list(NEW_ROLES))
        self.assertEqual(receipt['defaults_revision'], 3)
        catalog = ModelCatalog.from_file(self.root / 'catalog.json')
        defaults = self.store.read_defaults()
        for role, settings in defaults.roles.items():
            catalog.validate(ModelSelection(settings.provider, settings.model), (role,))
        raw = json.loads((self.root / 'catalog.json').read_text())
        for role, settings in NEW_ROLES.items():
            self.assertEqual(defaults.roles[role], RoleSettings(**settings))
            self.assertNotIn('copilot', {item['provider'] for item in raw['profiles'][role]['models']})
        audio = self.templates.get(receipt['template_created'])
        self.assertEqual((audio.name, audio.revision, audio.implement.profile), ('Game Audio', 1, 'sound-designer'))
        self.assertEqual(self.templates.defaults()['templates']['audio'], audio.template_id)
        self.assertEqual({doc['template_id']: doc['revision'] for doc in self.templates.list()
                          if doc['task_type'] != 'audio'}, heads)

    def test_apply_is_idempotent(self):
        first = self.migration.apply()
        catalog = digest(self.root / 'catalog.json')
        second = self.migration.apply()
        self.assertEqual((second['catalog_added'], second['roles_added'], second['template_created'],
                          second['type_default_set']), ([], [], None, None))
        self.assertEqual(second['defaults_revision'], first['defaults_revision'])
        self.assertEqual(digest(self.root / 'catalog.json'), catalog)
        self.assertEqual(len(self.templates.list()), 5)

    def test_audio_tasks_capture_game_audio_after_apply(self):
        self.migration.apply()
        capture = WorkflowCapture(self.store, self.templates)
        capture.set_enabled(True)
        snapshot = self.store.get_snapshot(
            self.store.capture_task('board', 't_audio', 'direct_root', workflow_selection={'type': 'audio'}))
        self.assertEqual(snapshot.workflow.name, 'Game Audio')
        self.assertEqual(snapshot.roles['sound-designer'], RoleSettings(**NEW_ROLES['sound-designer']))

    def test_rollback_removes_the_default_archives_and_is_idempotent(self):
        receipt = self.migration.apply()
        result = self.migration.rollback()
        self.assertEqual(result['type_default_removed'], receipt['template_created'])
        self.assertEqual(result['archived'], [receipt['template_created']])
        self.assertNotIn('audio', self.templates.defaults()['templates'])
        self.assertIn('art', self.templates.defaults()['templates'])
        self.assertTrue(next(d for d in self.templates.list(True) if d['task_type'] == 'audio')['archived'])
        with self.assertRaisesRegex(ConfigurationError, 'Unsupported task type'):
            WorkflowCapture(self.store, self.templates).preview({'type': 'audio'})
        self.assertIn('sound-designer', self.store.read_defaults().roles)
        self.assertEqual(self.migration.rollback(), {'schema': 'factory-game-audio-rollback/v1',
                                                     'type_default_removed': None, 'archived': [], 'purged': []})

    def test_purge_deletes_unused_audio_templates_only(self):
        self.migration.apply()
        result = self.migration.rollback(purge=True)
        self.assertEqual(result['purged'], result['archived'])
        self.assertEqual([d['task_type'] for d in self.templates.list(True)], ['feature', 'bug', 'chore', 'art'])

    def test_purge_keeps_templates_whose_head_revision_is_not_audio(self):
        self.migration.apply()
        feature = next(d for d in self.templates.list() if d['task_type'] == 'feature')
        old = dict(feature, revision=0, task_type='audio')
        with self.store._connect() as conn:
            conn.execute('INSERT INTO factory_workflow_revisions VALUES(?,?,?)',
                         (feature['template_id'], 0, encode(old)))
        result = self.migration.rollback(purge=True)
        self.assertEqual(result['purged'], result['archived'])
        self.assertNotIn(feature['template_id'], result['purged'])
        self.assertEqual([d['task_type'] for d in self.templates.list(True)], ['feature', 'bug', 'chore', 'art'])

    def test_purge_is_refused_once_an_audio_task_was_captured(self):
        self.migration.apply()
        capture = WorkflowCapture(self.store, self.templates)
        capture.set_enabled(True)
        self.store.capture_task('board', 't_audio', 'direct_root', workflow_selection={'type': 'audio'})
        with self.assertRaisesRegex(ValueError, 'snapshot uses an audio workflow'):
            self.migration.rollback(purge=True)
        self.assertEqual(len(self.templates.list(True)), 5)

    def test_audio_after_art_keeps_art(self):
        """Running the art migration, then the audio migration, leaves both type defaults and both templates active."""
        root = self.root / 'fresh'
        root.mkdir()
        legacy_install(root, art=False)
        art = ArtMigration(DASHBOARD, root / 'settings.db', root / 'catalog.json').apply()
        migration = Migration(DASHBOARD, root / 'settings.db', root / 'catalog.json')
        receipt = migration.apply()
        mapping = migration.templates.defaults()['templates']
        self.assertEqual(mapping['art'], art['template_created'])
        self.assertEqual(mapping['audio'], receipt['template_created'])
        self.assertEqual(sorted(d['name'] for d in migration.templates.list() if d['task_type'] in ('art', 'audio')),
                         ['Game Art', 'Game Audio'])
        self.assertTrue(set(ART_ROLES) | set(NEW_ROLES) <= set(migration.store.read_defaults().roles))

    def test_audio_purge_leaves_art_rows(self):
        ArtMigration(DASHBOARD, self.root / 'settings.db', self.root / 'catalog.json').apply()
        self.migration.apply()
        result = self.migration.rollback(purge=True)
        names = {d['name'] for d in self.templates.list()}
        self.assertIn('Game Art', names)
        self.assertNotIn('Game Audio', names)
        self.assertEqual(len(result['purged']), 1)
        self.assertIn('art', self.templates.defaults()['templates'])

    def test_cli_requires_a_new_receipt_and_rejects_pre_audio_source(self):
        args = [sys.executable, str(MIGRATE), '--dashboard-source', str(DASHBOARD), '--settings-db',
                str(self.root / 'settings.db'), '--catalog', str(self.root / 'catalog.json')]
        self.assertEqual(subprocess.run(args + ['--apply'], capture_output=True, text=True).returncode, 2)
        (self.root / 'old.json').write_text('{}')
        taken = subprocess.run(args + ['--apply', '--receipt', str(self.root / 'old.json')], capture_output=True, text=True)
        self.assertIn('already exists', taken.stderr)
        old = self.root / 'old-source/factory_dashboard'
        old.mkdir(parents=True)
        (old / '__init__.py').write_text('')
        (old / 'workflow_types.py').write_text("TASK_TYPES = ('feature', 'bug', 'chore', 'art')\nCAPABILITIES = {}\n")
        args[3] = str(old.parent)
        result = subprocess.run(args + ['--dry-run'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('lacks the audio task type', result.stderr)


@unittest.skipUnless((LIVE / 'state/factory/task-settings.db').is_file(), 'no live Factory settings store')
class LiveCopyTests(unittest.TestCase):
    """Runs the CLI on a sqlite .backup copy of the live store; the live files must not change."""

    def test_cli_round_trip_on_a_copy_of_the_live_store(self):
        live_db, live_catalog = LIVE / 'state/factory/task-settings.db', LIVE / 'state/factory/model-catalog.json'
        before = (digest(live_db), digest(live_catalog))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = sqlite3.connect(f'file:{live_db}?mode=ro', uri=True)
            target = sqlite3.connect(root / 'settings.db')
            source.backup(target)
            target.close()
            source.close()
            (root / 'catalog.json').write_text(live_catalog.read_text())
            base = [sys.executable, str(MIGRATE), '--dashboard-source', str(DASHBOARD), '--settings-db',
                    str(root / 'settings.db'), '--catalog', str(root / 'catalog.json')]
            dry = subprocess.run(base + ['--dry-run'], capture_output=True, text=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertTrue(set(json.loads(dry.stdout)['roles_add']) <= set(NEW_ROLES))
            applied = subprocess.run(base + ['--apply', '--receipt', str(root / 'apply.json')], capture_output=True, text=True)
            self.assertEqual(applied.returncode, 0, applied.stderr)
            self.assertEqual((root / 'apply.json').stat().st_mode & 0o777, 0o600)
            after = json.loads(subprocess.run(base + ['--dry-run'], capture_output=True, text=True).stdout)
            self.assertEqual((after['catalog_add'], after['roles_add']), ([], []))
            self.assertIsNotNone(after['type_default'])
            self.assertEqual(after['template'], after['type_default'])
            back = subprocess.run(base + ['--rollback', '--receipt', str(root / 'rollback.json')], capture_output=True, text=True)
            self.assertEqual(back.returncode, 0, back.stderr)
            self.assertIsNone(json.loads(subprocess.run(base + ['--dry-run'], capture_output=True, text=True).stdout)['type_default'])
        self.assertEqual((digest(live_db), digest(live_catalog)), before)
