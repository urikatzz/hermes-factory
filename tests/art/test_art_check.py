import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame

ROOT = Path(__file__).resolve().parents[2]
STUB = """#!/bin/sh
printf '%s\\n' "$@" > "$ART_STUB_LOG"
echo stub report > "$(dirname "$ART_STUB_LOG")/out/report.md"
"""


class ArtCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = build_testgame(self.root / 'game')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'hermes').write_text(STUB)
        (bin_dir / 'hermes').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', ART_STUB_LOG=str(self.root / 'args.txt'),
                        ART_CHECK_OUT=str(self.root / 'out'))

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self, *paths):
        return subprocess.run(['sh', str(ROOT / 'scripts/art_check.sh'), str(self.repo), *paths],
                              capture_output=True, text=True, env=self.env)

    def test_copies_art_privately_and_runs_profile_once(self):
        completed = self.run_check('Assets/Art')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = self.root / 'out'
        self.assertIn(f'REPORT={out}/report.md', completed.stdout)
        self.assertTrue((out / 'src/art/style/style.json').is_file())
        self.assertTrue((out / 'src/Assets/Art/Characters/hero.png').is_file())
        self.assertFalse((out / 'src/Assets/Models').exists())
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        query = (out / 'query.txt').read_text()
        self.assertIn('MODE=standalone', query)
        self.assertIn(f'SRC_DIR={out}/src', query)
        self.assertIn(f'LINT=python3 {ROOT}/scripts/art_lint.py', query)
        args = (self.root / 'args.txt').read_text().split('\n')
        self.assertEqual(args[:3], ['-p', 'art-reviewer', 'chat'])
        self.assertIn('art-review', args)
        self.assertIn(str(out / 'query.txt'), args)

    def test_whole_repo_skips_hidden_and_engine_dirs(self):
        self.assertEqual(self.run_check().returncode, 0)
        src = self.root / 'out/src'
        self.assertTrue((src / 'Assets/Models/crate.glb').is_file())
        self.assertFalse((src / '.git').exists())
        self.assertFalse((src / 'Library').exists())

    def test_rejects_symlink_escapes_and_dash_names(self):
        (self.root / 'secret').mkdir()
        (self.root / 'secret/key.png').write_text('secret')
        (self.repo / 'link').symlink_to('../secret')
        (self.repo / 'Assets/out').symlink_to('../../secret')
        for path in ('link', 'link/', 'link/key.png', 'Assets/out/key.png'):
            with self.subTest(path=path):
                self.assertEqual(self.run_check(path).returncode, 2)
                self.assertFalse((self.root / 'out/src/key.png').exists())
                self.assertFalse((self.root / 'args.txt').exists())
        (self.repo / '-n').mkdir()
        (self.repo / '-n/a.png').write_text('x')
        completed = self.run_check('-n')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue((self.root / 'out/src/-n/a.png').is_file())

    def test_rejects_escaping_and_missing_paths(self):
        for path in ('../x', '/etc', 'Assets/../../x', 'missing'):
            with self.subTest(path=path):
                completed = self.run_check(path)
                self.assertEqual(completed.returncode, 2)
                self.assertFalse((self.root / 'args.txt').exists())
