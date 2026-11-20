"""End-to-end regression for the original failure, and proof that reference authority is project-agnostic.

The original failure: a human approved a look image; the GDD named it; a derived style bible then said "Grey-box only ... Deferred look: no hazard stripes,
crosshair corner marks, frame counter, target heads, joints, strobe prop or painted art", the plan reduced the presentation to generic grey-box assets, and
nothing noticed. Here the same inputs run through the real controller and must be stopped at the gate that owns each defect."""
from pathlib import Path
import unittest

from factory_dashboard import project_references as refs
from reference_fixture import NEEDS, ReferenceFlow, write_project

# Verbatim from the failing run's art/style/STYLE.md.
ORIGINAL_S1 = ('S1 (blocking) Grey-box only: every world object is the existing `Assets/Art/GreyBox/WhiteSquare.png` sprite tinted by a palette colour. '
               'No new textures, gradients, outlines, particles, cast shadows, extra lights or post-processing; one Global Light 2D only.')
ORIGINAL_S9 = ('S9 Deferred look: no hazard stripes, crosshair corner marks, frame counter, target heads, joints, strobe prop or painted art (GDD milestone 6). '
               'The HUD is amber on dark.')
GDD = ('# Game\n\nDecided: the look is "High-speed camera". Reference image: `docs/look/look-d.png` (direction only, not a game asset).\n\n'
       '## Milestones\n\n1. Grey-box playable: movement, jump, one room.\n6. Art to the look above, then audio.\n')


class OriginalFailure(ReferenceFlow):
    """Approved reference adopted from the GDD alone (as in the original project: no references file), a contradictory bible, a grey-box plan."""
    REFERENCE_PATH = 'docs/look/look-d.png'

    def prepare(self):
        (self.project / 'docs/look').mkdir(parents=True)
        (self.project / 'docs/look/look-d.png').write_bytes(b'the human-approved look image')
        (self.project / 'docs/GDD.md').write_text(GDD)
        (self.project / 'art/style').mkdir(parents=True)
        (self.project / 'art/style/STYLE.md').write_text('# Grey-box presentation rules\n\n' + ORIGINAL_S1 + '\n' + ORIGINAL_S9 + '\n')

    def reasons(self, profile='architect'):
        return self.rejection(profile)[1]['previous_handoff_rejected']['reason']

    def test_the_reference_is_adopted_from_the_gdd_and_its_requirement_is_required(self):
        self.assertEqual([r['id'] for r in refs.authoritative(self.loaded['references'])], ['ref1'])
        self.assertEqual([r['id'] for r in refs.required_requirements(self.loaded['references'])], ['V1'])

    def test_a_director_plan_that_postpones_the_look_is_sent_back(self):
        self.start()
        self.finish(self.only('art-director'), 'V1: Grey-box only. Deferred look until milestone 6.')
        self.assertIn('implicit_deferral', self.reasons('art-director'))

    def test_the_grey_box_plan_the_factory_once_accepted_is_now_sent_back(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 Grey-box look: every world SpriteRenderer uses the WhiteSquare sprite, no new image files'})])
        reason = self.reasons()
        self.assertIn('Task acceptance contradicts, defers or replaces', reason)
        self.assertIn('implicit_deferral', reason)

    def test_a_plan_that_never_carries_the_reference_into_a_task_is_sent_back(self):
        self.approved_director()
        self.architect([self.visual_task(visual=[], acceptance={'AC1': 'Room is playable with generic art'})])
        self.assertIn('not traced into any task acceptance: V1', self.reasons())

    def test_the_contradictory_bible_blocks_a_plan_that_does_not_amend_it(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 the presentation follows the approved image'})])
        reason = self.reasons()
        self.assertIn('art/style/STYLE.md', reason)
        self.assertIn('Plan an artist task that amends it', reason)

    def test_the_corrected_plan_reaches_a_plan_reviewer_who_must_open_the_image(self):
        self.approved_director()
        amend = dict(id='bible', title='Amend the bible', owner='artist', dependencies=[], needs={**NEEDS, 'art': True}, visual=['V1'],
                     acceptance={'AC1': 'V1: art/style/STYLE.md no longer defers or forbids the approved look'})
        look = self.visual_task(id='look', dependencies=['bible'], acceptance={'AC1': 'V1 the presentation follows the approved image in the rendered game'})
        self.architect([amend, look])
        reviewer = self.only('claude-reviewer')
        self.assertIn('Reference audit (mandatory)', self.board.cards[reviewer['task_id']]['body'])


class OtherProject(ReferenceFlow):
    """A different kind of project: no engine, another file layout and format, other ids and topics. The authority system must not care."""
    REFERENCE_PATH = 'art/refs/board.jpg'
    REFERENCES_FILE = 'art/references.json'
    REFERENCES = [dict(
        id='board', path='art/refs/board.jpg', roles=['visual_reference'], authority='human_approved', title='Approved board mock',
        topics=['layout', 'typography', 'colour'],
        requirements=[dict(id='V1', text='A dark navy board with neon cyan tiles and rounded corners', keywords=['neon', 'rounded corners']),
                      dict(id='V2', text='Bold rounded sans-serif score text top centre', keywords=['score text'])],
        deferrals=[])]

    def test_the_whole_flow_works_with_another_layout_and_nothing_project_specific(self):
        self.approved_director()
        self.architect([self.visual_task()])
        self.only('claude-reviewer')

    def test_the_same_gates_hold_there(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 V2 shown, placeholder tiles are fine'})])
        self.assertIn('implicit_deferral', self.rejection('architect')[1]['previous_handoff_rejected']['reason'])

    def test_a_forbidding_rule_in_another_vocabulary_is_caught(self):
        self.approved_director()
        self.architect([self.visual_task(acceptance={'AC1': 'V1 V2; no neon tiles in this release'})])
        self.assertIn('forbids', self.rejection('architect')[1]['previous_handoff_rejected']['reason'])

    def test_inspection_topics_come_from_the_reference(self):
        self.start()
        _, context = self.rejection('art-director')
        self.assertEqual(context['approved_references'][0]['inspect_topics'], ['layout', 'typography', 'colour'])

    def test_the_vision_check_is_a_session_log_check_not_a_json_check(self):
        self.start()
        self.finish(self.only('art-director'), 'V1 V2', viewed=False)
        self.assertIn('shows no successful vision_analyze call', self.rejection('art-director')[1]['previous_handoff_rejected']['reason'])


class NoProjectSpecificCode(unittest.TestCase):
    def test_the_authority_system_names_no_particular_game_engine_or_look(self):
        from factory_dashboard import project_cards
        source = Path(refs.__file__).read_text() + ''.join(
            getattr(project_cards, name) for name in ('APPROVED_REFERENCES', 'INSPECTION', 'VISUAL_TRACE', 'REFERENCE_AUDIT', 'APPROVED_COMPARISON'))
        for word in ('impact', 'unity', 'look d', 'room01', 'whitesquare', 'crash', 'dummy', 'hazard'):
            self.assertNotIn(word, source.lower(), word)


if __name__ == '__main__':
    unittest.main()
