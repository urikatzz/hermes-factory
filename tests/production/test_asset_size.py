import json
import subprocess
import sys
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_production.sizing import CAP, CLASS_MAX, CLASS_MIN, SizingError, derive_size


class SizingTests(unittest.TestCase):
    def test_missing_pixel_dimensions_are_derived_from_the_reference_aspect_and_never_refused(self):
        sized = derive_size(aspect=1.5)
        self.assertEqual(sized['source'], 'derived')
        self.assertAlmostEqual(sized['width'] / sized['height'], 1.5, delta=0.01)
        self.assertIn('approved reference region', sized['reasoning'])

    def test_world_size_scales_the_pixel_size_and_keeps_the_proportions(self):
        small = derive_size(world=(1.7, 1.7))
        large = derive_size(world=(29.4, 4.9))
        self.assertEqual((small['width'], small['height']), (218, 218))                 # 1.7 units at 128 px per unit
        self.assertLess(small['width'], large['width'])                                   # a bigger thing in the world gets more pixels
        self.assertAlmostEqual(large['width'] / large['height'], 29.4 / 4.9, delta=0.2)
        self.assertEqual(derive_size(world=(1.7, 1.7), ppu=256)['width'], 435)           # the density is a parameter

    def test_derived_sizes_always_stay_inside_the_class_range_and_under_the_cap(self):
        for aspect in (0.05, 0.1, 0.25, 0.5, 1, 2, 4, 10, 20):
            for world in (None, (0.2, 0.2 / aspect), (3, 3 / aspect), (60, 60 / aspect)):
                try:
                    sized = derive_size(aspect=aspect, world=world)
                except SizingError:
                    continue                                                              # an unrepresentable aspect is refused, never clamped into a wrong shape
                self.assertTrue(CLASS_MIN <= sized['width'] <= CLASS_MAX and CLASS_MIN <= sized['height'] <= CLASS_MAX, (aspect, world, sized))
                self.assertLessEqual(max(sized['width'], sized['height']), CAP, (aspect, world, sized))
                self.assertAlmostEqual(sized['width'] / sized['height'], aspect, delta=aspect * 0.06 + 0.02, msg=(aspect, world, sized))

    def test_a_higher_cap_is_allowed_only_when_asked_for_explicitly_and_the_class_max_still_holds(self):
        self.assertEqual(max(derive_size(world=(30, 30), cap=2048)['width'], 0), 2048)
        self.assertEqual(derive_size(world=(60, 60), cap=99999)['width'], CLASS_MAX)       # never above the class maximum

    def test_an_explicit_size_takes_precedence_over_every_estimate(self):
        sized = derive_size(aspect=3.0, world=(9, 1), explicit=(300, 100))
        self.assertEqual((sized['width'], sized['height'], sized['source']), (300, 100, 'explicit'))
        self.assertEqual(derive_size(explicit=(2048, 32))['source'], 'explicit')         # inside the class range, however unusual

    def test_genuinely_contradictory_or_impossible_constraints_still_refuse(self):
        for kwargs, fragment in ((dict(explicit=(8, 8)), 'outside the class range'), (dict(explicit=(4096, 512)), 'outside the class range'),
                                 (dict(aspect=2.0, world=(1, 3)), 'contradictory'), (dict(aspect=80), 'cannot fit the class range'),
                                 (dict(), 'nothing to derive'), (dict(aspect=-1), 'positive'), (dict(aspect=float('nan')), 'positive'), (dict(world=(0, 1), aspect=1), 'positive')):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SizingError) as caught:
                    derive_size(**kwargs)
                self.assertIn(fragment, str(caught.exception))

    def test_the_plans_world_proportions_win_when_they_agree_with_the_reference_within_tolerance(self):
        sized = derive_size(aspect=1.0, world=(1.1, 1.0))
        self.assertAlmostEqual(sized['width'] / sized['height'], 1.1, delta=0.02)


class SizingCommandLineTests(unittest.TestCase):
    def run_cli(self, *args):
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/asset_size.py'), *args], capture_output=True, text=True)
        return done.returncode, json.loads(done.stdout) if done.stdout.strip() else {}

    def test_the_cli_prints_the_size_source_and_the_reasoning_to_copy_into_the_report(self):
        code, out = self.run_cli('--aspect', '1.5', '--world', '3x2')
        self.assertEqual((code, out['ok'], out['source']), (0, True, 'derived'))
        self.assertTrue(out['reasoning'] and out['width'] and out['height'])
        self.assertEqual(self.run_cli('--explicit', '256x512')[1]['source'], 'explicit')

    def test_a_contradiction_is_exit_3_with_the_reason_and_bad_arguments_are_exit_2(self):
        code, out = self.run_cli('--aspect', '2', '--world', '1x3')
        self.assertEqual((code, out['ok']), (3, False)); self.assertIn('contradictory', out['error'])
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/asset_size.py'), '--world', 'huge'], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


class SizingInstructionTests(unittest.TestCase):
    def test_the_artist_skill_states_the_rule(self):
        text = (ROOT / 'art_production/install/SKILL.md').read_text()
        for fragment in ('Sizing when the task gives no pixel size', 'never a reason to block', 'explicit beats any estimate', "approved reference and take its aspect ratio",
                         'world size from the plan', '32 to 2048 px per side', 'caps the long side at 1024', 'record the pixel size, the world size', 'SIZE', 'exits 3'):
            self.assertIn(fragment, text)

    def test_the_artist_skill_explains_edge_contact_and_fragments(self):
        text = (ROOT / 'art_production/install/SKILL.md').read_text()
        for fragment in ('edge_contact', 'fragment_count', '--drop-fragments-below', '--margin 2', 'never removes the largest group', 'regenerate the image rather than deleting it'):
            self.assertIn(fragment, text)

    def test_the_task_writing_skill_asks_for_world_sizes_and_forbids_inventing_pixel_requirements(self):
        text = (ROOT / 'runtime/factory-skills/worker/task-writing/SKILL.md').read_text()
        for fragment in ('Asset sizes and placement', 'world size', 'unspecified pixel size is an implementation decision', 'not a new mandatory field'):
            self.assertIn(fragment, text)

    def test_the_installer_ships_the_sizing_tool(self):
        self.assertIn('asset_size.py', (ROOT / 'scripts/install_art_production.sh').read_text())


if __name__ == '__main__':
    unittest.main()
