import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.ffmpeg import FFmpegUnavailable, decode_wav, find_ffmpeg, loudness, pictures, probe

FF = find_ffmpeg()


@unittest.skipUnless(FF, 'ffmpeg not installed')
class FFmpegTest(unittest.TestCase):
    def test_probe_decode_loudness_pictures(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = fx.write_tone(Path(tmp) / 'a.wav', fx.tone(2.0, amp=0.5, channels=2))
            ogg = Path(tmp) / 'a.ogg'
            import subprocess
            subprocess.run([FF.ffmpeg, '-v', 'error', '-i', str(src), '-c:a', 'vorbis', '-strict', '-2', str(ogg)], check=True)
            info = probe(FF, ogg)
            self.assertEqual((info['codec'], info['channels'], info['sample_rate']), ('vorbis', 2, 44100))
            self.assertAlmostEqual(info['duration'], 2.0, delta=0.05)
            wav = decode_wav(FF, ogg, Path(tmp) / 'd.wav')
            self.assertEqual(wav.channels, 2)
            loud = loudness(FF, src)
            self.assertAlmostEqual(loud['peak_dbfs'], -6.0, delta=0.3)
            self.assertLess(loud['lufs'], -5)
            images = pictures(FF, src, Path(tmp) / 'pics', 'a')
            self.assertTrue(all(Path(p).stat().st_size > 0 for p in images))

    def test_garbage_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'x.ogg'
            bad.write_bytes(b'nope')
            with self.assertRaises(ValueError):
                probe(FF, bad)


class MissingTest(unittest.TestCase):
    def test_missing_binary(self):
        self.assertIsNone(find_ffmpeg('/nonexistent/ffmpeg'))
        with self.assertRaises(FFmpegUnavailable):
            from factory_audio.ffmpeg import require
            require(None)


if __name__ == '__main__':
    unittest.main()
