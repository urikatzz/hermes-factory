"""Scoped human waivers, preserved-path constraints, per-agent repair routing and resume after a human decision."""
import unittest

from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_decisions import (constraints_of, finding_file, normalize_decisions, preserved_conflict, waiver_for)
from factory_dashboard.project_policy import route_findings, validate_plan
from factory_dashboard.workflow_gate import evaluate_cycle
from factory_dashboard.workflow_handoffs import StageResult

from test_project_controller import CODE, NEEDS

ART = 'art-reviewer:F2|HIGH|AC1|sprite.png|[similarity] 5% match to the reference, below 80%'
UI = 'ui-reviewer:F1|MEDIUM|AC1|Assets/Scripts/Builder.cs:HealthBar|Health bar sits inside the ceiling band'


def waiver(**overrides):
    return {**dict(ac='AC1', path='sprite.png', source='art-reviewer', reason='Runtime-tinted primitive, not a finished visual asset'), **overrides}


class DecisionValidationTests(unittest.TestCase):
    def test_a_scoped_waiver_is_recorded_with_its_audit_fields(self):
        stored = normalize_decisions(dict(waivers=[waiver()]), 'Approved by the project owner', now=1)['waivers'][0]
        self.assertRegex(stored['id'], r'^w_[0-9a-f]{8}$')
        self.assertEqual((stored['ac'], stored['path'], stored['source'], stored['applied']), ('AC1', 'sprite.png', 'art-reviewer', []))

    def test_no_global_or_unreasoned_waiver_can_be_recorded(self):
        for bad in (dict(path='*'), dict(path='**/*'), dict(path=''), dict(path='...'), dict(ac='all'), dict(ac=None), dict(reason='ok'),
                    dict(source='Art Reviewer'), dict(extra=1)):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(waivers=[{**waiver(), **bad}]), 'note')
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(unknown=[]), 'note')

    def test_constraints_need_specific_paths_and_a_reason(self):
        ok = normalize_decisions(dict(constraints=[dict(preserve=['Assets/Art/*.png'], reason='Approved plan keeps these hashes')]), 'n')
        self.assertEqual(ok['constraints'][0]['preserve'], ['Assets/Art/*.png'])
        for bad in (dict(preserve=['*'], reason='long enough reason'), dict(preserve=[], reason='long enough reason'), dict(preserve=['a.png'], reason='x')):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(constraints=[bad]), 'n')

    def test_waiver_matches_only_its_criterion_path_and_reviewer(self):
        w = normalize_decisions(dict(waivers=[waiver()]), 'n')['waivers']
        self.assertTrue(waiver_for(ART.replace('AC1', 'AC1'), w))
        self.assertIsNone(waiver_for(ART.replace('|AC1|', '|AC2|'), w))
        self.assertIsNone(waiver_for(ART.replace('sprite.png', 'hero.png'), w))
        self.assertIsNone(waiver_for(ART.replace('art-reviewer', 'claude-reviewer'), w))
        self.assertIsNone(waiver_for(UI, w))
        self.assertEqual(finding_file(UI), 'Assets/Scripts/Builder.cs')

    def test_plans_may_declare_preserved_paths_and_conflicts_are_detected(self):
        scope = dict(art=False, audio=False, ui=False, ux=False)
        plan = dict(tasks=[{**CODE, 'preserve': ['Assets/Art/GreyBox/WhiteSquare.png']}])
        validate_plan(plan, scope, ['AC1'])
        with self.assertRaises(ConfigurationError):
            validate_plan(dict(tasks=[{**CODE, 'preserve': ['*']}]), scope, ['AC1'])
        constraints = constraints_of(dict(tasks=plan['tasks'], constraints=[]))
        self.assertTrue(preserved_conflict('art-reviewer:F2|HIGH|AC1|Assets/Art/GreyBox/WhiteSquare.png|x', constraints))
        self.assertIsNone(preserved_conflict(UI, constraints))


class RoutingTests(unittest.TestCase):
    def test_each_agent_receives_only_its_own_findings(self):
        routes = route_findings([ART, UI], 'developer')
        self.assertEqual(routes, {'artist': [ART], 'fixer': [UI]})

    def test_an_art_reviewer_finding_about_code_goes_to_the_code_fixer(self):
        code = 'art-reviewer:F1|HIGH|AC1|Assets/Scripts/HudView.cs:12|Segment colour is wrong'
        self.assertEqual(route_findings([code], 'developer'), {'fixer': [code]})
        self.assertEqual(route_findings([ART], 'developer'), {'artist': [ART]})

    def test_declared_domains_keep_working(self):
        self.assertEqual(list(route_findings(['AC1: fail'], 'developer', ['art'])), ['artist'])
        self.assertEqual(list(route_findings([ART], 'developer', ['audio'])), ['artist', 'sound-designer', 'fixer'])


def result(findings, kind='review', **metadata):
    return StageResult(True, '', kind, 1, dict(verdict='CHANGES_REQUIRED', manifest_sha12='abcdef123456', source_profile='art-reviewer',
                                               findings=findings, failed_checks=[], checks_failed=0, **metadata))


class GateWaiverTests(unittest.TestCase):
    writer = StageResult(True, '', 'implement', 1, dict(verdict='DONE', manifest_sha12='abcdef123456', ac_ids=['AC1']))
    verifier = StageResult(True, '', 'verify', 1, dict(verdict='PASS', manifest_sha12='abcdef123456', source_profile='verifier', ac_ids=['AC1'],
                                                       ac_results={'AC1': 'pass'}, release_audit='PASS', findings=[], failed_checks=[], checks_failed=0))

    def gate(self, findings, waivers):
        reviewer = result([f.split(':', 1)[1] for f in findings])
        return evaluate_cycle(self.writer, [self.verifier, reviewer], None, 2, 0, dict(waivers=waivers))

    def test_waived_finding_passes_and_keeps_the_original_result(self):
        stored = normalize_decisions(dict(waivers=[waiver()]), 'n')['waivers']
        decision = self.gate([ART], stored)
        self.assertEqual(decision.decision, 'pass')
        self.assertEqual(decision.blocking, ())
        self.assertIn('5% match', decision.waived[0])
        self.assertIn('waived by human decision ' + stored[0]['id'], decision.waived[0])

    def test_without_a_waiver_or_for_another_path_the_finding_still_blocks(self):
        self.assertEqual(self.gate([ART], []).decision, 'repair')
        other = normalize_decisions(dict(waivers=[waiver(path='other.png')]), 'n')['waivers']
        self.assertEqual(self.gate([ART], other).decision, 'repair')

    def test_a_waiver_never_hides_other_blocking_findings(self):
        stored = normalize_decisions(dict(waivers=[waiver()]), 'n')['waivers']
        decision = self.gate([ART, UI.replace('ui-reviewer', 'art-reviewer')], stored)
        self.assertEqual(decision.decision, 'repair')
        self.assertEqual(len(decision.blocking), 1)


if __name__ == '__main__':
    unittest.main()
