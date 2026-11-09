import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.ffmpeg import find_ffmpeg

CLI = Path(__file__).resolve().parents[2] / 'scripts/audio_lint.py'
FF = find_ffmpeg()


def run(*args):
    return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)


@unittest.skipUnless(FF, 'ffmpeg not installed')
class CliTest(unittest.TestCase):
    def test_gate_and_bible_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = fx.build_testgame(Path(tmp) / 'g', FF.ffmpeg)
            self.assertEqual(run(repo, '--out', Path(tmp) / 'o').returncode, 0)
            self.assertEqual(run(repo, '--out', Path(tmp) / 'o2', '--fail-on-blocking').returncode, 1)
            good = run(repo, 'Assets/Audio/SFX/click.wav', '--out', Path(tmp) / 'o3', '--fail-on-blocking')
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertEqual(json.loads(run(repo, '--check-bible').stdout)['bible'], 'ok')
            self.assertEqual(len(json.loads(run(repo, '--style-hash').stdout)['style_sha256']), 64)
            empty = Path(tmp) / 'e'
            empty.mkdir()
            self.assertEqual(run(empty, '--check-bible').returncode, 1)


if __name__ == '__main__':
    unittest.main()
