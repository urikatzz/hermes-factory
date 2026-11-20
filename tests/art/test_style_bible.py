import json
import tempfile
import unittest
from pathlib import Path

from art_fixtures import PALETTE, gpl, write_bible
from factory_art.style_bible import BibleError, classify, glob_regex, is_art_file, load_bible, parse_rules

SPRITE = {'name': 'chars', 'kind': 'sprite', 'match': ['Assets/Characters/**/*.png'], 'rules': ['S1']}


class RuleTests(unittest.TestCase):
    def test_look_rules_and_annotated_blocking_marks_are_parsed(self):
        rules = parse_rules('L1 (blocking, V1) Dark lab.\nL2 (blocking) Dummies.\nL13 (V13; introduced_at milestone 2) Later.\nS1 Plain.\n')
        self.assertEqual(rules, {'L1': True, 'L2': True, 'L13': False, 'S1': False})

    def test_parses_ids_and_blocking_marker(self):
        rules = parse_rules('# Style\n**S1** Silhouettes.\n## S2 (blocking) Light.\n- T1 Short copy.\nS is prose.\n')
        self.assertEqual(rules, {'S1': False, 'S2': True, 'T1': False})

    def test_duplicate_rule_id_is_invalid(self):
        with self.assertRaisesRegex(BibleError, 'S1 is defined twice'):
            parse_rules('**S1** a\n**S1** b\n')


class GlobTests(unittest.TestCase):
    def test_double_star_spans_directories_and_single_star_does_not(self):
        pattern = glob_regex('Assets/**/*.png')
        self.assertTrue(pattern.fullmatch('Assets/a.png'))
        self.assertTrue(pattern.fullmatch('Assets/x/y/a.png'))
        self.assertFalse(pattern.fullmatch('Other/a.png'))
        self.assertFalse(glob_regex('Assets/*.png').fullmatch('Assets/x/a.png'))
        self.assertTrue(glob_regex('Assets/Props/**').fullmatch('Assets/Props/a/b.glb'))


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def assertInvalid(self, message, classes, **kwargs):
        write_bible(self.root, classes, **kwargs)
        with self.assertRaisesRegex(BibleError, message):
            load_bible(self.root)

    def test_loads_valid_bible_with_palette(self):
        sprite = dict(SPRITE, palette={'file': 'palette.gpl', 'tolerance': 4}, references=['ref/hero.png'])
        write_bible(self.root, [sprite], files={'palette.gpl': gpl(PALETTE), 'ref/hero.png': b'x'})
        bible = load_bible(self.root)
        self.assertEqual(bible['rules'], {'S1': True, 'S2': False, 'T1': False})
        self.assertEqual(bible['classes'][0]['_palette'], PALETTE)

    def test_missing_files(self):
        with self.assertRaisesRegex(BibleError, 'art/style/style.json not found'):
            load_bible(self.root)
        write_bible(self.root, [SPRITE])
        (self.root / 'art/style/STYLE.md').unlink()
        with self.assertRaisesRegex(BibleError, 'art/style/STYLE.md not found'):
            load_bible(self.root)

    def test_invalid_json(self):
        write_bible(self.root, [SPRITE])
        (self.root / 'art/style/style.json').write_text('{')
        with self.assertRaisesRegex(BibleError, 'not valid JSON'):
            load_bible(self.root)

    def test_non_utf8_bible_files(self):
        for name in ('style.json', 'STYLE.md'):
            with self.subTest(name=name):
                write_bible(self.root, [SPRITE])
                (self.root / 'art/style' / name).write_bytes(b'\xff\xfe')
                with self.assertRaisesRegex(BibleError, 'not valid UTF-8'):
                    load_bible(self.root)

    def test_wrong_version(self):
        write_bible(self.root, [SPRITE])
        (self.root / 'art/style/style.json').write_text(json.dumps({'version': 2, 'classes': [SPRITE]}))
        with self.assertRaisesRegex(BibleError, 'version must be 1'):
            load_bible(self.root)

    def test_invalid_classes(self):
        cases = {
            'kind must be one of': [dict(SPRITE, kind='audio')],
            'unknown fields': [dict(SPRITE, triangles_max=5)],
            'STYLE.md does not define': [dict(SPRITE, rules=['S9'])],
            'does not exist under art/style': [dict(SPRITE, references=['../outside.png'])],
            'is duplicated': [SPRITE, SPRITE],
            'match must be': [dict(SPRITE, match=[])],
            r'size\.width must be \[min, max\]': [dict(SPRITE, size={'width': [64, 32]})],
            'severity.size must be one of': [dict(SPRITE, severity={'size': 'FATAL'})],
            'severity has unknown check': [dict(SPRITE, severity={'triangles': 'LOW'})],
            'origin must be': [{'name': 'm', 'kind': 'model', 'match': ['*.glb'], 'origin': 'top'}],
            'forbidden must be': [{'name': 't', 'kind': 'text', 'match': ['*.json'], 'forbidden': ['']}],
            'palette has no colours': [dict(SPRITE, palette={'file': 'palette.gpl'})],
            'tolerance must be a non-negative integer': [dict(SPRITE, palette={'file': 'palette.gpl', 'tolerance': False})],
            r'palette\.tolerance must be a non-negative integer': [dict(SPRITE, palette={'file': 'palette.gpl', 'tolerance': 1.5})],
        }
        for message, classes in cases.items():
            with self.subTest(message=message):
                self.assertInvalid(message, classes, files={'palette.gpl': 'GIMP Palette\n'})


class ClassifyTests(unittest.TestCase):
    def test_first_class_wins_and_overlaps_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            text = {'name': 'copy', 'kind': 'text', 'match': ['Assets/Text/*.json']}
            broad = {'name': 'all', 'kind': 'sprite', 'match': ['Assets/**/*.png']}
            write_bible(temp, [SPRITE, broad, text])
            bible = load_bible(temp)
            cls, overlaps = classify(bible, 'Assets/Characters/hero.png')
            self.assertEqual((cls['name'], overlaps), ('chars', ['all']))
            self.assertEqual(classify(bible, 'Docs/a.png'), (None, []))
            self.assertTrue(is_art_file(bible, 'Docs/a.png'))
            self.assertTrue(is_art_file(bible, 'Assets/Text/menu.json'))
            self.assertFalse(is_art_file(bible, 'Assets/Characters/hero.png.meta'))
            self.assertFalse(is_art_file(bible, 'Docs/notes.json'))
