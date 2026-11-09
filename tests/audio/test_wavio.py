import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.wavio import WavError, read_wav, write_wav


class WavioTest(unittest.TestCase):
    def test_round_trip_stereo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.wav'
            data = fx.tone(0.1, channels=2)
            write_wav(path, data, 22050)
            wav = read_wav(path)
            self.assertEqual((wav.rate, wav.channels, wav.bits), (22050, 2, 16))
            self.assertEqual(len(wav.data[0]), len(data[0]))
            self.assertAlmostEqual(wav.data[1][100], data[1][100], places=3)

    def test_clamps_out_of_range(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'a.wav'
            write_wav(path, [[2.0, -2.0]], 8000)
            self.assertEqual(read_wav(path).data[0], [32767 / 32768, -1.0])

    def test_rejects_garbage_and_24_bit(self):
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / 'bad.wav'
            bad.write_bytes(b'not a wav')
            with self.assertRaises(WavError):
                read_wav(bad)
            import wave
            deep = Path(tmp) / 'deep.wav'
            with wave.open(str(deep), 'wb') as out:
                out.setnchannels(1); out.setsampwidth(3); out.setframerate(8000); out.writeframes(b'\0' * 30)
            with self.assertRaises(WavError) as ctx:
                read_wav(deep)
            self.assertIn('24-bit', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
