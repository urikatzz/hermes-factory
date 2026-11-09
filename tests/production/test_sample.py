import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT


class SampleTests(unittest.TestCase):
    def test_sample_has_a_valid_bible_and_refuses_a_non_empty_folder(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / 'art-sample'
            made = subprocess.run([sys.executable, str(ROOT / 'scripts/make_art_sample.py'), str(folder)],
                                  capture_output=True, text=True)
            self.assertEqual(made.returncode, 0, made.stderr)
            check = subprocess.run([sys.executable, str(ROOT / 'scripts/art_lint.py'), str(folder), '--check-bible'],
                                   capture_output=True, text=True)
            self.assertEqual(check.returncode, 0, check.stdout)
            self.assertEqual(json.loads(check.stdout)['classes'], ['item_sprite', 'prop_model'])
            again = subprocess.run([sys.executable, str(ROOT / 'scripts/make_art_sample.py'), str(folder)],
                                   capture_output=True, text=True)
            self.assertEqual(again.returncode, 1)
