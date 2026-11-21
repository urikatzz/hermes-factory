"""The full-scene gate: the complete engine capture of the assembled scene against the complete approved reference, and the repair loop around it."""
import hashlib
import json
from pathlib import Path
import unittest

from factory_dashboard import scene_loop
from factory_dashboard.project_evidence import validate_scene_similarity
from reference_fixture import png
from test_reference_art_review import ArtReviewFlow

DIFFS = [dict(aspect='texture', description='the wall is nearly featureless', impact=5, responsible='room01-wall-backdrop.png', repair='paint lighter charcoal panels with seams and rivets'),
         dict(aspect='color', description='the floor is far lighter than the near-black reference floor', impact=4, responsible='room01-floor-band.png', repair='repaint the floor near-black')]
DIAGNOSIS = 'The wall and the floor carry most of the difference; the door and platform already match and must be kept.'


class SceneFlow(ArtReviewFlow):
    def reach_integration_review(self):
        return self.reach_art_review()                               # the single art review is the final integration one

    def scene_files(self, name='scene', score=85, status=None, differences=None, tamper=None, blocked=False, diagnosis=DIAGNOSIS):
        folder = Path(self.temp.name) / 'scene'
        folder.mkdir(exist_ok=True)
        shot = folder / (name + '.png'); shot.write_bytes(png(size=24000 + len(name) + score))
        digest = hashlib.sha256(shot.read_bytes()).hexdigest()
        render = dict(schema='factory-scene-render/v1', renderer='engine-game-view', command=['engine', '--capture'], exit_code=0, scene='Scenes/Room01.unity',
                      project_dir=self.temp.name, screenshot=shot.name, screenshot_sha256=digest, width=1280, height=720, captured_at=1,
                      engine=dict(engine='Unity', engine_version='6000.4.11f1', graphics_device='Apple M1 Max', screenshot_sha256=digest),
                      completeness=dict(required=['V1', 'V2'], present=['V1', 'V2'], missing=[], deferred=[], complete=True))
        status = status or ('pass' if score >= 80 else 'fail')
        record = dict(schema='factory-scene-similarity/v1', model='m', threshold=80, reference=dict(path='docs/look/reference.png', sha256=self.loaded['references'][0]['sha256']),
                      screenshot=dict(path=str(shot), sha256=digest), score=None if blocked else score, differences=[] if (status == 'pass' or blocked) else (differences or DIFFS),
                      diagnosis='' if status == 'pass' else diagnosis, status='blocked' if blocked else status, problems=['no engine render'] if blocked else [])
        for key, value in (tamper or {}).items():
            (render if key.startswith('render_') else record)[key.removeprefix('render_')] = value
        return [self.write(self._stage, 'scene-render.json', render), self.write(self._stage, 'scene-similarity.json', record), str(shot)]

    def integration_review(self, stage, **kw):
        self._stage = stage
        files = self.scene_files(**{k: kw.pop(k) for k in ('name', 'score', 'status', 'differences', 'tamper', 'blocked', 'diagnosis') if k in kw})
        failing = kw.pop('failing', False)
        if failing:
            kw.update(holistic='reject', verdict='CHANGES_REQUIRED', findings=['F1|HIGH|AC1|Assets/Art/Room01/room01-wall-backdrop.png|[scene] 5/5 texture: the wall is nearly featureless | responsible: room01-wall-backdrop.png | repair: paint panels'])
        self.review(stage, mode='rendered_in_engine', extra=files, **kw)


class SceneGateCardTests(SceneFlow):
    def test_the_final_reviewer_is_told_to_score_the_complete_scene(self):
        integration = self.board.cards[self.reach_art_review()['task_id']]['body']
        for text in ('Full-scene similarity gate', 'COMPLETE assembled scene against the COMPLETE approved reference', 'never an isolated sprite', 'SCENE_SCORE --reference',
                     'never an image you generated', 'pass is 80/100', 'Never estimate or invent the score', 'unity_scene_capture.py --project PROJECT_DIR', '--required V1,V2',
                     'never trust the writer', 'preliminary composition', 'cannot be accepted'):
            self.assertIn(text, integration)


class IntegrationWriterCardTests(SceneFlow):
    def test_the_integration_writer_is_told_to_assemble_a_layout_and_capture_the_scene(self):
        self.finish_asset_task()
        card = self.board.cards[self.only('developer')['task_id']]['body']
        for text in ('Scene assembly (final integration with an approved reference)', 'art/scene/scene-layout.json', 'factory-scene-layout/v1', 'covers = the approved requirement ids',
                     'unity_scene_capture.py --project PROJECT_DIR', '--required V1,V2', 'a missing element is reported as missing', 'Never claim coverage for an asset that does not exist'):
            self.assertIn(text, card)

    def test_an_asset_task_writer_card_has_no_scene_assembly_text(self):
        self.approved_director()
        self.architect([self.visual_task(owner='artist')])
        self.finish(self.only('claude-reviewer'), 'Plan reviewed against the reference.', document='PLAN-REVIEW.md')
        self.assertNotIn('Scene assembly', self.board.cards[self.only('artist')['task_id']]['body'])


class SceneGateEvaluationTests(SceneFlow):
    def test_a_scene_at_or_above_80_passes_the_gate(self):
        self.integration_review(self.reach_integration_review(), score=80)
        self.assertEqual(self.document()['terminal']['phase'], 'delivered')   # the whole run is delivered on a passing scene
        self.assertEqual(self.document()['scene']['attempts'][-1]['score'], 80)
        self.assertTrue(scene_loop.passed(self.document()['scene']))

    def test_a_scene_below_80_goes_back_to_the_artist_with_the_ranked_diagnosis_recorded(self):
        self.integration_review(self.reach_integration_review(), score=62, failing=True)
        self.assertEqual([r['profile'] for r in self.board.ready()], ['artist'])
        scene = self.document()['scene']
        self.assertEqual((scene['attempts'][0]['score'], scene['attempts'][0]['status'], scene['best']['score']), (62, 'fail', 62))
        self.assertEqual([d['impact'] for d in scene['attempts'][0]['differences']], [5, 4])
        card = self.board.cards[self.only('artist')['task_id']]['body']
        for text in ('SCENE SCORE HISTORY', 'attempt 1: 62', 'responsible room01-wall-backdrop.png', 'metadata.scene_repair_plan', 'change only the responsible assets', 'Preserve it'):
            self.assertIn(text, card)

    def test_a_below_80_score_without_a_blocking_finding_or_a_ranked_diagnosis_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=62)       # fails but the reviewer reported no HIGH finding and CHANGES_REQUIRED
        self.assertIn('requires a blocking finding', self.terminal()['reason'])

    def test_a_missing_scene_evaluation_blocks_instead_of_receiving_a_score(self):
        self.integration_review(self.reach_integration_review(), blocked=True)
        self.assertIn('no score exists', self.terminal()['reason'])
        self.assertNotIn('scene', self.document())

    def test_a_scene_review_with_no_scene_similarity_record_at_all_blocks(self):
        self.review(self.reach_integration_review(), scene=False)          # no scene record at all
        self.assertIn('scene-similarity.json', self.terminal()['reason'])

    def test_a_score_for_a_screenshot_that_is_not_the_retained_render_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=95, tamper=dict(render_screenshot_sha256='0' * 64))
        self.assertIn('not the retained render', self.terminal()['reason'])

    def test_a_score_against_a_reference_nobody_approved_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=95, tamper=dict(reference=dict(path='x.png', sha256='1' * 64)))
        self.assertIn('human-approved reference', self.terminal()['reason'])

    def test_a_lowered_threshold_or_a_contradictory_score_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=70, status='pass', tamper=dict(threshold=60))
        self.assertIn('below the required 80', self.terminal()['reason'])


class SceneCompletenessTests(SceneFlow):
    MISSING = dict(required=['V1', 'V2'], present=['V1'], missing=['V2'], deferred=[], complete=False)

    def test_a_scene_that_scores_above_80_but_misses_required_elements_cannot_be_accepted(self):
        self.integration_review(self.reach_integration_review(), score=92, tamper=dict(render_completeness=self.MISSING))
        self.assertIn('misses required elements (V2)', self.terminal()['reason'])      # the reviewer approved a preliminary composition: refused
        self.assertNotEqual(self.terminal()['phase'], 'delivered')

    def test_an_incomplete_scene_with_a_blocking_finding_is_a_failed_attempt_that_goes_back_for_the_missing_elements(self):
        self.integration_review(self.reach_integration_review(), score=92, tamper=dict(render_completeness=self.MISSING), failing=True)
        self.assertEqual([r['profile'] for r in self.board.ready()], ['artist'])
        attempt = self.document()['scene']['attempts'][-1]
        self.assertEqual((attempt['score'], attempt['status']), (92, 'fail'))         # a high score does not make a missing element acceptable
        self.assertEqual(attempt['differences'][0]['aspect'], 'missing_detail')
        self.assertIn('V2', attempt['differences'][0]['description']); self.assertIn('incomplete', attempt['diagnosis'])
        self.assertFalse(scene_loop.passed(self.document()['scene']))

    def test_a_render_with_no_engine_attestation_is_refused(self):
        stage = self.reach_integration_review()
        self._stage = stage
        files = self.scene_files(score=95, tamper=dict(render_engine=None))
        self.review(stage, mode='rendered_in_engine', extra=files)
        self.assertIn('no engine attestation', self.terminal()['reason'])

    def test_an_attestation_for_a_different_screenshot_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=95, tamper=dict(render_engine=dict(engine='Unity', engine_version='6000.4.11f1', graphics_device='Apple M1 Max', screenshot_sha256='0' * 64)))
        self.assertIn('no engine attestation', self.terminal()['reason'])

    def test_a_capture_that_understates_what_the_reference_requires_is_refused(self):
        self.integration_review(self.reach_integration_review(), score=95, tamper=dict(render_completeness=dict(required=['V1'], present=['V1'], missing=[], deferred=[], complete=True)))
        self.assertIn('does not account for every required reference element', self.terminal()['reason'])

    def test_a_complete_attested_scene_at_80_is_delivered(self):
        self.integration_review(self.reach_integration_review(), score=80)
        self.assertEqual(self.document()['terminal']['phase'], 'delivered')


class FinalGateOwnsTheWholeGameTests(SceneFlow):
    MISSING = dict(required=['V1', 'V2'], present=['V1'], missing=['V2'], deferred=[], complete=False)

    def set_task_visual(self, ids):
        doc = self.document()
        doc['tasks'][0]['visual'] = ids
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(doc),)); self.conn.commit()

    def test_a_required_element_that_no_task_owns_sends_the_project_back_to_planning_not_to_a_repair(self):
        stage = self.reach_integration_review()
        self.set_task_visual(['V1'])                                        # nobody owns V2
        self.integration_review(stage, score=92, tamper=dict(render_completeness=self.MISSING), failing=True)
        self.assertEqual(self.document()['mode'], 'planning')
        self.assertIn('Required reference elements have no task: V2', self.document()['replan']['reason'])
        self.assertIn('not owned by any task', self.document()['replan']['findings'][0])
        self.assertEqual([r['profile'] for r in self.board.ready()], ['architect'])      # the legitimate planning workflow creates the task
        self.assertEqual(self.document()['replans'], 1)

    def test_when_the_replan_limit_is_reached_it_stops_for_a_human_and_does_not_extend_anything(self):
        stage = self.reach_integration_review()
        self.set_task_visual(['V1'])
        doc = self.document(); doc['replans'] = 2; doc.pop('replan_grants', None)
        self.conn.execute('UPDATE factory_project_execution SET document=?', (json.dumps(doc),)); self.conn.commit()
        self.integration_review(stage, score=92, tamper=dict(render_completeness=self.MISSING), failing=True)
        self.assertIn('replan limit is reached', self.terminal()['reason'])
        self.assertEqual(self.document()['replans'], 2)

    def test_a_missing_element_that_a_task_owns_is_repaired_not_replanned(self):
        self.integration_review(self.reach_integration_review(), score=92, tamper=dict(render_completeness=self.MISSING), failing=True)
        self.assertNotEqual(self.document().get('mode'), 'planning')
        self.assertEqual([r['profile'] for r in self.board.ready()], ['artist'])


class NoIntermediateArtReviewTests(SceneFlow):
    def test_the_panel_never_includes_the_art_reviewer_for_any_task_and_always_for_final_integration(self):
        from factory_dashboard.project_controller import ProjectController
        needs = dict(art=True, audio=False, ui=False, ux=False)
        for risk in ('normal', 'high'):
            panel = ProjectController._panel(['claude-reviewer', 'art-reviewer'], dict(id='sprites', needs=needs, risk=risk), {})
            self.assertNotIn('art-reviewer', panel, risk)
        self.assertIn('art-reviewer', ProjectController._panel(['claude-reviewer', 'art-reviewer'], dict(id='integration', needs=needs, risk='normal'), {}))

    def test_an_asset_task_with_a_failing_look_still_completes_and_the_game_moves_on(self):
        # Nothing visual can block a task: its technical checks passed, so it completes and the dependent integration starts.
        self.finish_asset_task()
        self.assertEqual([r['profile'] for r in self.board.ready()], ['developer'])
        self.assertIn('sprites' if False else self.document()['tasks'][0]['id'], [t['id'] for t in self.document()['completed']])

    def test_the_architect_is_told_the_only_art_review_is_the_final_one_and_that_every_requirement_needs_an_owner(self):
        self.approved_director()
        card = next(c for c in self.board.cards.values() if c['assignee'] == 'architect')['body']
        self.assertIn('ONE final gate on the complete, assembled and engine-rendered game', card)
        self.assertIn('no individual task is visually reviewed', card)
        self.assertIn('Every approved requirement must therefore be owned by a task', card)


class SceneLoopTests(unittest.TestCase):
    def attempt(self, state, n, score, diffs=DIFFS, repair=None, status=None):
        return scene_loop.record_attempt(state, task_id=f't_{n}', score=score, status=status or ('pass' if score >= 80 else 'fail'), screenshot_sha256=f'{n:064d}',
                                         differences=diffs, diagnosis=DIAGNOSIS, assets_sha256={'a.png': str(n)}, repair=repair)

    def plan(self, **kw):
        return dict(assets=['room01-wall-backdrop.png'], instructions='paint lighter charcoal panels with rivets', diagnosis_of_previous='The wall was nearly featureless and drove most of the gap.', **kw)

    def test_the_best_verified_result_survives_a_regression_and_a_tie_keeps_the_earlier_one(self):
        state = self.attempt(None, 1, 55)
        state = self.attempt(state, 2, 71)
        state = self.attempt(state, 3, 60)
        state = self.attempt(state, 4, 71)
        self.assertEqual((state['best']['n'], state['best']['score'], state['best']['assets_sha256']), (2, 71, {'a.png': '2'}))
        self.assertEqual([a['delta'] for a in state['attempts']], [None, 16, -11, 11])

    def test_a_blocked_or_fabricated_evaluation_is_never_recorded_as_an_attempt(self):
        for bad in (dict(status='blocked', score=None), dict(status='fail', score=None), dict(status='pass', score='90')):
            with self.assertRaises(ValueError):
                scene_loop.record_attempt(None, task_id='t', screenshot_sha256='x', differences=[], diagnosis='', **bad)

    def test_recording_is_idempotent_per_task(self):
        state = self.attempt(None, 1, 55)
        self.assertEqual(self.attempt(state, 1, 90), state)

    def test_a_repair_needs_a_diagnosis_of_the_previous_failure_and_only_touches_the_responsible_assets(self):
        state = self.attempt(None, 1, 55)
        self.assertEqual(scene_loop.check_repair_plan(state, self.plan()), [])
        self.assertTrue(scene_loop.check_repair_plan(state, dict(self.plan(), diagnosis_of_previous='too short')))
        blind = scene_loop.check_repair_plan(state, self.plan(new_reason='') | dict(assets=['room01-wall-backdrop.png', 'room01-door.png', 'room01-platform.png']))
        self.assertTrue(any('door.png' in p and 'platform.png' in p for p in blind))                       # do not blindly regenerate what matched
        self.assertEqual(scene_loop.check_repair_plan(state, self.plan(new_reason='the door seam shows on the wall render') | dict(assets=['room01-wall-backdrop.png', 'room01-door.png'])), [])
        self.assertTrue(scene_loop.check_repair_plan(state, dict(self.plan(), assets=[])))

    def test_an_unsuccessful_repair_cannot_be_repeated_without_a_new_reason(self):
        plan = self.plan()
        state = self.attempt(None, 1, 55)
        state = self.attempt(state, 2, 58, repair=dict(signature=scene_loop.signature(plan['assets'], plan['instructions'])))
        again = scene_loop.check_repair_plan(state, dict(plan, reconsidered=True))
        self.assertTrue(any('repeats an earlier' in p for p in again))
        self.assertEqual(scene_loop.check_repair_plan(state, dict(plan, reconsidered=True, new_reason='the earlier repair used the wrong palette file')), [])
        self.assertEqual(scene_loop.signature(['a'], 'Paint  the WALL'), scene_loop.signature(['a'], 'paint the wall'))   # spacing and case do not hide a repeat

    def test_no_improvement_requires_reconsidering_and_a_regression_requires_restoring_the_best(self):
        state = self.attempt(self.attempt(None, 1, 70), 2, 65)
        problems = scene_loop.check_repair_plan(state, self.plan())
        self.assertTrue(any('did not improve' in p for p in problems)); self.assertTrue(any('regressed' in p and 'restore the best' in p for p in problems))
        self.assertEqual(scene_loop.check_repair_plan(state, self.plan(reconsidered=True, restore_best=True)), [])

    def test_a_passed_scene_needs_no_repair(self):
        state = self.attempt(None, 1, 90)
        self.assertTrue(scene_loop.passed(state)); self.assertTrue(scene_loop.check_repair_plan(state, self.plan()))

    def test_the_brief_carries_history_remaining_differences_and_the_best_result(self):
        state = self.attempt(self.attempt(None, 1, 55), 2, 50)
        text = scene_loop.brief(state)
        for fragment in ('attempt 1: 55', 'attempt 2: 50 (-5)', 'Best verified result: attempt 1 at 55', '[impact 5]', 'responsible room01-wall-backdrop.png', 'reconsider the diagnosis'):
            self.assertIn(fragment, text)
        self.assertEqual(scene_loop.brief(None), '')

    def test_the_exhaustion_report_names_the_best_score_and_what_remains_without_asking_for_more_budget(self):
        report = scene_loop.exhaustion_report(self.attempt(self.attempt(None, 1, 55), 2, 62))
        for fragment in ('Repair budget exhausted', '55, 62', 'attempt 2 at 62', 'needs 80', 'nearly featureless'):
            self.assertIn(fragment, report)
        self.assertNotIn('extra_repairs', report)


class SceneRepairBudgetTests(SceneFlow):
    def fail_scene(self, score=62):
        self.integration_review(self.reach_integration_review(), score=score, failing=True)

    def test_a_repair_after_a_failed_scene_score_must_carry_its_plan_and_a_blind_repair_is_rejected(self):
        self.fail_scene()
        row = self.only('artist')
        self.board.complete(row, verdict='DONE'); self.tick()                         # no scene_repair_plan
        self.assertNotIn('scene_pending_repair', self.document())
        self.assertNotEqual(self.document().get('work', {}).get('step'), 'verifying')

    def test_a_repair_with_a_diagnosis_and_only_the_blamed_assets_is_accepted(self):
        self.fail_scene()
        plan = dict(assets=['room01-wall-backdrop.png'], instructions='paint lighter charcoal panels with seams and rivets', diagnosis_of_previous=DIAGNOSIS)
        self.board.complete(self.only('artist'), verdict='DONE', scene_repair_plan=plan); self.tick()
        self.assertEqual(self.document()['work']['step'], 'verifying')
        self.assertEqual(self.document()['scene_pending_repair']['assets'], ['room01-wall-backdrop.png'])

    def test_an_exhausted_budget_stops_for_a_human_with_the_remaining_differences_and_no_extra_budget(self):
        definition = json.loads(self.conn.execute('SELECT definition FROM factory_workflow_roots').fetchone()[0]); definition['max_repairs'] = 0
        self.conn.execute('UPDATE factory_workflow_roots SET definition=?', (json.dumps(definition),)); self.conn.commit()
        self.fail_scene(score=62)
        reason = self.terminal()['reason']
        self.assertIn('Repair budget exhausted', reason); self.assertIn('62', reason); self.assertIn('Repair limit reached', reason)
        self.assertEqual(self.document()['work'].get('extra_repairs', 0), 0)


if __name__ == '__main__':
    unittest.main()
