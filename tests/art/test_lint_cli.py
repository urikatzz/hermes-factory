import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame, sprite, write_bible
from factory_art.png import write_png

ROOT = Path(__file__).resolve().parents[2]
LINT = ROOT / 'scripts/art_lint.py'
CLEAN_CLASSES = [{'name': 'icon', 'kind': 'sprite', 'match': ['Assets/**'],
                  'size': {'width': [16, 64], 'height': [16, 64]}, 'alpha': 'required', 'rules': ['S1']}]


def lint(*args):
    return subprocess.run([sys.executable, str(LINT), *map(str, args)], capture_output=True, text=True)


class LintCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def clean_repo(self):
        repo = self.root / 'clean'
        write_bible(repo, CLEAN_CLASSES)
        (repo / 'Assets').mkdir()
        write_png(repo / 'Assets/hero.png', sprite())
        return repo

    def test_fail_on_blocking_exits_1_only_with_blocking_findings(self):
        game = build_testgame(self.root / 'game')
        plain = lint(game, '--out', self.root / 'a', '--blender', '/nonexistent')
        self.assertEqual(plain.returncode, 0, plain.stderr)
        gate = lint(game, '--out', self.root / 'b', '--blender', '/nonexistent', '--fail-on-blocking')
        self.assertEqual(gate.returncode, 1, gate.stderr)
        self.assertTrue(json.loads(gate.stdout)['lint_blocking'])
        clean = lint(self.clean_repo(), '--out', self.root / 'c', '--fail-on-blocking')
        self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
        self.assertEqual(json.loads(clean.stdout)['findings'], 0)

    def test_art_without_a_bible_fails_the_gate(self):
        repo = self.root / 'nobible'
        (repo / 'Assets').mkdir(parents=True)
        write_png(repo / 'Assets/hero.png', sprite())
        self.assertEqual(lint(repo, '--out', self.root / 'd', '--fail-on-blocking').returncode, 1)

    def test_check_bible_reports_classes_or_the_error(self):
        ok = lint(build_testgame(self.root / 'game'), '--check-bible')
        self.assertEqual(ok.returncode, 0, ok.stderr)
        data = json.loads(ok.stdout)
        self.assertEqual(data['bible'], 'ok')
        self.assertEqual(data['classes'], ['character_sprite', 'prop_model', 'ui_copy'])
        self.assertEqual(data['rules'], ['S1', 'S2', 'T1'])
        (self.root / 'empty').mkdir()
        bad = lint(self.root / 'empty', '--check-bible')
        self.assertEqual(bad.returncode, 1)
        self.assertEqual(json.loads(bad.stdout)['bible'], 'invalid')
        self.assertIn('art/style/style.json not found', json.loads(bad.stdout)['error'])

    def test_out_is_required_without_check_bible(self):
        result = lint(self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn('--out is required', result.stderr)

    def test_style_hash_is_stable_and_changes_with_the_bible(self):
        repo = self.clean_repo()
        first = lint(repo, '--style-hash')
        self.assertEqual(first.returncode, 0, first.stderr)
        digest = json.loads(first.stdout)['style_sha256']
        self.assertRegex(digest, '^[0-9a-f]{64}$')
        self.assertEqual(json.loads(lint(repo, '--style-hash').stdout)['style_sha256'], digest)
        (repo / 'art/style/extra.txt').write_text('x')
        self.assertNotEqual(json.loads(lint(repo, '--style-hash').stdout)['style_sha256'], digest)

    def test_expect_style_hash_blocks_when_art_style_changed(self):
        repo = self.clean_repo()
        digest = json.loads(lint(repo, '--style-hash').stdout)['style_sha256']
        same = lint(repo, '--out', self.root / 'e', '--fail-on-blocking', '--expect-style-hash', digest)
        self.assertEqual(same.returncode, 0, same.stdout + same.stderr)
        style = repo / 'art/style/STYLE.md'
        style.write_text(style.read_text() + '\nS9: anything goes\n')
        changed = lint(repo, '--out', self.root / 'f', '--fail-on-blocking', '--expect-style-hash', digest)
        self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
        found = json.loads((self.root / 'f/lint.json').read_text())['findings']
        self.assertIn({'severity': 'BLOCKER', 'check': 'style', 'file': 'art/style',
                       'problem': 'art/style changed during an asset task'}, found)
