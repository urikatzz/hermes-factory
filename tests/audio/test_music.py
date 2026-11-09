import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.ffmpeg import find_ffmpeg, loudness, probe
from factory_audio.lint import run_lint

CLI = Path(__file__).resolve().parents[2] / 'scripts/music_process.py'
FF = find_ffmpeg()


def process(repo, src, out, *extra):
    return subprocess.run([sys.executable, str(CLI), str(src), str(out), '--class', 'music',
                           '--bible', str(repo / 'audio/style/audio.json'), *map(str, extra)], capture_output=True, text=True)


@unittest.skipUnless(FF, 'ffmpeg not installed')
class MusicTest(unittest.TestCase):
    def test_loop_trim_loudness_ogg(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'g'
            fx.write_bible(repo)
            src = fx.write_tone(Path(tmp) / 'raw.wav', fx.tone(8.0, freq=437.3, amp=0.1, channels=1, lead=0.5, tail=0.5, fade=0))
            out = repo / 'Assets/Audio/Music/theme.ogg'
            done = process(repo, src, out, '--loop')
            self.assertEqual(done.returncode, 0, done.stderr)
            info = probe(FF, out)
            self.assertEqual((info['codec'], info['channels'], info['sample_rate']), ('vorbis', 2, 44100))
            self.assertLess(info['duration'], 8.0)
            self.assertAlmostEqual(loudness(FF, out)['lufs'], -16, delta=1.0)
            lint = run_lint(repo, Path(tmp) / 'lint', ['Assets/Audio/Music/theme.ogg'], FF)
            self.assertEqual([f['check'] for f in lint['findings']], [])
            self.assertIn('loop_end_s', json.loads(done.stdout))

    def test_bad_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'g'
            fx.write_bible(repo)
            bad = Path(tmp) / 'bad.mp3'
            bad.write_bytes(b'nope')
            self.assertEqual(process(repo, bad, Path(tmp) / 'o.ogg').returncode, 1)
            good = fx.write_tone(Path(tmp) / 'g.wav', fx.tone(5.0, channels=2))
            done = subprocess.run([sys.executable, str(CLI), str(good), str(Path(tmp) / 'o.ogg'), '--class', 'nope',
                                   '--bible', str(repo / 'audio/style/audio.json')], capture_output=True, text=True)
            self.assertEqual(done.returncode, 2)


if __name__ == '__main__':
    unittest.main()
