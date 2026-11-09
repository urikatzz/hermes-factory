import copy
import json
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.bible import BibleError, classify, is_audio_file, load_bible, style_hash


class BibleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_loads_rules_and_classes(self):
        fx.write_bible(self.root)
        bible = load_bible(self.root)
        self.assertEqual(sorted(bible['rules']), ['A1', 'A2'])
        self.assertTrue(bible['rules']['A1']['blocking'])
        self.assertFalse(bible['rules']['A2']['blocking'])
        self.assertEqual(classify(bible, 'Assets/Audio/SFX/ui/click.wav')[0]['name'], 'ui_sfx')
        self.assertIsNone(classify(bible, 'Assets/Other/x.wav')[0])
        self.assertTrue(is_audio_file('a/b.OGG'))
        self.assertFalse(is_audio_file('a/b.png'))

    def test_missing_bible(self):
        with self.assertRaisesRegex(BibleError, 'audio/style/audio.json'):
            load_bible(self.root)

    def bad(self, change, message):
        cls = copy.deepcopy(fx.MUSIC_CLASS)
        change(cls)
        fx.write_bible(self.root, [cls])
        with self.assertRaisesRegex(BibleError, message):
            load_bible(self.root)

    def test_rejects_bad_classes(self):
        self.bad(lambda c: c.update(channels=1), 'ogg.*2 channels')
        self.bad(lambda c: c.update(format='mp3'), 'format')
        self.bad(lambda c: c.update(kind='voice'), 'kind')
        self.bad(lambda c: c.update(duration_s=[5, 1]), 'duration_s')
        self.bad(lambda c: c.update(peak_dbfs_max=True), 'peak_dbfs_max')
        self.bad(lambda c: c.update(loudness_lufs={'target': -16}), 'loudness_lufs')
        self.bad(lambda c: c.update(rules=['Z9']), 'Z9')
        self.bad(lambda c: c.update(sample_rate=12345), 'sample_rate')

    def test_rejects_bad_utf8_and_json(self):
        style = fx.write_bible(self.root)
        (style / 'AUDIO.md').write_bytes(b'\xff\xfe')
        with self.assertRaisesRegex(BibleError, 'UTF-8'):
            load_bible(self.root)
        fx.write_bible(self.root)
        (style / 'audio.json').write_text('{')
        with self.assertRaisesRegex(BibleError, 'JSON'):
            load_bible(self.root)

    def test_style_hash_changes_with_content(self):
        fx.write_bible(self.root)
        first = style_hash(self.root)
        (self.root / 'audio/style/AUDIO.md').write_text(fx.RULES_MD + '\n**A3** New.\n')
        self.assertNotEqual(first, style_hash(self.root))
        self.assertEqual(len(first), 64)


if __name__ == '__main__':
    unittest.main()
