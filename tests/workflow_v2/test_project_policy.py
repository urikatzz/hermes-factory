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

    def test_plan_ignores_extra_top_level_keys_but_requires_tasks(self):
        from factory_dashboard.project_policy import validate_plan
        scope = dict(art=False, audio=False, ui=False, ux=False)
        task = dict(id='code', title='Wire scene', owner='developer', dependencies=[],
                    acceptance={'AC1': 'Room plays'}, needs=scope)
        self.assertEqual(len(validate_plan(dict(plan='x', root='y', tasks=[task]), scope, ['AC1'])), 1)
        with self.assertRaises(ConfigurationError):
            validate_plan(dict(plan='x'), scope, ['AC1'])

    def test_each_task_selects_code_security_and_relevant_specialist_reviews(self):
        from factory_dashboard.project_policy import review_profiles
        self.assertEqual(review_profiles(dict(art=False, audio=False, ui=False, ux=False)),
                         ['claude-reviewer', 'security-reviewer'])
        self.assertEqual(review_profiles(dict(art=True, audio=True, ui=True, ux=True)),
                         ['claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer', 'art-reviewer'])

    def test_specialist_findings_route_to_asset_producers_not_code_fixer(self):
        from factory_dashboard.project_policy import repair_profiles
        self.assertEqual(repair_profiles(['art-reviewer:F1|HIGH|AC1|sprite.png|Wrong silhouette'], 'developer'), ['artist'])
        self.assertEqual(repair_profiles(['security-reviewer:F1|HIGH|AC1|load.py|Unsafe path'], 'artist'), ['fixer'])
        self.assertEqual(repair_profiles(['art-reviewer:F1|HIGH|AC1|a|Wrong'], 'developer', repair_domains=['audio']),
                         ['artist', 'sound-designer', 'fixer'])

    def test_second_code_reviewer_is_a_second_opinion_not_a_default(self):
        from factory_dashboard.project_policy import review_profiles
        needs = dict(art=False, audio=False, ui=False, ux=False)
        both = ['codex-reviewer', 'claude-reviewer']
        self.assertEqual(review_profiles(needs, both), ['codex-reviewer', 'security-reviewer'])
        self.assertEqual(review_profiles(needs, both, True), ['codex-reviewer', 'claude-reviewer', 'security-reviewer'])

    def test_rereview_covers_finding_sources_and_the_repaired_discipline(self):
        from factory_dashboard.project_policy import rereview_profiles
        panel = ['claude-reviewer', 'security-reviewer', 'ux-reviewer', 'ui-reviewer', 'art-reviewer']
        self.assertEqual(rereview_profiles(panel, ['art-reviewer:F1|HIGH|AC1|a.png|Wrong'], ['artist']), ['art-reviewer'])
        self.assertEqual(rereview_profiles(panel, ['ui-reviewer:F1|HIGH|AC1|menu|Overlap'], ['fixer']),
                         ['claude-reviewer', 'security-reviewer', 'ui-reviewer'])
        self.assertEqual(rereview_profiles(panel, ['AC1: fail'], ['artist', 'fixer']),
                         ['claude-reviewer', 'security-reviewer', 'art-reviewer'])

    def test_integration_failures_route_to_owners_of_the_failing_criteria(self):
        from factory_dashboard.project_policy import repair_profiles
        owners = {'AC1': ['artist'], 'AC2': ['developer'], 'AC3': ['sound-designer']}
        self.assertEqual(repair_profiles(['AC1: fail'], 'developer', (), owners), ['artist'])
        self.assertEqual(repair_profiles(['AC2: fail'], 'developer', (), owners), ['fixer'])
        self.assertEqual(repair_profiles(['AC1: fail', 'AC3: fail'], 'developer', (), owners), ['artist', 'sound-designer', 'fixer'])
        self.assertEqual(repair_profiles(['Verifier checks failed'], 'developer', (), owners), ['fixer'])
        self.assertEqual(repair_profiles(['AC1: fail'], 'developer', ['code'], owners), ['fixer'])

    def test_plan_accepts_optional_risk_and_scope_only_widens(self):
        from factory_dashboard.project_policy import scope_additions, validate_plan
        scope = dict(art=False, audio=False, ui=False, ux=False)
        task = dict(id='code', title='Build', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs=scope)
        self.assertEqual(validate_plan(dict(tasks=[{**task, 'risk': 'high'}]), scope, ['AC1'])[0]['risk'], 'high')
        with self.assertRaisesRegex(ConfigurationError, 'risk'):
            validate_plan(dict(tasks=[{**task, 'risk': 'extreme'}]), scope, ['AC1'])
        self.assertEqual(scope_additions(['art'], scope), ['art'])
        self.assertEqual(scope_additions(None, scope), [])
        for bad in (['art', 'art'], ['video'], 'art'):
            with self.assertRaises(ConfigurationError):
                scope_additions(bad, scope)
        with self.assertRaises(ConfigurationError):
            scope_additions(['art'], {**scope, 'art': True})


if __name__ == '__main__':
    unittest.main()
