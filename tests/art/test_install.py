import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def test_installs_runnable_skill_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / 'skills'
            env = dict(os.environ, HERMES_FACTORY_SKILLS=str(skills))
            command = ['sh', str(ROOT / 'scripts/install_art_review.sh')]
            first = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = skills / 'art-review'
            self.assertTrue((skill / 'SKILL.md').read_text().startswith('---\nname: art-review\n'))
            text = (skill / 'SKILL.md').read_text()
            self.assertIn(f'python3 {skill}/scripts/art_lint.py', text)
            self.assertNotIn('${HERMES_SKILL_DIR}/scripts/art_lint.py', text)
            self.assertTrue((skill / 'SOUL.md').is_file())
            self.assertFalse(list(skill.rglob('__pycache__')))
            self.assertFalse((skill / 'factory_art/install').exists())
            repo = build_testgame(Path(temp) / 'game')
            lint = subprocess.run([sys.executable, str(skill / 'scripts/art_lint.py'), str(repo),
                                   '--out', str(Path(temp) / 'lint'), '--blender', '/nonexistent'],
                                  capture_output=True, text=True)
            self.assertEqual(lint.returncode, 0, lint.stderr)
            self.assertEqual(json.loads(lint.stdout)['unverified'], 1)
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 1)
            self.assertIn('already exists', again.stderr)
