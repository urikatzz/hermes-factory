import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def test_the_skill_installs_runs_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / 'skills'
            env = dict(os.environ, HERMES_FACTORY_SKILLS=str(skills))
            command = ['sh', str(ROOT / 'scripts/install_unity_scene.sh')]
            first = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = skills / 'unity-scene'
            text = (skill / 'SKILL.md').read_text()
            self.assertTrue(text.startswith('---\nname: unity-scene\n'))
            self.assertIn(f'python3 {skill}/scripts/unity_scene_capture.py', text)               # the command is expanded to the installed path
            self.assertNotIn('${HERMES_SKILL_DIR}/scripts/unity_scene_capture.py', text)
            self.assertTrue((skill / 'factory_unity/editor/FactorySceneBuilder.cs').is_file())     # the engine script ships with the package
            self.assertFalse((skill / 'factory_unity/install').exists())
            self.assertFalse(list(skill.rglob('__pycache__')))
            helped = subprocess.run([sys.executable, str(skill / 'scripts/unity_scene_capture.py'), '--help'], capture_output=True, text=True)
            self.assertEqual(helped.returncode, 0, helped.stderr); self.assertIn('--layout', helped.stdout)
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 1); self.assertIn('already exists', again.stderr)

    def test_the_skill_text_states_the_rules_that_keep_a_preliminary_scene_from_passing(self):
        text = (ROOT / 'factory_unity/install/SKILL.md').read_text()
        for fragment in ('real engine render of the whole scene', 'never on an image anybody painted or generated', 'covers', 'missing', 'preliminary composition test, never accepted',
                         'verifies every claim the engine makes', 'never modified'):
            self.assertIn(fragment, text)


if __name__ == '__main__':
    unittest.main()
