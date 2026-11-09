import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures  # noqa: F401  (puts the repo root on sys.path)
from audio_production.synth import RecipeError, render
from factory_audio.measure import peak_dbfs
from factory_audio.wavio import read_wav

CLI = Path(__file__).resolve().parents[2] / 'scripts/sfx_synth.py'


class SynthTest(unittest.TestCase):
    def test_every_wave_renders_with_envelope_length(self):
        for wave in ('square', 'saw', 'sine', 'triangle', 'noise'):
            data, rate = render({'wave': wave, 'attack': 0.01, 'sustain': 0.05, 'decay': 0.04})
            self.assertEqual(rate, 44100)
            self.assertEqual(len(data[0]), int(0.1 * 44100), wave)
            self.assertGreater(max(abs(v) for v in data[0]), 0.05, wave)

    def test_deterministic_and_seeded(self):
        a = render({'wave': 'noise', 'seed': 7})[0]
        self.assertEqual(a, render({'wave': 'noise', 'seed': 7})[0])
        self.assertNotEqual(a, render({'wave': 'noise', 'seed': 8})[0])

    def test_peak_clamp(self):
        data, _ = render({'wave': 'square', 'volume': 1.0, 'sustain_punch': 1.0, 'peak_dbfs_max': -3.0})
        self.assertLessEqual(peak_dbfs(data), -2.99)

    def test_slide_rises(self):
        data, rate = render({'wave': 'sine', 'freq_start': 200, 'freq_end': 800, 'attack': 0, 'sustain': 0.4, 'decay': 0, 'volume': 0.5})
        def crossings(chunk):
            return sum(1 for a, b in zip(chunk, chunk[1:]) if a <= 0 < b)
        q = len(data[0]) // 4
        self.assertGreater(crossings(data[0][-q:]), 2 * crossings(data[0][:q]))

    def test_bad_recipes(self):
        for recipe in ({}, {'wave': 'kazoo'}, {'wave': 'sine', 'sustain': -1}, {'wave': 'sine', 'channels': 3},
                       {'wave': 'sine', 'volume': 'loud'}, {'wave': 'sine', 'attack': 0, 'sustain': 0, 'decay': 0},
                       {'wave': 'sine', 'sustain': 60}):
            with self.assertRaises(RecipeError, msg=recipe):
                render(recipe)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            recipe = Path(tmp) / 'jump.json'
            recipe.write_text(json.dumps({'wave': 'square', 'freq_start': 300, 'freq_end': 900, 'channels': 1}))
            out = Path(tmp) / 'jump.wav'
            done = subprocess.run([sys.executable, str(CLI), str(recipe), str(out)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(read_wav(out).channels, 1)
            self.assertEqual(json.loads(done.stdout)['out'], str(out))
            recipe.write_text('{')
            self.assertEqual(subprocess.run([sys.executable, str(CLI), str(recipe), str(out)]).returncode, 2)


if __name__ == '__main__':
    unittest.main()
