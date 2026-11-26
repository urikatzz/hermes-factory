"""Controller-level behaviour of the art reviewer with an approved reference, and of the stages that must never see reference material."""
import json
from pathlib import Path
import unittest

from factory_dashboard import project_references as refs
from reference_fixture import NEEDS, ReferenceFlow, TOPICS, png

REFERENCE = dict(
    id='look', path='docs/look/reference.png', roles=['visual_reference', 'immutable'], authority='human_approved', title='Approved look',
    requirements=[dict(id='V1', text='Hazard stripes on platforms and the door frame', keywords=['hazard stripe']),
                  dict(id='V2', text='Slanted amber health segments top left', keywords=['slanted'])],
    deferrals=[])


class ArtReviewFlow(ReferenceFlow):
    REFERENCES = [REFERENCE]
    EXTRA = dict(milestone=1)

    def finish_asset_task(self):
        """The asset task passes its technical checks and completes. No art reviewer is ever scheduled for it: nobody visually reviews an individual asset."""
        self.approved_director()
        self.architect([self.visual_task(owner='artist')])
        self.finish(self.only('claude-reviewer'), 'Plan reviewed against the reference.', document='PLAN-REVIEW.md')
        self.board.complete(self.only('artist'))
        self.tick()
        self.board.complete(self.only('verifier'))
        self.tick()
        profiles = [r['profile'] for r in self.board.ready()]
        assert 'art-reviewer' not in profiles, profiles
        for row in self.board.ready():
            self.board.complete(row)
        self.tick()

    def reach_art_review(self):
        """The only art review: final integration of the complete game."""
        self.finish_asset_task()
        self.board.complete(self.only('developer'))
        self.tick()
        self.board.complete(self.only('verifier'))
        self.tick()
        for row in self.board.ready():
            if row['profile'] != 'art-reviewer':
                self.board.complete(row)
        return self.only('art-reviewer')

    def review(self, stage, holistic='accept', outcome=None, verdict='NO_BLOCKING_FINDINGS', findings=(), viewed_shots=True, per_requirement=None, dimensions=None, whole_outcome=None, viewed_as=None, mode='rendered_in_engine', extra=(), scene=True):
        folder = Path(self.temp.name) / 'review'
        folder.mkdir(exist_ok=True)
        shot = folder / 'game-view.png'
        shot.write_bytes(png())
        director = next(p for p in self.document()['plans'] if p['profile'] == 'art-director')
        reference = self.loaded['references'][0]
        whole = whole_outcome or ('pass' if holistic == 'accept' else 'fail')
        criteria = [dict(rule=f'{r["id"]}: matches the reference', expected='as in the reference', observed='as in the screenshot', outcome='pass')
                    for r in refs.required_requirements(self.loaded['references'])]
        criteria.append(dict(rule='HOLISTIC', expected='the approved look as a whole', observed='the whole screenshot', outcome=whole))
        record = dict(schema='factory-comparison/v1', plan_sha256=director['sha256'], manifest_sha12='abcdef123456', mode=mode, source='tool',
                      outcome=outcome or ('pass' if all(c['outcome'] == 'pass' for c in criteria) else 'fail'), criteria=criteria, evidence=[str(shot)],
                      references=[dict(id=reference['id'], sha256=reference['sha256'])],
                      holistic=dict(verdict=holistic, summary='Whole screenshot against the whole approved image: composition, proportions, density and atmosphere compared side by side. ' * 2,
                                    dimensions=dimensions or {t: ('matches' if holistic == 'accept' else 'differs') for t in TOPICS}, screenshots=['game-view.png']))
        comparison = self.write(stage, 'comparison.json', record)
        scene_files = self.default_scene_files(stage, holistic) if (scene and not extra) else []
        self.finish(stage, 'Art review report.', document='report.md', extra=[comparison, str(shot), *extra, *scene_files], screenshots=['game-view.png'], per_requirement=per_requirement,
                    shots_viewed=viewed_as if viewed_as is not None else ([shot] if viewed_shots else []), verdict=verdict, findings=list(findings))


    def default_scene_files(self, stage, holistic='accept'):
        """A real-looking engine capture of a complete scene, scored 85 (or 40 when the holistic judgement rejects), as the final reviewer would retain it."""
        import hashlib
        folder = Path(self.temp.name) / 'scene-default'
        folder.mkdir(exist_ok=True)
        shot = folder / 'scene.png'; shot.write_bytes(png(size=30000))
        digest = hashlib.sha256(shot.read_bytes()).hexdigest()
        required = [r['id'] for r in refs.required_requirements(self.loaded['references'])]
        passing = holistic == 'accept'
        render = dict(schema='factory-scene-render/v1', renderer='unity-universalrp', command=['capture'], exit_code=0, scene='Assets/Scenes/S.unity', project_dir=self.temp.name, screenshot='scene.png',
                      screenshot_sha256=digest, width=1280, height=720, captured_at=1, engine=dict(engine='Unity', engine_version='6000.4.11f1', graphics_device='Apple M1 Max', screenshot_sha256=digest),
                      completeness=dict(required=required, present=required, missing=[], deferred=[], complete=True))
        diffs = [] if passing else [dict(aspect='color', description='the whole is far too dark', impact=5, responsible='room01-wall.png', repair='lighten the panels')]
        record = dict(schema='factory-scene-similarity/v1', model='m', threshold=80, reference=dict(path='docs/look/reference.png', sha256=self.loaded['references'][0]['sha256']),
                      screenshot=dict(path=str(shot), sha256=digest), score=85 if passing else 40, differences=diffs, diagnosis='' if passing else 'The scene is far too dark overall and the wall drives the gap.',
                      status='pass' if passing else 'fail', problems=[])
        return [self.write(stage, 'scene-render.json', render), self.write(stage, 'scene-similarity.json', record), str(shot)]


class ArtReviewerTests(ArtReviewFlow):
    def test_artist_cards_carry_the_fit_mode_rules(self):
        self.approved_director()
        self.architect([self.visual_task(owner='artist')])
        self.finish(self.only('claude-reviewer'), 'Plan reviewed against the reference.', document='PLAN-REVIEW.md')
        card = self.board.cards[self.only('artist')['task_id']]['body']
        for text in ('Fit mode (required for every asset you fit)', '--coverage opaque', 'Full-bleed art', 'TOOL-MODE error', 'metadata.tool_defect', 'run it with',
                     'No one reviews or scores an individual asset visually', 'nothing here is blocked because an asset looks different', 'one final review of the complete',
                     'a missing pixel size is never a reason to block', 'an explicit size beats any estimate', "take its aspect ratio from that region", 'asset_size.py --aspect', 'caps the long side at 1024',
                     'record in your report the pixel size, the world size', 'constraints that contradict each other (the tool exits 3',
                     'FIT\'s `edge_contact` (all false) and `fragment_count` (0)', '--drop-fragments-below <px>',
                     'never one image per item', 'sprite_sheet.py <sheet.png> <out_dir> --grid CxR', 'not having a one-image-per-item route is never a blocker'):
            self.assertIn(text, card)

    def test_developer_cards_say_that_broken_source_in_the_checkout_is_theirs_and_no_editor_is_needed(self):
        self.finish_asset_task()
        card = self.board.cards[self.only('developer')['task_id']]['body']
        for text in ('Source already in the checkout is yours to repair', 'a half-finished edit from an earlier attempt', 'it is never a blocker',
                     'A running Unity Editor is NOT needed for C# work', 'unity_gate.sh . EditMode .', 'concern live-Editor operations'):
            self.assertIn(text, card)

    def test_no_art_reviewer_is_scheduled_for_an_asset_task_and_the_final_one_answers_for_every_requirement(self):
        self.finish_asset_task()                                        # asserts that no art reviewer was ready after the asset task's verifier
        self.assertEqual([r['profile'] for r in self.board.ready()], ['developer'])   # straight on to final integration: nothing waits for a visual review
        self.board.complete(self.only('developer')); self.tick()
        self.board.complete(self.only('verifier')); self.tick()
        for row in self.board.ready():
            if row['profile'] != 'art-reviewer':
                self.board.complete(row)
        body = self.board.cards[self.only('art-reviewer')['task_id']]['body']
        self.assertNotIn('Scope of this review', body)                   # no per-task scoping: the final review judges every approved requirement
        self.assertNotIn('only the requirement ids in this task', body)
        self.assertIn('Full-scene similarity gate', body)

    def test_a_reviewer_who_never_opened_the_rendered_screenshots_is_sent_back(self):
        self.review(self.reach_art_review(), viewed_shots=False)
        _, context = self.rejection('art-reviewer')
        self.assertIn('never opened any of the rendered screenshots', context['previous_handoff_rejected']['reason'])

    def test_a_reviewer_who_opened_the_lints_own_renders_of_the_retained_asset_is_not_sent_back(self):
        # The retained screenshot is game-view.png; the reviewer looked at the lint's grey-backdrop render of that very asset.
        render = Path(self.temp.name) / 'ws' / 'lint' / 'views' / 'Assets__Art__Room01__game-view.png' / 'grey.png'
        self.review(self.reach_art_review(), viewed_as=[render])
        self.assertEqual(self.document()['terminal']['phase'], 'delivered')   # accepted, not sent back

    def test_a_lint_render_of_a_different_asset_does_not_count(self):
        render = Path(self.temp.name) / 'ws' / 'lint' / 'views' / 'Assets__Art__Room01__some-other-asset.png' / 'grey.png'
        self.review(self.reach_art_review(), viewed_as=[render])
        _, context = self.rejection('art-reviewer')
        self.assertIn('never opened any of the rendered screenshots', context['previous_handoff_rejected']['reason'])

    def test_a_reviewer_who_opened_the_reference_and_the_screenshots_and_judged_the_whole_can_accept(self):
        self.review(self.reach_art_review())
        self.assertEqual(self.document()['terminal']['phase'], 'delivered')   # the single final review accepts the complete game

    def test_a_scene_that_passes_every_requirement_but_differs_as_a_whole_goes_back_to_the_artist(self):
        stage = self.reach_art_review()
        self.review(stage, holistic='reject', verdict='CHANGES_REQUIRED',
                    findings=['F1|HIGH|AC1|game-view.png|HOLISTIC: the overall composition, density and atmosphere differ from the approved reference'])
        self.assertEqual([r['profile'] for r in self.board.ready()], ['artist'])

    def test_recording_a_pass_for_a_rejected_whole_is_refused_as_contradictory(self):
        stage = self.reach_art_review()
        self.review(stage, holistic='reject', outcome='pass', whole_outcome='pass')
        self.assertIn('HOLISTIC', self.terminal()['reason'])
        self.assertNotIn('factory-retro', [r['profile'] for r in self.board.ready()])   # a stop waits for a human; the retro runs only after delivery

    def test_a_rejected_whole_without_a_blocking_finding_cannot_be_approved(self):
        stage = self.reach_art_review()
        self.review(stage, holistic='reject', verdict='NO_BLOCKING_FINDINGS')
        self.assertIn('actionable findings', self.terminal()['reason'])  # a failed comparison with no findings is refused

    def test_a_per_requirement_difference_needs_a_blocking_finding_and_changes_required(self):
        stage = self.reach_art_review()
        self.review(stage, per_requirement=dict(V1=dict(verdict='differs')))
        _, context = self.rejection('art-reviewer')
        self.assertIn('differs V1 needs a BLOCKER/HIGH finding', context['previous_handoff_rejected']['reason'])

    def test_the_final_reviewer_card_asks_for_the_holistic_judgement_and_only_the_full_scene_score(self):
        body = self.board.cards[self.reach_art_review()['task_id']]['body']
        self.assertIn('"holistic"', body)
        self.assertIn('Every requirement passing does not make the result acceptable', body)
        self.assertIn('Role findings (art reviewer)', body)
        self.assertIn('Full-scene similarity gate', body)               # the one similarity score is the full-scene one
        self.assertIn('never an isolated sprite', body)
        self.assertNotIn('per-asset', body.lower().replace('no per-asset similarity score exists here', ''))


class ReferenceExposureTests(ArtReviewFlow):
    """The first replan run stopped because the orchestrator's scope stage was shown reference material it could not act on."""
    FORBIDDEN = ('approved_references', 'Authority order', 'vision_analyze', 'reference-inspection', 'Mandatory reference inspection', 'Approved references.')

    def test_the_scope_card_carries_no_reference_material_even_when_references_exist(self):
        self.tick()
        scope = self.only('factory-orchestrator')
        body = self.board.cards[scope['task_id']]['body']
        for phrase in self.FORBIDDEN:
            self.assertNotIn(phrase, body, phrase)
        self.assertIsNone(self.document().get('terminal'))

    def test_the_scope_card_says_later_stage_work_is_not_the_orchestrators_and_never_a_reason_to_block(self):
        self.tick()
        body = self.board.cards[self.only('factory-orchestrator')['task_id']]['body']
        self.assertIn('belong to later stages with their own tools', body)
        self.assertIn('never finish BLOCKED because a later stage', body)
        self.assertIn('attach it with kanban_complete(artifacts=[that path])', body)
        self.assertIn("'kanban and skills only' does not apply to a managed stage", body)

    def test_the_scope_stage_completes_and_planning_starts_with_the_references_intact(self):
        self.start()
        self.assertEqual(self.document()['references_source'], 'docs/references.json')
        self.assertIn('approved_references', self.board.cards[self.only('art-director')['task_id']]['body'])

    def test_stages_that_only_read_or_build_are_never_told_to_inspect_images(self):
        self.reach_art_review()
        for row in self.conn.execute("SELECT task_id, profile FROM factory_workflow_stages WHERE profile IN ('artist','verifier','security-reviewer')").fetchall():
            body = self.board.cards[row[0]]['body']
            self.assertNotIn('Mandatory reference inspection', body, row[1])
            self.assertIn('Authority order', body)  # they still follow the authority order and cite requirement ids

    def test_the_installed_role_text_scopes_image_inspection_to_the_roles_that_hold_that_section(self):
        import sys
        from board_fixture import REPO
        sys.path.insert(0, str(REPO / 'scripts'))
        from install_project_workflows import MANAGED
        self.assertIn('a role whose card has no such section never needs to view images and never blocks for lacking vision', ' '.join(MANAGED.split()))


if __name__ == '__main__':
    unittest.main()
