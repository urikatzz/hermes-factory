import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime/factory-dashboard'))

from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.workflow_templates import _preset
from factory_dashboard.workflow_types import WorkflowDefinition


class ProjectPolicyTests(unittest.TestCase):
    def test_v2_definition_is_captured_without_reinterpreting_v1(self):
        old = _preset('feature')
        self.assertEqual(WorkflowDefinition.from_document(old).execution_version, 1)
        updated = {**old, 'execution_version': 2}
        definition = WorkflowDefinition.from_document(updated)
        self.assertEqual(definition.execution_version, 2)

    def test_scope_selects_only_relevant_directors_before_architecture(self):
        from factory_dashboard.project_policy import planning_profiles
        self.assertEqual(planning_profiles(dict(art=False, audio=False, ui=False, ux=False)), ['architect'])
        self.assertEqual(planning_profiles(dict(art=True, audio=True, ui=True, ux=True)),
                         ['art-director', 'audio-director', 'architect'])

    def test_task_graph_rejects_cycles_and_missing_asset_dependencies(self):
        from factory_dashboard.project_policy import validate_plan
        scope = dict(art=True, audio=False, ui=True, ux=True)
        plan = dict(tasks=[
            dict(id='assets', title='Create sprites', owner='artist', dependencies=[],
                 acceptance={'AC1': 'Sprite exists'}, needs=dict(art=True, audio=False, ui=False, ux=False)),
            dict(id='code', title='Integrate sprites', owner='developer', dependencies=['assets'],
                 acceptance={'AC2': 'Sprite renders in game'}, needs=scope),
        ])
        self.assertEqual(len(validate_plan(plan, scope, ['AC1', 'AC2'])), 2)
        bad = copy.deepcopy(plan)
        bad['tasks'][0]['dependencies'] = ['code']
        with self.assertRaisesRegex(ConfigurationError, 'cycle'):
            validate_plan(bad, scope, ['AC1', 'AC2'])
        bad = copy.deepcopy(plan)
        bad['tasks'][1]['dependencies'] = []
        with self.assertRaisesRegex(ConfigurationError, 'depend'):
            validate_plan(bad, scope, ['AC1', 'AC2'])

    def test_each_task_selects_code_security_and_relevant_specialist_reviews(self):
        from factory_dashboard.project_policy import review_profiles
        self.assertEqual(review_profiles(dict(art=False, audio=False, ui=False, ux=False)),
                         ['claude-reviewer', 'security-reviewer'])
        self.assertEqual(review_profiles(dict(art=True, audio=True, ui=True, ux=True)),
                         ['claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer', 'art-reviewer', 'audio-reviewer'])

    def test_specialist_findings_route_to_asset_producers_not_code_fixer(self):
        from factory_dashboard.project_policy import repair_profiles
        self.assertEqual(repair_profiles(['art-reviewer:F1|HIGH|AC1|sprite.png|Wrong silhouette'], 'developer'), ['artist'])
        self.assertEqual(repair_profiles(['audio-reviewer:F2|HIGH|AC1|hit.wav|Wrong tone'], 'developer'), ['sound-designer'])
        self.assertEqual(repair_profiles(['security-reviewer:F1|HIGH|AC1|load.py|Unsafe path'], 'artist'), ['fixer'])
        self.assertEqual(repair_profiles(['art-reviewer:F1|HIGH|AC1|a|Wrong', 'audio-reviewer:F2|HIGH|AC1|b|Wrong'], 'developer'),
                         ['artist', 'sound-designer', 'fixer'])


if __name__ == '__main__':
    unittest.main()
