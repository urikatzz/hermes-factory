"""Scoped human waivers, preserved-path constraints, per-agent repair routing and resume after a human decision."""
import unittest

from factory_dashboard.model_policy import ConfigurationError
from factory_dashboard.project_decisions import (constraint_view, constraints_of, finding_file, normalize_constraint, normalize_decisions,
                                                 preserved_conflict, relevant_constraints, validate_plan_constraints, validate_spec_conflicts,
                                                 waiver_for)
from factory_dashboard.project_policy import finding_id, missing_baseline_tokens, plan_architecture_diff, route_findings, validate_plan
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


class StructuredConstraintTests(unittest.TestCase):
    def test_every_kind_has_a_validated_stored_form_with_a_stable_id(self):
        samples = [dict(kind='immutable', preserve=['Assets/a.png'], reason='Approved asset must stay as is'),
                   dict(kind='palette', colors=['#1c1c1f', '#F2A020'], reason='Only the approved palette may be used', paths=['Assets/Scripts/*']),
                   dict(kind='layout', rules=['Health bar anchored top-left at 32,32'], reason='Approved HUD layout'),
                   dict(kind='architecture', rules=['Gameplay code never references editor assemblies'], reason='Approved architecture'),
                   dict(kind='behavior', rules=['Dodge roll has a one second cooldown'], reason='Approved behaviour'),
                   dict(kind='acceptance', acs=['AC8'], reason='AC8 must stay satisfied after any repair')]
        for sample in samples:
            with self.subTest(kind=sample['kind']):
                stored = normalize_constraint(sample)
                self.assertEqual(stored['kind'], sample['kind'])
                self.assertRegex(stored['id'], r'^c_[0-9a-f]{8}$')
                self.assertEqual(stored['id'], normalize_constraint(dict(reversed(list(sample.items()))))['id'])
        self.assertEqual(normalize_constraint(samples[1])['colors'], ['#1C1C1F', '#F2A020'])

    def test_invalid_constraints_are_rejected(self):
        for bad in (dict(kind='palette', colors=['red'], reason='long enough reason'), dict(kind='palette', reason='long enough reason'),
                    dict(kind='layout', reason='long enough reason'), dict(kind='layout', rules=['x'], reason='long enough reason'),
                    dict(kind='acceptance', acs=['nope'], reason='long enough reason'), dict(kind='immutable', reason='long enough reason'),
                    dict(kind='immutable', preserve=['*'], reason='long enough reason'), dict(kind='unknown', reason='long enough reason'),
                    dict(kind='behavior', rules=['valid rule text'], reason='short'), dict(kind='behavior', rules=['valid rule text'], reason='long enough reason', paths='x'),
                    dict(kind='behavior', rules=['valid rule text'], reason='long enough reason', extra=1)):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_constraint(bad)
        with self.assertRaises(ConfigurationError):
            validate_plan_constraints('nope')

    def test_legacy_stored_constraints_get_a_kind_and_an_id(self):
        view = constraint_view(dict(preserve=['sprite.png'], reason='old record', source='human'))
        self.assertEqual((view['kind'], view['preserve']), ('immutable', ['sprite.png']))
        self.assertRegex(view['id'], r'^c_[0-9a-f]{8}$')

    def test_constraints_in_force_merge_task_plan_and_human_sources_without_duplicates(self):
        plan = normalize_constraint(dict(kind='palette', colors=['#1C1C1F'], reason='Approved palette for the whole project'), 'plan')
        project = dict(tasks=[dict(id='t', preserve=['a.png'])], plan_constraints=[plan], constraints=[plan, dict(preserve=['b.png'], reason='human freeze')])
        self.assertEqual(sorted(c['kind'] for c in constraints_of(project)), ['immutable', 'immutable', 'palette'])

    def test_only_non_mechanical_constraints_in_scope_are_relevant_to_a_finding(self):
        finding = 'ui-reviewer:F1|MEDIUM|AC8|Assets/Scripts/Hud.cs:Bar|Low contrast'
        unscoped = normalize_constraint(dict(kind='palette', colors=['#1C1C1F'], reason='Approved palette for the project'))
        scoped = normalize_constraint(dict(kind='layout', rules=['Bar stays top-left'], reason='Approved layout', paths=['Assets/Scripts/Hud.cs']))
        elsewhere = normalize_constraint(dict(kind='layout', rules=['Menu stays centred'], reason='Approved menu layout', paths=['Assets/Menu/*']))
        acceptance = normalize_constraint(dict(kind='acceptance', acs=['AC8'], reason='AC8 must stay satisfied'))
        other_ac = normalize_constraint(dict(kind='acceptance', acs=['AC2'], reason='AC2 must stay satisfied'))
        immutable = normalize_constraint(dict(kind='immutable', preserve=['x.png'], reason='Approved file stays as is'))
        found = {c['id'] for c in relevant_constraints(finding, [unscoped, scoped, elsewhere, acceptance, other_ac, immutable])}
        self.assertEqual(found, {unscoped['id'], scoped['id'], acceptance['id']})

    def test_spec_conflict_reports_are_validated(self):
        ok = dict(spec_conflicts=[dict(constraint='c_0123abcd', reason='The fix needs an off-palette colour', finding='F1')])
        self.assertEqual(validate_spec_conflicts(ok)[0]['constraint'], 'c_0123abcd')
        self.assertEqual(validate_spec_conflicts({}), [])
        for bad in (dict(spec_conflicts='x'), dict(spec_conflicts=[dict(constraint='palette', reason='long enough reason')]),
                    dict(spec_conflicts=[dict(constraint='c_0123abcd', reason='short')]), dict(spec_conflicts=[dict(constraint='c_0123abcd', reason='long enough reason', extra=1)])):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                validate_spec_conflicts(bad)

    def test_exhaustion_handling_and_grants_need_a_valid_value_and_a_recorded_note(self):
        self.assertEqual(normalize_decisions(dict(on_exhaustion='human_review'), 'n')['on_exhaustion'], 'human_review')
        self.assertIsNone(normalize_decisions(dict(extra_repairs=1), 'n')['on_exhaustion'])
        for bad in ('stop', 'replan ', 1, True):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(on_exhaustion=bad), 'n')
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(extra_repairs=1), '  ')

    def test_extra_replans_are_one_per_decision_and_need_a_note(self):
        self.assertEqual(normalize_decisions(dict(extra_replans=1), 'n')['extra_replans'], 1)
        self.assertEqual(normalize_decisions(dict(), 'n')['extra_replans'], 0)
        for bad in (-1, 2, '1', 0.5, True):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(extra_replans=bad), 'n')
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(extra_replans=1), ' ')

    def test_extra_repairs_are_bounded(self):
        self.assertEqual(normalize_decisions(dict(extra_repairs=1), 'n')['extra_repairs'], 1)
        for bad in (-1, 3, '1', 1.5, True):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(extra_repairs=bad), 'n')


class PlanCorrectionPolicyTests(unittest.TestCase):
    TASK = dict(id='code', title='Build code', owner='developer', dependencies=[], acceptance={'AC1': 'Works'}, needs=dict(art=False, audio=False, ui=False, ux=False))

    def test_only_preserve_and_nothing_architectural_may_differ(self):
        self.assertEqual(plan_architecture_diff([self.TASK], [dict(self.TASK, preserve=['a.png'])]), [])
        for change in (dict(acceptance={'AC1': 'Weaker'}), dict(owner='artist'), dict(dependencies=['x']), dict(title='Renamed'),
                       dict(needs=dict(art=True, audio=False, ui=False, ux=False)), dict(risk='high')):
            with self.subTest(change=change):
                self.assertEqual(plan_architecture_diff([self.TASK], [dict(self.TASK, **change)]), ['code'])
        self.assertEqual(plan_architecture_diff([self.TASK], [self.TASK, dict(self.TASK, id='more')]), ['more'])
        self.assertEqual(plan_architecture_diff([self.TASK], []), ['code'])
        self.assertEqual(plan_architecture_diff([self.TASK], [dict(self.TASK, risk='normal')]), [])

    def test_baseline_hashes_must_survive_but_additions_are_free(self):
        old = 'Room01.unity acb98fe7 builder 937d9ee7abcd and 45 GiB'
        self.assertEqual(missing_baseline_tokens(old, 'baseline acb98fe7 / 937d9ee7abcd; current ce04575547a29dfa, 31.6 GiB'), [])
        self.assertEqual(missing_baseline_tokens(old, 'replaced by ce04575547a29dfa'), ['937d9ee7abcd', 'acb98fe7'])
        self.assertEqual(missing_baseline_tokens('no hashes here', 'anything'), [])

    def test_finding_ids_and_the_decision_field(self):
        self.assertEqual((finding_id('claude-reviewer:F12|MEDIUM|AC1|x|y'), finding_id('F3|LOW|-|x|y')), ('F12', 'F3'))
        self.assertEqual(normalize_decisions(dict(plan_correction=['F2', 'F1', 'F1']), 'n')['plan_correction'], ['F1', 'F2'])
        for bad in ('F1', ['f1'], ['F1', 7], ['AC1'], ['F' + '9' * 5]):
            with self.subTest(bad=bad), self.assertRaises(ConfigurationError):
                normalize_decisions(dict(plan_correction=bad), 'n')
        with self.assertRaises(ConfigurationError):
            normalize_decisions(dict(plan_correction=['F1']), ' ')


if __name__ == '__main__':
    unittest.main()
