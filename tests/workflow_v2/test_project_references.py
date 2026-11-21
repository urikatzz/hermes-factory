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
                 (dict(observations=[dict(topic='palette', region=[0.1, 0.1, 0.3, 0.3], observation='Charcoal walls with amber accents everywhere')]), 'does not cover'),
                 (dict(observations=[dict(topic=t, observation=f'Concrete description of the {t} the image shows') for t in TOPICS]), 'region'),
                 (dict(observations=[dict(topic=t, region=[0.0, 0.0, 0.2, 0.2], observation=f'Concrete description of the {t} the image shows {i}') for i, t in enumerate(TOPICS)]), 'identical region'),
                 (dict(observations=[dict(topic=t, region=[0.0, 0.0, 0.2, 0.2 + i / 100], observation=f'Concrete description of the {t} the image shows {i}') for i, t in enumerate(TOPICS)]), 'describes only')]
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

    def test_the_lints_renders_of_an_asset_count_as_viewing_that_asset_only(self):
        seen = ['/ws/t_1/lint/views/Assets__Art__Room01__room01-door.png/grey.png', '/ws/t_1/other/Assets__Art__Room01__room01-wall.png/grey.png']
        self.assertTrue(refs.viewed_via_lint_views('room01-door.png', seen))
        self.assertFalse(refs.viewed_via_lint_views('room01-wall.png', seen))   # not under lint/views
        self.assertFalse(refs.viewed_via_lint_views('room01-doo.png', seen))    # the name must match exactly
        self.assertFalse(refs.viewed_via_lint_views('door.png', seen))
        self.assertFalse(refs.viewed_via_lint_views('room01-door.png', []))

    def test_viewed_images_lists_only_successful_calls(self):
        image = Path(self.temp.name) / 'docs/look/reference.png'
        home = Path(self.temp.name) / 'home'
        record_session(home, 'art-reviewer', 'local-' + 'a' * 64, [image])
        record_session(home, 'art-reviewer', 'local-' + 'b' * 64, [image], succeeded=False)
        self.assertEqual(refs.viewed_images('art-reviewer', 'local-' + 'a' * 64, home), [str(image)])
        self.assertEqual(refs.viewed_images('art-reviewer', 'local-' + 'b' * 64, home), [])

    def test_vision_proof_accepts_the_current_hermes_session_id_format_and_still_rejects_malformed_ids(self):
        image = Path(self.temp.name) / 'docs/look/reference.png'
        home = Path(self.temp.name) / 'home'
        current = 'local-' + 'e73da9898541af5e35ee499d81e8c9fe7b40fed13dbbfde0b44c7a9437c1ac51'  # 70 characters, as Hermes issues them now
        older = '20261120_201753_f9024d'
        record_session(home, 'architect', current, [image])
        record_session(home, 'architect', older, [image])
        wanted = {'lookd': image}
        self.assertEqual(len(current), 70)
        self.assertEqual(refs.vision_proof('architect', current, home, wanted), [])
        self.assertEqual(refs.vision_proof('architect', older, home, wanted), [])
        for bad in ('', 'short', 'has space in it', "x'; DROP TABLE messages;--", 'a' * 129, 12345):
            with self.subTest(bad=bad):
                with self.assertRaisesRegex(ConfigurationError, 'no worker session'):
                    refs.vision_proof('architect', bad, home, wanted)

    def test_a_controller_running_inside_a_profile_still_finds_the_hermes_root(self):
        root = Path(self.temp.name) / 'hermes'
        inside = root / 'profiles' / 'factory-orchestrator'
        self.assertEqual(refs.hermes_root({'HERMES_HOME': str(inside)}, '/nowhere'), root)
        self.assertEqual(refs.hermes_root({'HERMES_HOME': str(root)}, '/nowhere'), root)
        self.assertEqual(refs.hermes_root({}, root), root)
        self.assertEqual(refs.hermes_root({'FACTORY_HERMES_HOME': str(root), 'HERMES_HOME': str(inside)}, '/nowhere'), root)
        for profile in ('art-director', 'architect'):
            (root / 'profiles' / profile).mkdir(parents=True, exist_ok=True)
            (root / 'profiles' / profile / 'config.yaml').write_text('platform_toolsets:\n  cli:\n  - kanban\n  - vision\n')
        self.assertIsNone(refs.vision_problem('art-director', refs.hermes_root({'HERMES_HOME': str(inside)}, '/nowhere')))

    def test_a_deleted_scratch_file_counts_only_where_the_worker_made_it_itself(self):
        home = Path(self.temp.name) / 'home'
        gone = Path(self.temp.name) / 'scratch' / 'plan-mockup.png'
        record_session(home, 'architect', 'sessionSSSS', [gone])
        retained = Path(self.temp.name) / 'retained' / 'plan-mockup.png'
        retained.parent.mkdir()
        retained.write_bytes(b'png')
        self.assertEqual(refs.vision_proof('architect', 'sessionSSSS', home, {'plan-mockup': retained}), ['plan-mockup'])
        self.assertEqual(refs.vision_proof('architect', 'sessionSSSS', home, {'plan-mockup': retained}, scratch_ok={'plan-mockup'}), [])
        other = Path(self.temp.name) / 'retained' / 'other.png'
        other.write_bytes(b'x')
        self.assertEqual(refs.vision_proof('architect', 'sessionSSSS', home, {'plan-mockup': other}, scratch_ok={'plan-mockup'}), ['plan-mockup'])
        gone_ref = Path(self.temp.name) / 'ref-copy' / 'reference.png'
        record_session(home, 'architect', 'sessionTTTT', [gone_ref])
        self.assertEqual(refs.vision_proof('architect', 'sessionTTTT', home, {'lookd': Path(self.temp.name) / 'docs/look/reference.png'}), ['lookd'])  # references stay strict

    def test_the_plain_contradiction_that_started_this_is_found_in_the_bible_and_in_plans(self):
        rule = 'S9 (blocking) Deferred look: no hazard stripes, crosshair corner marks or painted art (GDD milestone 6).'
        found = refs.find_contradictions(self.records, {'art/style/STYLE.md': 'S1 Palette is charcoal.\n' + rule})
        self.assertEqual([(c['kind'], c['requirement'], c['line']) for c in found if c['kind'] == 'forbids'], [('forbids', 'V1', 2)])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'Draw hazard stripes on the platform and the door frame.'}), [])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'No cast shadows, no reflections.'}), [])

    def test_faithful_plan_sentences_the_first_scan_wrongly_rejected_are_accepted(self):
        faithful = write_project(self.temp.name, [dict(REFERENCE, requirements=[
            dict(id='V1', text='stripes', keywords=['hazard stripe', 'corner mark', 'untextured']),
            dict(id='V2', text='slanted segments', keywords=['slanted', 'gradient', 'painted'])])], extra=MILESTONE_ONE)['references']
        for sentence in (
                '5. Rendering (V2): painted matte art with panel wear and texture; no cast shadows, no floor reflections, no gradient-based fake shadows.',
                '6. Floor and walls: the GDD says "flat and matte" while the reference shows painted texture and wear. The plan interprets this as matte (no gloss), not untextured. Confirm.',
                '4. Procedural only (no image generation): HUD health segments drawn as slanted parallelograms (V2), divider, frame counter text, corner marks, message text in amber stencil.',
                'REQUEST: No grey-box presentation, placeholder artwork or simplified geometry stands in for the approved direction. Painted sprites are produced with the art skill.',
                'No placeholder art and no simplified geometry: V1 hazard stripes and V2 slanted segments are built as shown.',
                'The current palette.txt has no steel grey and no hazard stripe colour, so the bible must be amended before V1 hazard stripes can be checked.',
                'T1 amends STYLE.md to remove the superseded greybox-only rules and add painted classes that carry V1 hazard stripes and V2 slanted segments.',
                'Room01PresentationTests assert V1 hazard stripes and V2 slanted segments through the L-rules and the presence of spark effects instead of greybox assertions that every sprite is WhiteSquare.',
                'style.json gains painted classes for V1 hazard stripes and V2 slanted segments. The existing WhiteSquare blockout class keeps its current file pattern.',
                'SUPERSEDED (rewrite, do not preserve): AC10 grey-box assertions for V1 hazard stripes; greybox-only assertions replaced by V2 slanted segment checks.'):
            self.assertEqual(refs.find_contradictions(faithful, {'PLAN.md': sentence}), [], sentence)

    def test_the_original_failures_are_still_caught_verbatim_after_the_precision_fix(self):
        original_s1 = ('S1 (blocking) Grey-box only: every world object is the existing `Assets/Art/GreyBox/WhiteSquare.png` sprite tinted by a palette colour. '
                       'No new textures, gradients, outlines, particles, cast shadows, extra lights or post-processing; one Global Light 2D only.')
        original_s9 = 'S9 Deferred look: no hazard stripes, crosshair corner marks, frame counter, target heads, joints, strobe prop or painted art (GDD milestone 6).'
        loaded = write_project(self.temp.name, [dict(REFERENCE, requirements=[
            dict(id='V1', text='a', keywords=['hazard stripe', 'crosshair', 'frame counter', 'target head', 'joint']),
            dict(id='V2', text='b', keywords=['painted', 'texture', 'gradient', 'particle'])])], extra=MILESTONE_ONE)['references']
        found = refs.find_contradictions(loaded, {'STYLE.md': original_s1 + '\n' + original_s9})
        pairs = {(c['kind'], c['requirement']) for c in found}
        self.assertEqual(pairs, {('forbids', 'V1'), ('forbids', 'V2'), ('implicit_deferral', 'V1')})
        by_line = {(c['line'], c['requirement']) for c in found if c['kind'] == 'forbids'}
        self.assertEqual(by_line, {(1, 'V2'), (2, 'V1'), (2, 'V2')})  # S1 forbids V2's texture/gradient/particle; S9 forbids V1's stripes/crosshair/joints and V2's painted art
        self.assertTrue({c['keyword'] for c in found if c['kind'] == 'implicit_deferral'} >= {'grey-box only', 'deferred look'})

    def test_instead_of_a_simplification_is_accepted_but_the_simplification_itself_is_not(self):
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'V1 hazard stripes are painted instead of greybox rectangles.'}), [])
        found = refs.find_contradictions(self.records, {'PLAN.md': 'V1 hazard stripes are delivered as greybox rectangles instead of painted trim.'})
        self.assertEqual({c['kind'] for c in found}, {'implicit_deferral'})

    def test_keeping_an_existing_class_is_not_a_deferral_but_delivering_the_requirement_as_one_is(self):
        found = refs.find_contradictions(self.records, {'PLAN.md': 'V1 hazard stripes are delivered as blockout rectangles and the look stays that way.'})
        self.assertEqual({c['kind'] for c in found}, {'implicit_deferral'})

    def test_a_removal_word_far_from_the_simplification_does_not_excuse_it(self):
        far = 'We removed the old compiler warnings last week and then reviewed every other open item at length, and meanwhile V1 hazard stripes are delivered as placeholder rectangles.'
        self.assertEqual({c['kind'] for c in refs.find_contradictions(self.records, {'PLAN.md': far})}, {'implicit_deferral'})
        near = 'V1 hazard stripes: the placeholder rectangles are removed and replaced by painted trim.'
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': near}), [])

    def test_a_negation_does_not_reach_across_a_new_idea_or_a_bracket(self):
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'No cloth physics, the hazard stripe trim is drawn on the door frame.'}), [])
        self.assertEqual(refs.find_contradictions(self.records, {'PLAN.md': 'No time is lost (hazard stripe trim is built first).'}), [])
        self.assertNotEqual(refs.find_contradictions(self.records, {'PLAN.md': 'Never include hazard stripe trim on the door.'}), [])
        self.assertNotEqual(refs.find_contradictions(self.records, {'STYLE.md': 'S9 Look: no hazard stripe colour.'}), [])

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


class RoleFindingTests(unittest.TestCase):
    """Role-specific, image-grounded findings: a successful vision call is necessary but not sufficient."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.records = write_project(self.temp.name, [REFERENCE], extra=MILESTONE_ONE)['references']
        self.loaded = dict(references=self.records)
        self.tasks = [dict(id='look', visual=['V1', 'V2'])]

    def findings(self, kind, **kwargs):
        from reference_fixture import role_findings
        return dict(role_findings=role_findings(self.loaded, kind, self.tasks, ['shot.png'], **kwargs))

    def test_each_role_has_its_own_valid_form(self):
        refs.validate_role_findings(self.findings('achieve'), self.records, 'achieve')
        refs.validate_role_findings(self.findings('carry'), self.records, 'carry', self.tasks)
        refs.validate_role_findings(self.findings('plan_check'), self.records, 'plan_check')
        refs.validate_role_findings(self.findings('render_check'), self.records, 'render_check', screenshots=['shot.png'])

    def test_a_finding_per_demanded_requirement_is_required_and_a_future_one_is_not(self):
        record = self.findings('achieve')
        record['role_findings'].pop()
        with self.assertRaisesRegex(ConfigurationError, 'Missing achieve findings.*V2'):
            refs.validate_role_findings(record, self.records, 'achieve')
        self.assertEqual(sorted(r['id'] for r in refs.required_requirements(self.records)), ['V1', 'V2'])

    def test_a_generic_copied_or_ungrounded_finding_is_rejected(self):
        for change, message in ((dict(finding='fine'), 'empty, repeated'),
                                (dict(finding='Hazard stripes on platforms and the door frame'), 'restates the requirement'),
                                (dict(region=None), 'region'), (dict(region=[0.9, 0.9, 0.5, 0.5]), 'impossible region'),
                                (dict(subject='magic'), 'generated.*procedural.*hybrid')):
            record = self.findings('achieve')
            record['role_findings'][0].update(change)
            with self.assertRaisesRegex(ConfigurationError, message):
                refs.validate_role_findings(record, self.records, 'achieve')
        three = write_project(self.temp.name, [REFERENCE], extra=dict(milestone=3))['references']
        from reference_fixture import role_findings
        record = dict(role_findings=role_findings(dict(references=three), 'achieve'))
        for entry in record['role_findings']:
            entry['region'] = [0.1, 0.1, 0.2, 0.2]
        with self.assertRaisesRegex(ConfigurationError, 'reuse the same few regions'):
            refs.validate_role_findings(record, three, 'achieve')

    def test_requirements_that_concern_the_whole_image_may_share_a_region(self):
        three = write_project(self.temp.name, [REFERENCE], extra=dict(milestone=3))['references']
        from reference_fixture import role_findings
        record = dict(role_findings=role_findings(dict(references=three), 'achieve'))
        record['role_findings'][1]['region'] = record['role_findings'][0]['region']  # three findings, two share the whole-image box
        refs.validate_role_findings(record, three, 'achieve')

    def test_the_error_names_the_offending_entry_and_the_exact_reason(self):
        for change, message in ((dict(kind='carry'), r'entry #1 has kind .carry.; your role writes kind "achieve"'),
                                (dict(requirement_id='V99'), r'entry #1 names requirement_id .V99.'),
                                (dict(requirement_id='V2'), 'two entries for V2')):
            record = self.findings('achieve')
            record['role_findings'][0].update(change)
            with self.assertRaisesRegex(ConfigurationError, message):
                refs.validate_role_findings(record, self.records, 'achieve')

    def test_a_finding_for_a_known_requirement_scheduled_for_later_is_allowed_but_not_demanded(self):
        record = self.findings('achieve')
        record['role_findings'].append(dict(kind='achieve', requirement_id='V3', subject='generated', region=[0.5, 0.5, 0.2, 0.2],
                                            finding='In the image the readout area shows detail that a later milestone will reproduce exactly'))
        refs.validate_role_findings(record, self.records, 'achieve')

    def test_the_architect_must_name_a_task_that_really_carries_the_requirement(self):
        record = self.findings('carry')
        record['role_findings'][0]['subject'] = 'elsewhere'
        with self.assertRaisesRegex(ConfigurationError, 'must name in "subject" a task'):
            refs.validate_role_findings(record, self.records, 'carry', self.tasks)
        with self.assertRaisesRegex(ConfigurationError, 'must name in "subject" a task'):
            refs.validate_role_findings(self.findings('carry'), self.records, 'carry', [dict(id='look', visual=['V1'])])

    def test_a_plan_reviewer_who_finds_a_weakened_requirement_must_also_raise_a_blocking_finding(self):
        record = self.findings('plan_check', V2=dict(verdict='weakened'))
        with self.assertRaisesRegex(ConfigurationError, 'weakened V2 needs a BLOCKER/HIGH finding'):
            refs.validate_role_findings(record, self.records, 'plan_check')
        refs.validate_role_findings(record, self.records, 'plan_check', findings=['F1|HIGH|AC1|plan|V2 is weakened to flat bars'])

    def test_an_art_reviewer_who_sees_a_difference_must_block_and_name_real_screenshots(self):
        record = self.findings('render_check', V1=dict(verdict='differs'))
        with self.assertRaisesRegex(ConfigurationError, 'differs V1 needs a BLOCKER/HIGH.*CHANGES_REQUIRED'):
            refs.validate_role_findings(record, self.records, 'render_check', screenshots=['shot.png'], verdict='NO_BLOCKING_FINDINGS',
                                        findings=['F1|HIGH|AC1|shot.png|V1 stripes missing'])
        refs.validate_role_findings(record, self.records, 'render_check', screenshots=['shot.png'], verdict='CHANGES_REQUIRED', findings=['F1|HIGH|AC1|shot.png|V1 stripes missing'])
        with self.assertRaisesRegex(ConfigurationError, 'retained rendered screenshot'):
            refs.validate_role_findings(self.findings('render_check'), self.records, 'render_check', screenshots=['other.png'])

    def test_the_art_plan_needs_every_section_and_a_real_mockup(self):
        from reference_fixture import ART_PLAN_BLOCK, png
        refs.validate_art_plan('# Plan\n' + ART_PLAN_BLOCK)
        for name in ('procedural', 'milestone', 'mockup', 'compar'):
            lines = [l for l in ART_PLAN_BLOCK.splitlines() if not (l.startswith('#') and name in l.lower())]
            with self.assertRaisesRegex(ConfigurationError, 'no section'):
                refs.validate_art_plan('\n'.join(lines))
        folder = Path(self.temp.name)
        (folder / 'plan-mockup.png').write_bytes(png())
        self.assertEqual(refs.plan_mockup([str(folder / 'plan-mockup.png')]), folder / 'plan-mockup.png')
        (folder / 'plan-mockup.png').write_bytes(png(300, 200))
        self.assertIsNone(refs.plan_mockup([str(folder / 'plan-mockup.png')]))
        (folder / 'plan-mockup.png').write_bytes(b'not a png' * 5000)
        self.assertIsNone(refs.plan_mockup([str(folder / 'plan-mockup.png')]))


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
        # The card names the exact originals to open, and says a copy in a snapshot or scratch folder cannot be verified.
        expected = str(Path(context['project_dir']) / 'docs/look/reference.png') if context.get('project_dir') else None
        self.assertIn('Open exactly these absolute paths with vision_analyze: ', body)
        self.assertRegex(body, r'Open exactly these absolute paths with vision_analyze: /\S+/docs/look/reference\.png')
        self.assertIn('Do not open a copy of an approved image', body)
        self.assertIn('deleted before the stage is checked', body)
        if expected:
            self.assertIn(expected, body)

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

    def test_an_art_plan_without_the_required_sections_or_the_mockup_is_not_offered_for_approval(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2 carried.', art_plan=False)
        self.assertIn('no section', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])
        self.finish(self.only('art-director'), 'V1 V2 carried.', mockup=False)
        self.assertIn('no representative mockup', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])

    def test_the_director_must_have_looked_at_its_own_mockup_and_the_human_sees_where_it_is(self):
        self.start()
        stage = self.only('art-director')
        folder = Path(self.temp.name) / 'unseen'
        folder.mkdir()
        self.finish(stage, 'V1 V2 carried.', viewed=False, shots_viewed=[])
        self.assertIn('shows no successful vision_analyze call', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])
        self.finish(self.only('art-director'), 'V1 V2 carried.')
        self.assertTrue(self.document()['awaiting']['mockup'].endswith('plan-mockup.png'))
        self.assertIn('mockup:', self.state.read_root(self.conn, self.root)['reason'])

    def test_a_director_finding_without_a_production_approach_or_a_region_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2 carried.', per_requirement=dict(V1=dict(subject='whatever')))
        self.assertIn('generated, procedural, hybrid', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])

    def test_a_director_plan_that_forbids_what_the_reference_shows_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2. Deferred look: no hazard stripes until milestone 6.')
        _, context = self.rejection('art-director')
        self.assertIn('Scan candidates in PLAN.md', context['previous_handoff_rejected']['reason'])

    def test_a_director_plan_that_drops_a_requirement_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'Only V1 is planned.')
        _, context = self.rejection('art-director')
        self.assertIn('does not carry approved visual requirement(s): V2', context['previous_handoff_rejected']['reason'])

    def test_attachments_stored_twice_with_the_same_bytes_are_one_artifact(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2 carried.', duplicates=True)
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')  # reached the human approval gate, not 'expected one retained'
        self.assertTrue(self.document()['awaiting']['mockup'].endswith('plan-mockup.png'))

    def test_numbered_copies_that_differ_stay_ambiguous(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2 carried.', duplicates='different')
        self.assertIn('Expected one retained reference-inspection.json', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])

    def test_a_requirement_a_human_scoped_to_a_later_milestone_is_not_demanded_now(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 and V2 only; the combo readout waits for milestone 3.')
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')  # awaiting the ordinary human approval

    def test_an_architect_plan_that_does_not_trace_the_requirements_is_sent_back_off_the_replan_budget(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'The room looks right'})])
        stage, context = self.rejection('architect')
        self.assertEqual(stage['evidence_retry'], 1)
        self.assertIn('no acceptance criterion states it', context['previous_handoff_rejected']['reason'])
        self.assertEqual(self.document().get('replans', 0), 0)

    def test_an_architect_that_leaves_a_requirement_with_no_carrying_task_is_sent_back_with_the_task_rule(self):
        self.approved_director()
        self.architect([self.visual_task(visual=['V1'], acceptance={'AC1': 'V1 only'})])
        _, context = self.rejection('architect')
        self.assertIn('must name in "subject" a task of project-plan.json whose "visual" list has V2', context['previous_handoff_rejected']['reason'])

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

    def test_recovery_never_re_approves_changed_references_only_an_explicit_phrase_does(self):
        self.approved_director()
        (self.project / 'docs/look/reference.png').write_bytes(b'a different image')
        self.tick()
        self.assertIn('references changed', self.terminal()['reason'])
        while self.board.ready():
            self.board.complete(self.board.ready()[0])
            self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')
        with self.assertRaisesRegex(Exception, 'Recovery alone never re-approves references'):
            self.controller.resume(self.conn, self.root, 'Retry: infrastructure recovered')
        digest = refs.load_references(self.project)['digest'][:12]
        self.controller.resume(self.conn, self.root, f'Retry after a human replaced the image. APPROVE-REFERENCES {digest}')
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'project')

    def test_a_project_without_references_is_unaffected(self):
        (self.project / 'docs/references.json').unlink()
        self.start()
        self.board.complete(self.only('art-director'))
        self.tick()
        self.assertEqual(self.state.read_root(self.conn, self.root)['phase'], 'blocked')  # awaiting the ordinary human art-plan approval


if __name__ == '__main__':
    unittest.main()
