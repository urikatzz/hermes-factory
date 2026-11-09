"""Regression tests for review findings on Part A."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.bible import BibleError, load_bible, style_hash
from factory_audio.ffmpeg import find_ffmpeg
from factory_audio.lint import run_lint

ROOT = Path(__file__).resolve().parents[2]
FF = find_ffmpeg()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()


class BibleTypes(Base):  # 1
    def test_malformed_types_are_bible_errors(self):
        for change in (dict(sample_rate=[1]), dict(kind=[]), dict(format={}), dict(rules=5), dict(rules=[5]),
                       dict(match=[1]), dict(channels=[2]), dict(loop=[]), dict(name=['x'])):
            cls = copy.deepcopy(fx.SFX_CLASS)
            cls.update(change)
            fx.write_bible(self.root, [cls])
            with self.assertRaises(BibleError, msg=change):
                load_bible(self.root)

    def test_lint_writes_blocker_for_malformed(self):
        cls = dict(copy.deepcopy(fx.SFX_CLASS), sample_rate=[1])
        fx.write_bible(self.root / 'g', [cls])
        fx.write_tone(self.root / 'g/a.wav', fx.tone(0.1))
        result = run_lint(self.root / 'g', self.root / 'o', (), None)
        self.assertEqual([f['check'] for f in result['findings']], ['bible'])
        self.assertTrue((self.root / 'o/lint.json').is_file())


class NonFinite(Base):  # 2
    def test_silent_wav_lint_json_is_strict(self):
        fx.write_bible(self.root / 'g')
        (self.root / 'g/Assets/Audio/SFX').mkdir(parents=True)
        fx.write_tone(self.root / 'g/Assets/Audio/SFX/s.wav', [[0.0] * 4410])
        run_lint(self.root / 'g', self.root / 'o', (), FF)
        text = (self.root / 'o/lint.json').read_text()
        self.assertNotIn('Infinity', text)
        data = json.loads(text, parse_constant=lambda c: self.fail(c))
        self.assertIsNone(data['assets'][0]['measures']['peak_dbfs'])


class Symlinks(Base):  # 3
    def test_symlink_in_style_rejected_and_hashed(self):
        style = fx.write_bible(self.root)
        other = self.root / 'other.md'
        other.write_text('x')
        first = style_hash(self.root)
        os.symlink(other, style / 'extra.md')
        self.assertNotEqual(first, style_hash(self.root))
        with self.assertRaisesRegex(BibleError, 'symlink'):
            load_bible(self.root)


@unittest.skipUnless(FF, 'ffmpeg not installed')
class MusicCli(Base):  # 4, 5, 8
    def run_cli(self, src, *extra, classes=None):
        repo = self.root / 'g'
        fx.write_bible(repo, classes or (fx.SFX_CLASS, fx.MUSIC_CLASS))
        return subprocess.run([sys.executable, str(ROOT / 'scripts/music_process.py'), str(src), str(self.root / 'o.ogg'),
                               '--class', 'music', '--bible', str(repo / 'audio/style/audio.json'), *extra],
                              capture_output=True, text=True)

    def test_invalid_bible_exit_2(self):
        src = fx.write_tone(self.root / 's.wav', fx.tone(5.0, channels=2))
        music = {k: v for k, v in fx.MUSIC_CLASS.items() if k != 'loudness_lufs'}
        self.assertEqual(self.run_cli(src, classes=[music]).returncode, 2)

    def test_tiny_loop_end_exit_1(self):
        src = fx.write_tone(self.root / 's.wav', fx.tone(5.0, channels=2))
        done = self.run_cli(src, '--loop', '--loop-end', '0.001')
        self.assertEqual(done.returncode, 1, done.stderr)
        self.assertIn('loop too short', done.stderr)

    def test_too_long_exit_1(self):
        src = self.root / 'long.ogg'
        subprocess.run([FF.ffmpeg, '-v', 'error', '-f', 'lavfi', '-i', 'anullsrc=r=8000:cl=stereo', '-t', '601',
                        '-c:a', 'vorbis', '-strict', '-2', str(src)], check=True)
        done = self.run_cli(src)
        self.assertEqual(done.returncode, 1)
        self.assertIn('600', done.stderr)


class LoopUnit(unittest.TestCase):  # 5
    def test_make_loop_short(self):
        from audio_production.music import find_loop_end, make_loop
        data = fx.tone(1.0)
        with self.assertRaisesRegex(ValueError, 'loop too short'):
            make_loop(data, 44100, 10)
        with self.assertRaisesRegex(ValueError, 'loop too short'):
            find_loop_end(data, 44100, loop_end=0.0001)


class SynthBounds(Base):  # 6
    def test_non_finite_and_bounds(self):
        from audio_production.synth import RecipeError, render
        for recipe in ({'wave': 'sine', 'volume': float('nan')}, {'wave': 'sine', 'freq_start': float('inf')},
                       {'wave': 'sine', 'arp_semitones': 49}, {'wave': 'sine', 'arp_semitones': -49},
                       {'wave': 'sine', 'vibrato_depth': 25}, {'wave': 'sine', 'vibrato_hz': 51},
                       {'wave': 'sine', 'vibrato_hz': -1}):
            with self.assertRaises(RecipeError, msg=recipe):
                render(recipe)

    def test_cli_value_error_exit_2(self):
        recipe = self.root / 'r.json'
        recipe.write_text('{"wave": "sine", "volume": NaN}')
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sfx_synth.py'), str(recipe), str(self.root / 'o.wav')],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 2, done.stderr)


class Timeouts(unittest.TestCase):  # 7
    def test_music_uses_run_with_timeout(self):
        import inspect
        import audio_production.music as music
        from factory_audio import ffmpeg
        self.assertNotIn('subprocess.run', inspect.getsource(music))
        self.assertIn('timeout', inspect.signature(ffmpeg._run).parameters)


class LongLint(Base):  # 8
    def test_long_wav_duration_without_decoding(self):
        fx.write_bible(self.root / 'g')
        sfx = self.root / 'g/Assets/Audio/SFX'
        sfx.mkdir(parents=True)
        import wave
        with wave.open(str(sfx / 'huge.wav'), 'wb') as out:
            out.setnchannels(1); out.setsampwidth(2); out.setframerate(8000)
            out.writeframes(b'\0\0' * (8000 * 601))
        import factory_audio.lint as lint
        original = lint.read_wav
        lint.read_wav = lambda *a, **k: self.fail('decoded a too-long file')
        try:
            result = run_lint(self.root / 'g', self.root / 'o', (), None)
        finally:
            lint.read_wav = original
        self.assertIn(('HIGH', 'duration'), [(f['severity'], f['check']) for f in result['findings']])


class SilenceLimit(Base):  # 9
    def lint_late(self, **change):
        cls = dict(copy.deepcopy(fx.SFX_CLASS), **change)
        if change.get('silence_max_ms') == 'absent':
            del cls['silence_max_ms']
        fx.write_bible(self.root / 'g', [cls])
        (self.root / 'g/Assets/Audio/SFX').mkdir(parents=True, exist_ok=True)
        fx.write_tone(self.root / 'g/Assets/Audio/SFX/a.wav', fx.tone(0.2, amp=0.2, lead=0.01))
        return [f['check'] for f in run_lint(self.root / 'g', self.root / 'o', (), None)['findings']]

    def test_zero_means_none_allowed(self):
        self.assertIn('silence', self.lint_late(silence_max_ms=0))

    def test_absent_means_off(self):
        self.assertNotIn('silence', self.lint_late(silence_max_ms='absent'))


class StaleCueOutside(Base):  # 10
    def test_target_outside_repo(self):
        fx.write_bible(self.root / 'g')
        (self.root / 'secret.ogg').write_bytes(b'x')
        cues = self.root / 'g/audio/cues'
        cues.mkdir(parents=True)
        (cues / 'x.md').write_text('target: ../secret.ogg\n')
        found = run_lint(self.root / 'g', self.root / 'o', (), None)['findings']
        self.assertEqual([(f['severity'], f['check']) for f in found], [('LOW', 'stale_cue')])
        self.assertIn('outside', found[0]['problem'])


if __name__ == '__main__':
    unittest.main()
