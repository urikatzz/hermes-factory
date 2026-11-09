import unittest

import audio_fixtures as fx
from factory_audio.measure import clip_runs, dc_offset, edge_silence_ms, loop_seam, peak_dbfs


class MeasureTest(unittest.TestCase):
    def test_peak(self):
        self.assertAlmostEqual(peak_dbfs(fx.tone(0.1, amp=0.5)), -6.02, places=1)
        self.assertEqual(peak_dbfs([[0.0, 0.0]]), float('-inf'))

    def test_clip_runs(self):
        self.assertEqual(clip_runs([[0.0, 1.0, 1.0, 1.0, 0.2, -1.0, -1.0]]), 1)
        self.assertEqual(clip_runs(fx.tone(0.1, amp=0.5)), 0)

    def test_dc_offset(self):
        self.assertLess(abs(dc_offset(fx.tone(0.5))), 0.001)
        self.assertAlmostEqual(dc_offset([[0.1] * 100]), 0.1)

    def test_edge_silence(self):
        lead, tail = edge_silence_ms(fx.tone(0.2, lead=0.1, tail=0.05), 44100)
        self.assertAlmostEqual(lead, 100, delta=2)
        self.assertAlmostEqual(tail, 50, delta=2)

    def test_loop_seam(self):
        good = loop_seam(fx.loop_tone(1.0), 44100)
        bad = loop_seam(fx.tone(1.0, freq=437.3, fade=0), 44100)
        self.assertLess(good['jump'], 0.05)
        self.assertGreater(bad['jump'], 0.1)
        self.assertLess(good['rms_ratio_db'], 1.0)


if __name__ == '__main__':
    unittest.main()
