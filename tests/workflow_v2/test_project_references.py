"""An approved visual reference cannot be silently ignored, replaced, contradicted, deferred or faked by downstream planning and review."""
import json
from pathlib import Path
import tempfile
import unittest

from factory_dashboard import project_references as refs
from factory_dashboard.model_policy import ConfigurationError
from reference_fixture import NEEDS, ReferenceFlow, TOPICS, inspection, record_session, write_project

REFERENCE = dict(
    id='lookd', path='docs/look/reference.png', roles=['visual_reference', 'immutable'], authority='human_approved', title='Approved look',
    requirements=[dict(id='V1', text='Hazard stripes on platforms and the door frame', keywords=['hazard stripe']),
                  dict(id='V2', text='Slanted amber health segments top left', keywords=['slanted']),
                  dict(id='V3', text='A combo readout top right', keywords=['combo readout'], introduced_at=3)],
    deferrals=[])
MILESTONE_ONE = dict(milestone=1)


class ReferenceModuleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.loaded = write_project(self.temp.name, [REFERENCE], extra=MILESTONE_ONE)
        self.records = self.loaded['references']

    def test_roles_are_a_set_so_a_file_is_immutable_and_an_authoritative_visual_reference_but_not_a_production_asset(self):
        record = self.records[0]
        self.assertEqual(set(record['roles']), {'visual_reference', 'immutable'})
        self.assertNotIn('production_asset', record['roles'])
        self.assertEqual([r['id'] for r in refs.authoritative(self.records)], ['lookd'])
        with self.assertRaisesRegex(ConfigurationError, 'roles'):
            write_project(self.temp.name, [{**REFERENCE, 'roles': ['mockup']}])

    def test_an_example_or_derived_file_is_not_authoritative(self):
        self.assertEqual(refs.authoritative(write_project(self.temp.name, [{**REFERENCE, 'roles': ['example']}], extra=MILESTONE_ONE)['references']), [])
        self.assertEqual(refs.authoritative(write_project(self.temp.name, [{**REFERENCE, 'authority': 'derived'}], extra=MILESTONE_ONE)['references']), [])

    def test_a_gdd_that_names_a_reference_image_is_enough_even_without_a_references_file(self):
        (Path(self.temp.name) / 'docs/references.json').unlink()
        (Path(self.temp.name) / 'docs/GDD.md').write_text('Look D. Reference image: `docs/look/reference.png` (direction only, not a game asset).\n')
        loaded = refs.load_references(self.temp.name)
        reference = loaded['references'][0]
        self.assertEqual((loaded['source'], reference['authority'], 'visual_reference' in reference['roles']), ('docs/GDD.md', 'human_approved', True))
        self.assertEqual([r['id'] for r in refs.required_requirements(loaded['references'])], ['V1'])

    def test_a_changed_image_is_reported_against_the_approved_hash(self):
        write_project(self.temp.name, [dict(REFERENCE, sha256=self.records[0]['sha256'])], extra=MILESTONE_ONE)
        (Path(self.temp.name) / 'docs/look/reference.png').write_bytes(b'replaced by a mockup')
        self.assertIn('changed since it was approved', ' '.join(refs.load_references(self.temp.name)['problems']))

    def test_only_a_human_can_defer_and_only_a_listed_requirement(self):
        for deferral in (dict(requirement='V1', until='milestone 6', reason='later', approved_by='agent'),
                         dict(requirement='V9', until='milestone 6', reason='later', approved_by='human'),
                         dict(requirement='V1', until='', reason='later', approved_by='human')):
            with self.assertRaisesRegex(ConfigurationError, 'deferral'):
                write_project(self.temp.name, [{**REFERENCE, 'deferrals': [deferral]}], extra=MILESTONE_ONE)
        loaded = write_project(self.temp.name, [{**REFERENCE, 'deferrals': [dict(requirement='V1', until='milestone 6', reason='no art yet', approved_by='human')]}],
                               extra=MILESTONE_ONE)
        self.assertEqual([r['id'] for r in refs.required_requirements(loaded['references'])], ['V2'])

    def test_milestone_scoping_is_a_human_decision_in_the_file_never_an_inference(self):
        self.assertEqual([r['id'] for r in refs.required_requirements(self.records)], ['V1', 'V2'])  # V3 arrives at milestone 3, set by a human
        later = write_project(self.temp.name, [REFERENCE], extra=dict(milestone=3))
        self.assertEqual([r['id'] for r in refs.required_requirements(later['references'])], ['V1', 'V2', 'V3'])
        with self.assertRaisesRegex(ConfigurationError, 'introduced_at.*milestone'):
            write_project(self.temp.name, [REFERENCE])  # a scoped requirement without a human-set milestone is refused

    def test_a_reference_path_cannot_leave_the_project(self):
        with self.assertRaisesRegex(ConfigurationError, 'relative|leaves'):
            write_project(self.temp.name, [{**REFERENCE, 'path': '../outside.png'}], extra=MILESTONE_ONE)

    def test_inspection_must_be_bound_to_the_exact_image_and_say_what_it_shows(self):
        self.assertTrue(refs.validate_inspection(inspection(self.loaded), self.records))
        cases = [(dict(sha256='0' * 64), 'different image'), (dict(tool='human'), 'vision_analyze'), (dict(tool='guess'), 'vision_analyze'),
                 (dict(requirement_ids=['V1']), 'cite every requirement'),
                 (dict(observations=[dict(topic=t, observation='ok') for t in TOPICS]), 'empty, repeated'),
                 (dict(observations=[dict(topic='palette', observation='Charcoal walls with amber accents everywhere')]), 'does not cover')]
        for change, message in cases:
            with self.assertRaisesRegex(ConfigurationError, message):
                refs.validate_inspection(inspection(self.loaded, **change), self.records)
        with self.assertRaisesRegex(ConfigurationError, 'was not inspected'):
            refs.validate_inspection(dict(schema=refs.INSPECTION_SCHEMA, references=[]), self.records)

    def test_vision_proof_needs_a_successful_tool_call_on_that_exact_file(self):
        image = Path(self.temp.name) / 'docs/look/reference.png'
        home = Path(self.temp.name) / 'home'
        record_session(home, 'architect', 'sessionAAAA', [image])
        record_session(home, 'architect', 'sessionBBBB', [image], succeeded=False)
        other = Path(self.temp.name) / 'other.png'
        other.write_bytes(b'something else')
        record_session(home, 'architect', 'sessionCCCC', [other])
        copy = Path(self.temp.name) / 'copy.png'
        copy.write_bytes(image.read_bytes())
        record_session(home, 'architect', 'sessionDDDD', [copy])
        wanted = {'lookd': image}
        self.assertEqual(refs.vision_proof('architect', 'sessionAAAA', home, wanted), [])
        self.assertEqual(refs.vision_proof('architect', 'sessionBBBB', home, wanted), ['lookd'])   # the tool call failed
        self.assertEqual(refs.vision_proof('architect', 'sessionCCCC', home, wanted), ['lookd'])   # a different file was opened
        self.assertEqual(refs.vision_proof('architect', 'sessionDDDD', home, wanted), [])          # same bytes at another path counts
        self.assertEqual(refs.vision_proof('architect', 'sessionZZZZ', home, wanted), ['lookd'])   # no such calls
        with self.assertRaisesRegex(ConfigurationError, 'no worker session'):
            refs.vision_proof('architect', None, home, wanted)
        with self.assertRaisesRegex(ConfigurationError, 'unreadable'):
            refs.vision_proof('nobody', 'sessionAAAA', home, wanted)

    def test_the_plain_contradiction_that_started_this_is_found_in_the_bible_and_in_plans(self):
        rule = 'S9 (blocking) Deferred look: no hazard stripes, crosshair corner marks or painted art (GDD milestone 6).'
        found = refs.find_contradictions(self.records, {'art/style/STYLE.md': 'S1 Palette is charcoal.\n' + rule})
        self.assertEqual([(c['kind'], c['requirement'], c['line']) for c in found if c['kind'] == 'forbids'], [('forbids', 'V1', 2)])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'Draw hazard stripes on the platform and the door frame.'}), [])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'No cast shadows, no reflections.'}), [])

    def test_a_conforming_rule_that_merely_contains_a_negation_elsewhere_is_not_flagged(self):
        rule = 'S9 Room 1 presents hazard stripes and a HUD that does not exist yet for weapons. S1 slanted segments; do not count blockout squares.'
        self.assertEqual(refs.find_contradictions(self.records, {'STYLE.md': rule}), [])
        postponed = refs.find_contradictions(self.records, {'PLAN.md': 'The hazard stripe trim is out of scope until milestone 6.'})
        self.assertEqual({c['requirement'] for c in postponed}, {'V1'})

    def test_grey_box_or_placeholder_next_to_a_requirement_is_an_implicit_deferral(self):
        for text in ('V1 is delivered as generic grey-box rectangles for now.', 'The hazard stripe trim uses placeholder squares.',
                     'Slanted segments are simplified to flat bars.'):
            found = refs.find_contradictions(self.records, {'PLAN.md': text})
            self.assertEqual({c['kind'] for c in found}, {'implicit_deferral'}, text)
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'The solid-colour sprite stays byte-identical while V1 stripes are painted.'}), [])
        self.assertEqual([c['kind'] for c in refs.find_contradictions(self.records, {'STYLE.md': 'S1 Grey-box only: every world object is a tinted square.'})], ['implicit_deferral'])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'Milestone 1 is grey-box gameplay: movement and jump.'}), [])
        carried = refs.find_contradictions(self.records, {'task look': 'Placeholder art is fine'}, {'task look': ['V1']})
        self.assertEqual({(c['kind'], c['requirement']) for c in carried}, {('implicit_deferral', 'V1')})

    def test_a_future_requirement_is_not_contradicted_by_saying_it_comes_later(self):
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'The combo readout is out of scope until milestone 3.'}), [])

    def test_a_factory_mockup_can_never_be_the_comparison_target(self):
        mock = dict(id='mock', path='art/style/mock.png', roles=['example'], authority='derived', requirements=[], deferrals=[])
        (Path(self.temp.name) / 'art/style').mkdir(parents=True)
        (Path(self.temp.name) / 'art/style/mock.png').write_bytes(b'mockup')
        records = write_project(self.temp.name, [REFERENCE, mock], extra=MILESTONE_ONE)['references']
        for text in ('Similarity >= 0.80 against art/style/mock.png', '"references": ["mock.png"]'):
            found = refs.find_contradictions(records, {'art/style/style.json': text})
            self.assertEqual([c['kind'] for c in found], ['derived_source'], text)
        self.assertEqual(refs.find_contradictions(records, {'PLAN.md': 'Compare against docs/look/reference.png (lookd); mock.png is an example only.'}), [])

    def test_only_a_human_deferral_removes_a_contradiction(self):
        loaded = write_project(self.temp.name, [{**REFERENCE, 'deferrals': [dict(requirement='V1', until='milestone 6', reason='art later', approved_by='human')]}], extra=MILESTONE_ONE)
        self.assertEqual(refs.find_contradictions(loaded['references'], {'s': 'No hazard stripes in this milestone.'}), [])

    def task(self, ident, acceptance, visual=None, owner='developer'):
        return dict(id=ident, title=ident, owner=owner, dependencies=[], acceptance=acceptance, needs=NEEDS, **({'visual': visual} if visual is not None else {}))

    def test_every_approved_requirement_must_be_traced_into_a_task_acceptance(self):
        both = self.task('look', {'AC1': 'V1 hazard stripes and V2 segments are visible in the render'}, ['V1', 'V2'])
        self.assertEqual(refs.validate_traceability(self.records, [both]), ['V1', 'V2'])
        with self.assertRaisesRegex(ConfigurationError, 'not traced.*V2'):
            refs.validate_traceability(self.records, [self.task('look', {'AC1': 'V1 stripes'}, ['V1'])])
        with self.assertRaisesRegex(ConfigurationError, 'unknown visual'):
            refs.validate_traceability(self.records, [self.task('look', {'AC1': 'V1 V2 V7'}, ['V1', 'V2', 'V7'])])
        with self.assertRaisesRegex(ConfigurationError, 'no acceptance criterion states it'):
            refs.validate_traceability(self.records, [self.task('look', {'AC1': 'Looks nice'}, ['V1', 'V2'])])

    def test_a_contradicting_bible_must_be_amended_by_an_artist_task_that_names_it(self):
        bible = refs.find_contradictions(self.records, {'art/style/STYLE.md': 'S9: no hazard stripes'})
        plain = self.task('look', {'AC1': 'V1 V2 shown'}, ['V1', 'V2'])
        with self.assertRaisesRegex(ConfigurationError, 'contradicts approved requirement V1'):
            refs.validate_traceability(self.records, [plain], bible)
        fix = self.task('bible', {'AC1': 'V1: art/style/STYLE.md no longer forbids hazard stripes'}, ['V1'], owner='artist')
        self.assertTrue(refs.validate_traceability(self.records, [fix, plain], bible))

    def test_a_profile_without_the_vision_toolset_cannot_be_the_inspector(self):
        with tempfile.TemporaryDirectory() as home:
            for name, toolsets in (('seer', ['kanban', 'vision']), ('blind', ['kanban', 'file', 'terminal'])):
                folder = Path(home) / 'profiles' / name
                folder.mkdir(parents=True)
                (folder / 'config.yaml').write_text('model:\n  provider: x\nplatform_toolsets:\n  cli:\n' + ''.join(f'  - {t}\n' for t in toolsets) + 'kanban:\n  dispatch: false\n')
            self.assertIsNone(refs.vision_problem('seer', home))
            self.assertIn('lack', refs.vision_problem('blind', home))
            self.assertIn('unreadable', refs.vision_problem('missing', home))

    def comparison(self, **change):
        reference = self.records[0]
        record = dict(references=[dict(id='lookd', sha256=reference['sha256'])], evidence=['/x/shot.png'],
                      criteria=[dict(rule='V1: stripes', expected='stripes', observed='stripes', outcome='pass'),
                                dict(rule='V2: segments', expected='slanted', observed='slanted', outcome='pass'),
                                dict(rule='HOLISTIC', expected='same look', observed='same look', outcome='pass')],
                      holistic=dict(verdict='accept', summary='Whole screenshot reads as the approved look: the same dark lab, tan dummies, amber accents, slanted HUD and hazard trim at similar scale. ' * 2,
                                    dimensions={t: 'matches' for t in TOPICS}, screenshots=['shot.png']))
        record.update(change)
        return record

    def test_the_comparison_must_cite_the_original_judge_each_requirement_and_the_whole(self):
        self.assertTrue(refs.validate_reference_comparison(self.comparison(), self.records))
        base = self.comparison()['holistic']
        cases = [(dict(references=[dict(id='mockup', sha256='1' * 64)]), 'cite every approved reference'),
                 (dict(criteria=[dict(rule='V1: s', expected='a', observed='b', outcome='pass'), dict(rule='HOLISTIC', expected='a', observed='b', outcome='pass')]), 'no criterion.*V2'),
                 (dict(holistic=None), 'holistic'),
                 (dict(holistic={**base, 'summary': 'fine'}), 'holistic summary'),
                 (dict(holistic={**base, 'dimensions': {t: 'matches' for t in TOPICS[:-1]}}), 'dimensions'),
                 (dict(holistic={**base, 'screenshots': ['other.png']}), 'screenshots'),
                 (dict(holistic={**base, 'dimensions': {**{t: 'matches' for t in TOPICS}, 'palette': 'differs'}}), 'differs')]
        for change, message in cases:
            with self.assertRaisesRegex(ConfigurationError, message):
                refs.validate_reference_comparison(self.comparison(**change), self.records)

    def test_every_requirement_passing_does_not_make_a_rejected_whole_acceptable(self):
        rejected = self.comparison(holistic={**self.comparison()['holistic'], 'verdict': 'reject'})
        with self.assertRaisesRegex(ConfigurationError, 'HOLISTIC.*equals the holistic verdict'):
            refs.validate_reference_comparison(rejected, self.records)  # all V pass but the whole is rejected: recording a pass is contradictory
        rejected['criteria'][2]['outcome'] = 'fail'
        self.assertTrue(refs.validate_reference_comparison(rejected, self.records))  # recorded honestly, the whole fails
        with self.assertRaisesRegex(ConfigurationError, 'HOLISTIC'):
            refs.validate_reference_comparison(self.comparison(criteria=self.comparison()['criteria'][:2]), self.records)

    def test_a_comparison_that_leans_on_a_mockup_is_refused(self):
        mock = dict(id='mock', path='art/style/mock.png', roles=['example'], authority='derived', requirements=[], deferrals=[])
        (Path(self.temp.name) / 'art/style').mkdir(parents=True)
        (Path(self.temp.name) / 'art/style/mock.png').write_bytes(b'mockup')
        records = write_project(self.temp.name, [REFERENCE, mock], extra=MILESTONE_ONE)['references']
        record = self.comparison(references=[dict(id='lookd', sha256=records[0]['sha256'])])
        record['criteria'][0]['expected'] = 'matches art/style/mock.png'
        with self.assertRaisesRegex(ConfigurationError, 'factory-made mockup'):
            refs.validate_reference_comparison(record, records)


class ReferenceWorkflowTests(ReferenceFlow):
    """Through the real controller: planning cannot start, pass or finish while ignoring the approved reference."""
    REFERENCES = [REFERENCE]
    EXTRA = MILESTONE_ONE

    def test_every_stage_card_carries_the_authority_hierarchy_and_the_approved_reference_but_the_scope_stage_does_not(self):
        self.tick()
        scope = self.only('factory-orchestrator')
        self.assertNotIn('approved_references', self.board.cards[scope['task_id']]['body'])
        self.assertNotIn('Authority order', self.board.cards[scope['task_id']]['body'])
        self.board.complete(scope, project_scope={**NEEDS, 'art': True})
        self.tick()
        stage, context = self.rejection('art-director')
        body = self.board.cards[stage['task_id']]['body']
        self.assertIn('human-approved decisions and references > GDD > style bible', body)
        self.assertIn('is an implicit', body)
        self.assertIn('open every approved reference image yourself with', body)
        reference = context['approved_references'][0]
        self.assertEqual((reference['path'], reference['sha256'], reference['milestone']), ('docs/look/reference.png', self.loaded['references'][0]['sha256'], 1))
        self.assertEqual([r['id'] for r in reference['requirements']], ['V1', 'V2', 'V3'])

    def test_a_director_that_never_opened_the_reference_is_sent_back_with_the_exact_reason(self):
        self.start()
        self.finish(self.only('art-director'), 'Plan covers V1 and V2.', inspected=False)
        stage, context = self.rejection('art-director')
        self.assertEqual(stage['evidence_retry'], 1)
        self.assertIn('Reference inspection rejected', context['previous_handoff_rejected']['reason'])

    def test_a_perfectly_formatted_inspection_without_the_vision_tool_calls_is_rejected(self):
        self.start()
        self.finish(self.only('art-director'), 'Plan covers V1 and V2.', viewed=False)
        _, context = self.rejection('art-director')
        self.assertIn('shows no successful vision_analyze call', context['previous_handoff_rejected']['reason'])

    def test_a_failed_or_misdirected_vision_call_is_not_an_inspection(self):
        self.start()
        self.finish(self.only('art-director'), 'Plan covers V1 and V2.', succeeded=False)
        _, context = self.rejection('art-director')
        self.assertIn('shows no successful vision_analyze call', context['previous_handoff_rejected']['reason'])

    def test_a_director_plan_that_forbids_what_the_reference_shows_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2. Deferred look: no hazard stripes until milestone 6.')
        _, context = self.rejection('art-director')
        self.assertIn('contradicts, defers or replaces approved reference requirements', context['previous_handoff_rejected']['reason'])

    def test_a_director_plan_that_drops_a_requirement_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'Only V1 is planned.')
        _, context = self.rejection('art-director')
        self.assertIn('does not carry approved visual requirement(s): V2', context['previous_handoff_rejected']['reason'])

    def test_a_requirement_a_human_scoped_to_a_later_milestone_is_not_demanded_now(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 and V2 only; the combo readout waits for milestone 3.')
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')  # awaiting the ordinary human approval

    def test_an_architect_plan_that_does_not_trace_the_requirements_is_sent_back_off_the_replan_budget(self):
        self.approved_director()
        self.architect([self.visual_task(visual=['V1'], acceptance={'AC1': 'V1 only'})])
        stage, context = self.rejection('architect')
        self.assertEqual(stage['evidence_retry'], 1)
        self.assertIn('not traced into any task acceptance: V2', context['previous_handoff_rejected']['reason'])
        self.assertEqual(self.document().get('replans', 0), 0)

    def test_task_acceptance_that_excludes_an_approved_characteristic_is_sent_back(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 V2 shown; the slanted segments stay out of scope until milestone 6'})])
        _, context = self.rejection('architect')
        self.assertIn('Task acceptance contradicts, defers or replaces', context['previous_handoff_rejected']['reason'])

    def test_a_plan_that_reduces_the_look_to_generic_grey_box_is_sent_back(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 V2: the room uses generic grey-box placeholder rectangles'})])
        _, context = self.rejection('architect')
        self.assertIn('implicit_deferral', context['previous_handoff_rejected']['reason'])

    def test_a_factory_mockup_as_the_acceptance_target_is_sent_back(self):
        (self.project / 'art/style').mkdir(parents=True)
        (self.project / 'art/style/mock.png').write_bytes(b'mockup')
        mock = dict(id='mock', path='art/style/mock.png', roles=['example'], authority='derived', requirements=[], deferrals=[])
        write_project(self.project, [REFERENCE, mock], extra=MILESTONE_ONE)
        self.loaded = refs.load_references(self.project)
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 V2: similarity >= 0.80 against art/style/mock.png'})])
        _, context = self.rejection('architect')
        self.assertIn('derived_source', context['previous_handoff_rejected']['reason'])

    def test_a_contradicting_existing_bible_demands_an_artist_task_that_amends_it(self):
        (self.project / 'art/style').mkdir(parents=True)
        (self.project / 'art/style/STYLE.md').write_text('S9 Deferred look: no hazard stripes.\n')
        self.approved_director()
        self.architect([self.visual_task()])
        _, context = self.rejection('architect')
        self.assertIn('art/style/STYLE.md', context['previous_handoff_rejected']['reason'])

    def test_a_traced_plan_reaches_a_plan_reviewer_who_must_open_the_reference_too(self):
        self.approved_director()
        self.architect([self.visual_task()])
        reviewer = self.only('claude-reviewer')
        body = self.board.cards[reviewer['task_id']]['body']
        self.assertIn('Reference audit (mandatory)', body)
        self.assertIn('open every approved reference image yourself', body)
        self.board.complete(reviewer)
        self.tick()
        _, context = self.rejection('claude-reviewer')
        self.assertIn('Reference inspection rejected', context['previous_handoff_rejected']['reason'])

    def test_a_profile_that_cannot_open_images_never_gets_the_visual_stage(self):
        self.vision(['art-director', 'claude-reviewer', 'art-reviewer'], blind=['architect'])
        self.approved_director()
        self.assertIn('Visual capability missing', self.terminal()['reason'])
        self.assertIn('architect cannot inspect', self.terminal()['reason'])
        self.assertFalse(self.conn.execute("SELECT 1 FROM factory_workflow_stages WHERE profile='architect'").fetchone())

    def test_replacing_the_reference_image_mid_run_stops_for_a_human(self):
        self.approved_director()
        (self.project / 'docs/look/reference.png').write_bytes(b'a factory mockup swapped in')
        self.tick()
        self.assertIn('references changed', self.terminal()['reason'])
        self.assertEqual(self.terminal()['phase'], 'blocked')

    def test_promoting_a_mockup_or_rewriting_the_authority_mid_run_needs_a_human(self):
        self.approved_director()
        document = json.loads((self.project / 'docs/references.json').read_text())
        document['references'][0]['authority'] = 'derived'
        (self.project / 'docs/references.json').write_text(json.dumps(document))
        self.tick()
        self.assertIn('references changed', self.terminal()['reason'])

    def test_a_project_without_references_is_unaffected(self):
        (self.project / 'docs/references.json').unlink()
        self.start()
        self.board.complete(self.only('art-director'))
        self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')  # awaiting the ordinary human art-plan approval


if __name__ == '__main__':
    unittest.main()
