"""Scan findings in plan prose are explained, shown to the human, ruled on by the plan reviewer, and never silently dismissed; operative rules stay hard."""
import json
import unittest

from factory_dashboard import project_references as refs
from reference_fixture import NEEDS, ReferenceFlow

REFERENCE = dict(
    id='look', path='docs/look/reference.png', roles=['visual_reference', 'immutable'], authority='human_approved', title='Approved look',
    requirements=[dict(id='V1', text='Hazard stripes on platforms and the door frame', keywords=['hazard stripe']),
                  dict(id='V2', text='Slanted amber health segments top left', keywords=['slanted'])],
    deferrals=[])
FLAGGED = 'Rendering note: no hazard stripe trim is drawn on the sled seat, only on the door frame and the platform face.'
QUOTE = 'no hazard stripe trim is drawn on the sled seat'
EXPLANATION = 'The sentence limits stripes on the seat prop only; the door frame and platform face still carry them as V1 requires.'


class AdjudicationFlow(ReferenceFlow):
    REFERENCES = [REFERENCE]
    EXTRA = dict(milestone=1)

    def explained_director(self, text=FLAGGED, explanations=None):
        self.start()
        top = dict(scan_explanations=explanations if explanations is not None else [dict(quote=QUOTE, requirement_id='V1', explanation=EXPLANATION)])
        self.finish(self.only('art-director'), 'V1 V2 carried. ' + text, inspection_top=top)

    def candidate_ids(self):
        return [c['id'] for c in self.document()['explained_candidates']['art-director']]

    def approve(self):
        awaiting = self.document()['awaiting']
        self.controller.resume(self.conn, self.root, f"APPROVE {self.root} {awaiting['sha256'][:12]} {(awaiting['references_digest'] or 'none')[:12]}")

    def to_plan_review(self):
        self.explained_director()
        self.approve()
        self.architect([self.visual_task()])
        return self.only('claude-reviewer')

    def rule(self, stage, verdict, findings=(), **kwargs):
        entries = [dict(id=i, verdict=verdict, quote=QUOTE, rationale='Judged against the approved image and the surrounding text of the plan sentence.') for i in self.candidate_ids()]
        self.finish(stage, 'Plan reviewed.', document='PLAN-REVIEW.md', adjudication=entries, findings=list(findings), **kwargs)


class ExplanationTests(AdjudicationFlow):
    def test_a_flagged_line_without_an_explanation_is_sent_back_naming_the_way_out_and_off_the_general_budget(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2 carried. ' + FLAGGED, inspection_top=dict(scan_explanations=[]))
        _, context = self.rejection('art-director')
        reason = context['previous_handoff_rejected']['reason']
        self.assertIn('Scan candidates in PLAN.md', reason)
        self.assertIn('scan_explanations', reason)
        self.assertEqual(self.document()['handoff_retries'], {'project-art-director:0:scan': 1})  # the general two-retry budget is untouched
        self.assertEqual(context['previous_handoff_rejected']['max_attempts'], 3)

    def test_a_too_thin_or_misquoted_explanation_does_not_count(self):
        for explanations in ([dict(quote=QUOTE, requirement_id='V1', explanation='fine')],
                             [dict(quote='something else entirely that is not in the plan', requirement_id='V1', explanation=EXPLANATION)],
                             [dict(quote='no hazard', requirement_id='V1', explanation=EXPLANATION)],
                             [dict(quote=QUOTE, requirement_id='V2', explanation=EXPLANATION)]):
            self.setUp()
            self.explained_director(explanations=explanations)
            self.assertIn('Scan candidates', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])

    def test_an_explained_line_reaches_the_human_gate_with_its_explanation_and_is_not_dismissed(self):
        self.explained_director()
        awaiting = self.document()['awaiting']
        self.assertEqual([(c['requirement'], c['explanation']) for c in awaiting['explained']], [('V1', EXPLANATION)])
        self.assertIn('flagged line(s) the director explained', self.state.read_root(self.conn, self.root)['reason'])

    def test_the_scan_budget_is_bounded_then_stops_for_a_human(self):
        self.start()
        for _ in range(4):
            self.finish(self.only('art-director'), 'V1 V2 carried. ' + FLAGGED, inspection_top=dict(scan_explanations=[]))
            if self.document().get('terminal'):
                break
        self.assertIn('Scan candidates', self.terminal()['reason'])
        self.assertEqual(self.document()['handoff_retries']['project-art-director:0:scan'], 3)


class OperativeRuleTests(AdjudicationFlow):
    def test_task_acceptance_cannot_be_explained_away(self):
        self.explained_director(text='All V1 and V2 work is planned.', explanations=[])
        self.approve()
        bad = self.visual_task(acceptance={'AC1': 'V1 V2: ' + FLAGGED})
        self.architect([bad], inspection_top=dict(scan_explanations=[dict(quote=QUOTE, requirement_id='V1', explanation=EXPLANATION)]))
        self.assertIn('Task acceptance contradicts', self.rejection('architect')[1]['previous_handoff_rejected']['reason'])

    def test_the_verbatim_original_style_bible_cannot_be_explained_away(self):
        (self.project / 'art/style').mkdir(parents=True)
        (self.project / 'art/style/STYLE.md').write_text('S9 Deferred look: no hazard stripes, crosshair corner marks or painted art (GDD milestone 6).\n')
        self.explained_director(text='All V1 and V2 work is planned.', explanations=[])
        self.approve()
        explain = dict(scan_explanations=[dict(quote='no hazard stripes, crosshair corner marks', requirement_id='V1', explanation=EXPLANATION)])
        self.architect([self.visual_task()], inspection_top=explain)
        self.assertIn('art/style/STYLE.md', self.rejection('architect')[1]['previous_handoff_rejected']['reason'])


class PlanReviewRulingTests(AdjudicationFlow):
    def test_the_plan_reviewer_card_lists_the_explained_candidates_and_asks_for_rulings(self):
        reviewer = self.to_plan_review()
        body = self.board.cards[reviewer['task_id']]['body']
        self.assertIn('"explained_scan_candidates"', body)
        self.assertIn('factory-scan-adjudication/v1', body)
        self.assertIn(EXPLANATION[:40], body)

    def test_a_reviewer_who_rules_on_nothing_is_sent_back(self):
        reviewer = self.to_plan_review()
        self.finish(reviewer, 'Plan reviewed.', document='PLAN-REVIEW.md')
        self.assertIn('scan-adjudication', self.rejection('claude-reviewer')[1]['previous_handoff_rejected']['reason'])

    def test_a_ruling_must_quote_the_flagged_text_and_say_why(self):
        reviewer = self.to_plan_review()
        entries = [dict(id=self.candidate_ids()[0], verdict='benign', quote='unrelated words entirely here', rationale='x' * 50)]
        self.finish(reviewer, 'Plan reviewed.', document='PLAN-REVIEW.md', adjudication=entries)
        self.assertIn('must quote at least 15 characters', self.rejection('claude-reviewer')[1]['previous_handoff_rejected']['reason'])

    def test_a_benign_ruling_lets_the_plan_proceed(self):
        reviewer = self.to_plan_review()
        self.rule(reviewer, 'benign')
        self.assertEqual([r['profile'] for r in self.board.ready()], ['developer'])

    def test_a_contradiction_ruling_needs_a_blocking_finding_and_then_returns_the_plan(self):
        reviewer = self.to_plan_review()
        self.rule(reviewer, 'contradiction')
        self.assertIn('needs a BLOCKER/HIGH finding naming that id', self.rejection('claude-reviewer')[1]['previous_handoff_rejected']['reason'])
        self.rule(self.only('claude-reviewer'), 'contradiction', findings=[f"F1|HIGH|AC1|PLAN.md|{self.candidate_ids()[0]} contradicts V1: stripes removed"])
        self.assertEqual([r['profile'] for r in self.board.ready()], ['architect'])  # the plan goes back; nothing proceeds

    def test_an_ambiguous_ruling_stops_for_a_human_who_can_resolve_it_explicitly(self):
        reviewer = self.to_plan_review()
        identifier = self.candidate_ids()[0]
        self.rule(reviewer, 'ambiguous')
        self.assertIn('needs a human', self.terminal()['reason'])
        self.assertEqual(self.board.ready()[0]['profile'], 'factory-retro')
        while self.board.ready():
            self.board.complete(self.board.ready()[0])
            self.tick()
        self.controller.resume(self.conn, self.root, 'Recovered. SCAN-BENIGN ' + identifier)
        self.assertEqual(self.document()['scan_resolved'], [identifier])
        reviewer = self.only('claude-reviewer')
        self.assertNotIn('"explained_scan_candidates"', self.board.cards[reviewer['task_id']]['body'])  # the context key; the instruction text still names it
        self.finish(reviewer, 'Plan reviewed.', document='PLAN-REVIEW.md')
        self.assertEqual([r['profile'] for r in self.board.ready()], ['developer'])


if __name__ == '__main__':
    unittest.main()
