import json
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.ffmpeg import find_ffmpeg
from factory_audio.lint import run_lint

FF = find_ffmpeg()


@unittest.skipUnless(FF, 'ffmpeg not installed')
class LintTest(unittest.TestCase):
    def test_testgame_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = fx.build_testgame(Path(tmp) / 'game', FF.ffmpeg)
            result = run_lint(repo, Path(tmp) / 'out', (), FF)
            got = sorted((f['severity'], f['check'], f['file']) for f in result['findings'])
            self.assertEqual(got, fx.TESTGAME_EXPECTED)
            self.assertTrue(result['lint_blocking'])
            data = json.loads((Path(tmp) / 'out/lint.json').read_text())
            theme = next(a for a in data['assets'] if a['file'].endswith('theme.ogg'))
            self.assertEqual(theme['class'], 'music')
            self.assertEqual(len(theme['images']), 2)
            self.assertIn('lufs', theme['measures'])

    def test_missing_bible_blocks_only_with_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / 'empty'
            empty.mkdir()
            self.assertEqual(run_lint(empty, Path(tmp) / 'o1', (), FF)['findings'], [])
            fx.write_tone(empty / 'a.wav', fx.tone(0.1))
            checks = [f['check'] for f in run_lint(empty, Path(tmp) / 'o2', (), FF)['findings']]
            self.assertEqual(checks, ['bible'])

    def test_style_hash_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'g'
            fx.write_bible(repo)
            result = run_lint(repo, Path(tmp) / 'o', (), FF, expect_style_hash='0' * 64)
            self.assertEqual(result['findings'][0]['check'], 'style')

    def test_paths_outside_repo_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'g'
            fx.write_bible(repo)
            with self.assertRaises(ValueError):
                run_lint(repo, Path(tmp) / 'o', ['../x'], FF)


class NoFFmpegTest(unittest.TestCase):
    def test_ogg_unverified_without_ffmpeg(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'g'
            fx.write_bible(repo)
            (repo / 'Assets/Audio/Music').mkdir(parents=True)
            (repo / 'Assets/Audio/SFX').mkdir(parents=True)
            (repo / 'Assets/Audio/Music/a.ogg').write_bytes(b'OggS')
            fx.write_tone(repo / 'Assets/Audio/SFX/a.wav', fx.tone(0.12, freq=1200, amp=0.25))
            result = run_lint(repo, Path(tmp) / 'o', (), None)
            self.assertEqual([u['file'] for u in result['unverified']], ['Assets/Audio/Music/a.ogg'])
            self.assertFalse(result['lint_blocking'])


if __name__ == '__main__':
    unittest.main()
