import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import audio_fixtures  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


class InstallTest(unittest.TestCase):
    def run_install(self, script, skills):
        return subprocess.run(['sh', str(ROOT / 'scripts' / script)], env=dict(os.environ, HERMES_FACTORY_SKILLS=str(skills)),
                              capture_output=True, text=True)

    def test_both_installers(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self.assertEqual(self.run_install('install_audio_review.sh', skills).returncode, 0)
            self.assertEqual(self.run_install('install_audio_production.sh', skills).returncode, 0)
            review, production = skills / 'audio-review', skills / 'audio-production'
            for path in (review / 'scripts/audio_lint.py', review / 'factory_audio/lint.py', review / 'factory_art/findings.py',
                         production / 'scripts/sfx_synth.py', production / 'scripts/music_process.py',
                         production / 'audio_production/synth.py', production / 'factory_audio/wavio.py',
                         production / 'souls/audio-director.SOUL.md', production / 'souls/sound-designer.SOUL.md'):
                self.assertTrue(path.is_file(), path)
            for text in (review / 'SKILL.md', production / 'SKILL.md', production / 'souls/sound-designer.SOUL.md'):
                body = text.read_text()
                self.assertNotIn('${', body, text)
                self.assertIn(str(skills), body, text)
            lint = subprocess.run(['python3', str(review / 'scripts/audio_lint.py'), tmp, '--check-bible'], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 1)
            self.assertIn('invalid', lint.stdout)
            self.assertNotEqual(self.run_install('install_audio_review.sh', skills).returncode, 0)


if __name__ == '__main__':
    unittest.main()
