import copy
import json
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path.home() / '.hermes' / 'factory-dashboard'))
from factory_dashboard.task_settings_store import TaskSettingsStore
from factory_dashboard.workflow_templates import WorkflowTemplates
from factory_dashboard.policy_store import RevisionConflict
from factory_dashboard.task_settings import RoleSettings
from factory_dashboard.workflow_capture import WorkflowCapture
from factory_dashboard.workflow_types import CAPABILITIES
from factory_ecc.migration import build_preview, apply_preview, rollback_receipt


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = TaskSettingsStore(self.root / 'settings.db')
        self.templates = WorkflowTemplates(self.store)
        self.templates.initialize()

    def test_service_migration_preserves_defaults_and_history_and_is_idempotent(self):
        before = self.templates.list()
        defaults = self.templates.defaults()
        preview = build_preview(self.templates)
        self.assertEqual(len(preview['changes']), 3)
        result = apply_preview(self.templates, preview, self.root / 'receipts')
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(self.templates.defaults(), defaults)
        for doc in before:
            self.assertEqual(asdict(self.templates.get(doc['template_id'], 1)),
                             {k: v for k, v in doc.items() if k != 'archived'})
            self.assertEqual(self.templates.get(doc['template_id']).revision, 2)
        self.assertEqual(build_preview(self.templates)['changes'], [])
        for p in (self.root / 'receipts').glob('*.json'):
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)

    def test_stale_preview_and_modified_preview_do_not_write(self):
        preview = build_preview(self.templates)
        doc = asdict(self.templates.get(preview['changes'][0]['template_id']))
        self.templates.save({**doc, 'description': 'user edit'}, doc['revision'])
        with self.assertRaises(ValueError):
            apply_preview(self.templates, preview, self.root / 'receipts')
        self.assertEqual([x['revision'] for x in self.templates.list()], [2, 1, 1])
        preview = build_preview(self.templates)
        preview['changes'][0]['after']['max_repairs'] = 0
        with self.assertRaises(ValueError):
            apply_preview(self.templates, preview, self.root / 'receipts')

    def test_preflight_size_limits_and_excludes_archived_templates(self):
        doc = asdict(self.templates.get(self.templates.list()[0]['template_id']))
        doc['template_id'] = ''; doc.pop('revision')
        doc.pop('template_id')
        archived = self.templates.save(doc, 0)
        self.templates.archive(archived.template_id, 1)
        self.assertEqual(len(build_preview(self.templates)['changes']), 3)
        doc = asdict(self.templates.get(self.templates.list()[0]['template_id']))
        doc['prepare']['instructions'] = 'x' * 3900
        self.templates.save(doc, doc['revision'])
        with self.assertRaises(ValueError):
            build_preview(self.templates)

    def test_partial_conflict_has_receipts_and_resumes_from_fresh_preview(self):
        preview = build_preview(self.templates)
        real_save = self.templates.save
        count = 0
        def concurrent_save(document, expected_revision):
            nonlocal count
            count += 1
            if count == 2:
                raise RevisionConflict('concurrent edit')
            return real_save(document, expected_revision)
        self.templates.save = concurrent_save
        result = apply_preview(self.templates, preview, self.root / 'receipts')
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['applied']), 1)
        self.templates.save = real_save
        fresh = build_preview(self.templates)
        self.assertEqual(len(fresh['changes']), 2)
        self.assertEqual(apply_preview(self.templates, fresh, self.root / 'more')['status'], 'complete')

    def test_rollback_creates_new_revision_and_refuses_later_user_edits(self):
        preview = build_preview(self.templates)
        result = apply_preview(self.templates, preview, self.root / 'receipts')
        path = Path(result['applied'][0]['receipt'])
        old = preview['changes'][0]['before']
        restored = rollback_receipt(self.templates, json.loads(path.read_text()))
        self.assertEqual(restored.revision, 3)
        self.assertEqual(restored.prepare.instructions, old['prepare']['instructions'])
        with self.assertRaises(ValueError):
            rollback_receipt(self.templates, json.loads(path.read_text()))

    def test_existing_capture_and_new_capture_retain_distinct_stage_instructions(self):
        self.store.seed_defaults({profile:RoleSettings('test','model','medium') for profile in CAPABILITIES})
        capture=WorkflowCapture(self.store,self.templates)
        capture.initialize();capture.set_enabled(True)
        old=self.store.capture_task('private','before','test',workflow_selection={'type':'feature'})
        before=self.store.get_snapshot(old)
        preview=build_preview(self.templates)
        apply_preview(self.templates,preview,self.root/'receipts')
        new=self.store.capture_task('private','after','test',workflow_selection={'type':'feature'})
        after=self.store.get_snapshot(new)
        self.assertEqual(self.store.get_snapshot(old).workflow,before.workflow)
        self.assertEqual(before.workflow.revision,1)
        self.assertEqual(after.workflow.revision,2)
        self.assertNotEqual(before.workflow.prepare.instructions,after.workflow.prepare.instructions)

    def test_rollback_rejects_cross_template_and_modified_historical_receipts(self):
        preview=build_preview(self.templates)
        result=apply_preview(self.templates,preview,self.root/'receipts')
        receipt=json.loads(Path(result['applied'][0]['receipt']).read_text())
        original_heads=self.templates.list()
        altered=copy.deepcopy(receipt)
        altered['before']['template_id']=result['applied'][1]['template_id']
        with self.assertRaises(ValueError):rollback_receipt(self.templates,altered)
        altered=copy.deepcopy(receipt)
        altered['before']['prepare']['instructions']='forged prior guidance'
        with self.assertRaises(ValueError):rollback_receipt(self.templates,altered)
        self.assertEqual(self.templates.list(),original_heads)
