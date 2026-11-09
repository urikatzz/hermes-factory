import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures  # noqa: F401
from factory_audio.bible import load_bible

ROOT = Path(__file__).resolve().parents[2]


class SampleTest(unittest.TestCase):
    def test_sample_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'audio-sample'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts/make_audio_sample.py'), str(out)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            bible = load_bible(out)
            self.assertEqual({c['name'] for c in bible['classes']}, {'ui_sfx', 'game_sfx', 'music'})
            self.assertTrue((out / '.git').is_dir())
            self.assertEqual(subprocess.run(['git', '-C', str(out), 'status', '--porcelain'], capture_output=True, text=True).stdout, '')
            self.assertEqual(json.loads(done.stdout)['repo'], str(out))


if __name__ == '__main__':
    unittest.main()
