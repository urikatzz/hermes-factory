import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, '/Users/example/.hermes/factory-dashboard')
from factory_dashboard.workflow_templates import _preset
from factory_dashboard.workflow_types import WorkflowDefinition
from factory_ecc.guidance import transform_workflow


class GuidanceTests(unittest.TestCase):
    def test_preserves_custom_content_and_workflow_configuration(self):
        original = _preset('bug')
        original['prepare']['instructions'] = 'Use existing diagnostics.\n'
        saved = copy.deepcopy(original)
        result = transform_workflow(original)
        self.assertEqual(original, saved)
        self.assertTrue(result['prepare']['instructions'].startswith('Use existing diagnostics.\n'))
        for key in ('prepare', 'implement', 'repair'):
            self.assertNotEqual(result[key]['instructions'], original[key]['instructions'])
            old, new = dict(original[key]), dict(result[key])
            old.pop('instructions'); new.pop('instructions')
            self.assertEqual(old, new)
        for key in set(original) - {'prepare', 'implement', 'repair'}:
            self.assertEqual(original[key], result[key])
        WorkflowDefinition.from_document(result)

    def test_repeated_transform_is_exact_noop(self):
        first = transform_workflow(_preset('feature'))
        self.assertEqual(transform_workflow(first), first)

    def test_rejects_damaged_or_edited_managed_blocks(self):
        for instructions in ('<!-- factory-ecc-guidance/v1:begin -->',
                             '<!-- factory-ecc-guidance/v2:begin -->text<!-- factory-ecc-guidance/v2:end -->'):
            doc = _preset('chore')
            doc['implement']['instructions'] = instructions
            with self.assertRaises(ValueError):
                transform_workflow(doc)
        doc = transform_workflow(_preset('chore'))
        doc['implement']['instructions'] += doc['implement']['instructions']
        with self.assertRaises(ValueError):
            transform_workflow(doc)
