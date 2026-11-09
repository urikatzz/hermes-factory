import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import TESTGAME_EXPECTED, build_testgame, sprite
from factory_art.lint import collect, run_lint
from factory_art.png import write_png

ROOT = Path(__file__).resolve().parents[2]


class LintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = build_testgame(Path(self.temp.name) / 'game')
        self.out = Path(self.temp.name) / 'lint'

    def tearDown(self):
        self.temp.cleanup()

    def test_collect_skips_hidden_engine_and_bible_dirs(self):
        files = collect(self.repo)
        self.assertIn('Assets/Art/Characters/hero.png', files)
        self.assertFalse([f for f in files if f.startswith(('.git/', 'Library/', 'art/style/'))])
        with self.assertRaises(ValueError):
            collect(self.repo, ['../outside'])

    def test_testgame_produces_exactly_the_expected_findings(self):
        result = run_lint(self.repo, self.out, blender=None)
        self.assertEqual(sorted((f['severity'], f['check'], f['file']) for f in result['findings']), TESTGAME_EXPECTED)
        self.assertEqual(result['unverified'], [{'file': 'Assets/Models/crate.glb', 'cause': 'environment',
                                                 'reason': 'Blender not found'}])
        self.assertEqual(result['blocked_tools'][0]['cmd'], 'blender')
        self.assertTrue(result['lint_blocking'])
        self.assertEqual(json.loads((self.out / 'lint.json').read_text())['lines'], result['lines'])
        hero = next(a for a in result['assets'] if a['file'] == 'Assets/Art/Characters/hero.png')
        self.assertEqual((hero['rules'], len(hero['images']), hero['vision']), (['S1', 'S2'], 3, True))
        self.assertTrue(hero['references'][0].endswith('art/style/reference/hero.png'))

    def test_image_budget_respects_first(self):
        result = run_lint(self.repo, self.out, blender=None, first=['Assets/Art/Characters/opaque.png'], max_images=4)
        reviewed = [a['file'] for a in result['assets'] if a['vision'] and a['images']]
        self.assertEqual(reviewed, ['Assets/Art/Characters/opaque.png'])
        self.assertIn('Assets/Art/Characters/hero.png', result['not_reviewed'])
        self.assertEqual(result['images'], 4)

    def test_view_dirs_do_not_collide(self):
        from factory_art.lint import _slug
        self.assertNotEqual(_slug('a/b__c.png'), _slug('a__b/c.png'))

    def test_severity_override_applies_per_class(self):
        style = self.repo / 'art/style/style.json'
        data = json.loads(style.read_text())
        data['classes'][0]['severity'] = {'alpha': 'LOW'}
        style.write_text(json.dumps(data))
        found = run_lint(self.repo, self.out, blender=None)['findings']
        self.assertIn(('LOW', 'alpha'), [(f['severity'], f['check']) for f in found])

    def test_missing_bible_blocks_only_when_art_exists(self):
        empty = Path(self.temp.name) / 'empty'
        (empty / 'src').mkdir(parents=True)
        (empty / 'src/main.py').write_text('')
        self.assertEqual(run_lint(empty, self.out)['art_files'], 0)
        self.assertEqual(run_lint(empty, self.out)['findings'], [])
        write_png(empty / 'src/hero.png', sprite())
        found = run_lint(empty, self.out)['findings']
        self.assertEqual([(f['severity'], f['check']) for f in found], [('BLOCKER', 'bible')])

    def test_cli_summary_and_bad_path(self):
        cli = [sys.executable, str(ROOT / 'scripts/art_lint.py'), str(self.repo), '--out', str(self.out),
               '--blender', '/nonexistent/blender']
        completed = subprocess.run(cli, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual((summary['findings'], summary['unverified']), (len(TESTGAME_EXPECTED), 1))
        bad = subprocess.run(cli + ['../escape'], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn('not an existing path inside', bad.stderr)
