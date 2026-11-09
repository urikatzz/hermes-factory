# Art Verifier Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a level-1 art verifier: a deterministic linter for sprites, 3D models and game text against a repo's `art/style/` bible, a standalone `art_check.sh`, and the `art-review` skill plus `art-reviewer` profile that add a rule-bound vision pass.

**Architecture:** A standard-library Python package `factory_art/` holds the measurable checks (PNG decoding, style bible validation, sprite/model/text checks, view rendering). 3D models are measured and rendered by headless Blender through a script run inside Blender's own Python. `scripts/art_lint.py` writes `lint.json` plus review images; the Hermes `art-reviewer` profile reads those and adds vision findings that must cite a STYLE.md rule.

**Tech Stack:** Python 3.11+ standard library, unittest, Blender 4.1 (`/Applications/Blender.app`) for models, POSIX sh + openrsync for the standalone wrapper, Hermes CLI (`hermes -p <profile> chat`).

**Spec:** `docs/superpowers/specs/2026-10-21-art-verifier-design.md`

**Git:** The user commits manually. Do not run `git add`/`git commit`; each task ends with a test run instead.

**Running tests:** from the repo root, `python3 -m unittest discover -s tests/art -p 'test_*.py' -v`. A single file: `python3 -m unittest discover -s tests/art -p 'test_png.py' -v`. Test helpers in `tests/art/` are imported by bare name (`from art_fixtures import ...`), as `tests/ecc` does.

---

## File structure

```
factory_art/
  __init__.py            package docstring only
  findings.py            finding records, severity order, overrides, F-lines
  png.py                 stdlib PNG reader/writer, Image dataclass
  style_bible.py         load/validate art/style, rule IDs, glob matching, classify
  sprite_checks.py       size, alpha, pixel-art edges/scale, palette
  views.py               upscale, composite, tile; sprite views; contact sheet
  text_checks.py         JSON string walk, max_chars, forbidden
  model_checks.py        compare Blender stats with class limits
  blender_runner.py      find Blender, run render script with timeout
  blender/render_model.py   runs inside Blender: import, stats.json, 4 renders
  lint.py                collect files, run checks, image budget, lint.json
  install/SKILL.md       art-review skill text (installed)
  install/SOUL.md        art-reviewer profile soul (installed)
scripts/
  art_lint.py            CLI around factory_art.lint
  art_check.sh           standalone review through the art-reviewer profile
  install_art_review.sh  copy skill + package into ~/.hermes/factory-skills/worker/art-review
tests/art/
  art_fixtures.py        sprite(), write_bible(), write_glb(), build_testgame()
  png_fixtures.py        raw PNG builder with forward filters
  test_findings.py  test_png.py  test_style_bible.py  test_sprite_checks.py
  test_views.py  test_text_checks.py  test_model_checks.py  test_blender.py
  test_lint.py  test_art_check.py  test_install.py
docs/art-verifier.md            operator instructions
docs/art-verifier-results.md    validation results
```

---

### Task 1: Package skeleton and findings

**Files:**
- Create: `factory_art/__init__.py`, `factory_art/findings.py`
- Test: `tests/art/test_findings.py`

- [ ] **Step 1: Write the failing test**

`tests/art/test_findings.py`:

```python
import unittest

from factory_art.findings import finding, lines, ordered, override


class FindingTests(unittest.TestCase):
    def test_rejects_unknown_severity(self):
        with self.assertRaises(ValueError):
            finding('CRITICAL', 'size', 'a.png', 'x')

    def test_orders_by_severity_then_file_then_check(self):
        found = [finding('LOW', 'unsupported', 'b.jpg', 'x'), finding('HIGH', 'size', 'b.png', 'x'),
                 finding('HIGH', 'alpha', 'a.png', 'x'), finding('BLOCKER', 'unreadable', 'c.png', 'x')]
        self.assertEqual([(f['severity'], f['file']) for f in ordered(found)],
                         [('BLOCKER', 'c.png'), ('HIGH', 'a.png'), ('HIGH', 'b.png'), ('LOW', 'b.jpg')])

    def test_override_changes_only_named_checks(self):
        found = override([finding('HIGH', 'size', 'a.png', 'x'), finding('MEDIUM', 'palette', 'a.png', 'y')],
                         {'size': 'LOW'})
        self.assertEqual([f['severity'] for f in found], ['LOW', 'MEDIUM'])

    def test_lines_number_findings_and_escape_pipes(self):
        self.assertEqual(lines([finding('HIGH', 'size', 'a.png', '64|32')]), ['F1|HIGH|size|a.png|64/32'])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/art -p 'test_findings.py' -v`
Expected: ERROR `ModuleNotFoundError: No module named 'factory_art'`

- [ ] **Step 3: Implement**

`factory_art/__init__.py`:

```python
"""Level-1 art verification: lint game assets against a repo's art/style bible."""
```

`factory_art/findings.py`:

```python
"""Finding records shared by every art check."""

SEVERITIES = ('BLOCKER', 'HIGH', 'MEDIUM', 'LOW', 'NIT')
BLOCKING = ('BLOCKER', 'HIGH')


def finding(severity, check, file, problem):
    if severity not in SEVERITIES:
        raise ValueError(f'Unknown severity {severity!r}')
    return {'severity': severity, 'check': check, 'file': file, 'problem': problem}


def override(found, levels):
    return [dict(item, severity=levels.get(item['check'], item['severity'])) for item in found]


def ordered(found):
    return sorted(found, key=lambda item: (SEVERITIES.index(item['severity']), item['file'], item['check']))


def lines(found):
    return [f"F{number}|{item['severity']}|{item['check']}|{item['file']}|{item['problem'].replace('|', '/')}"
            for number, item in enumerate(found, 1)]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `python3 -m unittest discover -s tests/art -p 'test_findings.py' -v`
Expected: 4 tests OK

---

### Task 2: Standard-library PNG reader/writer

**Files:**
- Create: `factory_art/png.py`
- Test: `tests/art/png_fixtures.py`, `tests/art/test_png.py`

- [ ] **Step 1: Write the fixture builder and failing tests**

`tests/art/png_fixtures.py` (independent forward-filter encoder, so decoding is not tested against itself):

```python
"""Build raw PNG bytes with chosen colour type, bit depth and per-row filters."""
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _filter(row, previous, bpp, kind):
    out = bytearray([kind])
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        upleft = previous[i - bpp] if i >= bpp else 0
        up = previous[i]
        predictor = [0, left, up, (left + up) // 2, _paeth(left, up, upleft)][kind]
        out.append((value - predictor) & 255)
    return out


def raw_png(width, height, ctype, depth, rows, filters=None, palette=None, trns=None, interlace=0):
    """rows: unfiltered scanline bytes, one per image row."""
    bpp = max(1, CHANNELS[ctype] * depth // 8)
    data = bytearray()
    previous = bytes(len(rows[0]))
    for index, row in enumerate(rows):
        data += _filter(bytes(row), previous, bpp, (filters or [0] * height)[index])
        previous = bytes(row)
    chunks = [_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, ctype, 0, 0, interlace))]
    if palette:
        chunks.append(_chunk(b'PLTE', bytes(c for rgb in palette for c in rgb)))
    if trns is not None:
        chunks.append(_chunk(b'tRNS', trns))
    chunks += [_chunk(b'IDAT', zlib.compress(bytes(data))), _chunk(b'IEND', b'')]
    return SIGNATURE + b''.join(chunks)
```

`tests/art/test_png.py`:

```python
import struct
import tempfile
import unittest
from pathlib import Path

from factory_art.png import Image, PngError, decode_png, encode_png, read_png, write_png
from png_fixtures import raw_png

RGB_ROWS = [bytes([10, 20, 30, 200, 100, 50, 0, 255, 128]),
            bytes([12, 22, 32, 190, 110, 40, 5, 250, 120]),
            bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])]
RGB_PIXELS = [tuple(row[i:i + 3]) + (255,) for row in RGB_ROWS for i in range(0, 9, 3)]


class PngTests(unittest.TestCase):
    def test_round_trip_rgba(self):
        image = Image(2, 2, [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 0), (255, 255, 255, 255)])
        self.assertEqual(decode_png(encode_png(image)), image)

    def test_every_filter_type_decodes(self):
        for kind in range(5):
            with self.subTest(filter=kind):
                data = raw_png(3, 3, 2, 8, RGB_ROWS, filters=[kind, kind, kind])
                self.assertEqual(decode_png(data).pixels, RGB_PIXELS)

    def test_mixed_filters_decode(self):
        data = raw_png(3, 3, 2, 8, RGB_ROWS, filters=[4, 2, 3])
        self.assertEqual(decode_png(data).pixels, RGB_PIXELS)

    def test_indexed_8bit_with_transparency(self):
        palette = [(0, 0, 0), (200, 10, 10)]
        data = raw_png(2, 1, 3, 8, [bytes([0, 1])], palette=palette, trns=bytes([0]))
        self.assertEqual(decode_png(data).pixels, [(0, 0, 0, 0), (200, 10, 10, 255)])

    def test_indexed_4bit_ignores_row_padding(self):
        palette = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
        data = raw_png(3, 1, 3, 4, [bytes([0x01, 0x20])], palette=palette)
        self.assertEqual(decode_png(data).pixels, [(1, 1, 1, 255), (2, 2, 2, 255), (3, 3, 3, 255)])

    def test_grey_and_grey_alpha(self):
        self.assertEqual(decode_png(raw_png(1, 1, 0, 8, [bytes([7])])).pixels, [(7, 7, 7, 255)])
        self.assertEqual(decode_png(raw_png(1, 1, 4, 8, [bytes([7, 9])])).pixels, [(7, 7, 7, 9)])

    def test_rgb_transparency_key(self):
        data = raw_png(2, 1, 2, 8, [bytes([1, 2, 3, 4, 5, 6])], trns=struct.pack('>HHH', 1, 2, 3))
        self.assertEqual(decode_png(data).pixels, [(1, 2, 3, 0), (4, 5, 6, 255)])

    def test_rejects_unsupported_and_corrupt_files(self):
        cases = {
            '16-bit': raw_png(1, 1, 2, 16, [bytes(6)]),
            'interlaced': raw_png(1, 1, 2, 8, [bytes(3)], interlace=1),
            'not png': b'GIF89a',
            'bad crc': raw_png(1, 1, 2, 8, [bytes(3)])[:-1] + b'\x00',
        }
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(PngError):
                decode_png(data)

    def test_read_and_write_files(self):
        image = Image(1, 1, [(9, 8, 7, 6)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'a.png'
            write_png(path, image)
            self.assertEqual(read_png(path), image)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_png.py' -v`
Expected: ERROR `No module named 'factory_art.png'`

- [ ] **Step 3: Implement `factory_art/png.py`**

```python
"""Minimal standard-library PNG codec: 8-bit grey/RGB/RGBA, 1-8 bit indexed, non-interlaced."""
from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PngError(ValueError):
    pass


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    pixels: list  # row-major (r, g, b, a) tuples


def read_png(path):
    return decode_png(Path(path).read_bytes())


def write_png(path, image):
    Path(path).write_bytes(encode_png(image))


def decode_png(data):
    if not data.startswith(SIGNATURE):
        raise PngError('not a PNG file')
    header, palette, trns, idat = None, [], b'', []
    position = len(SIGNATURE)
    while position + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        crc = data[position + 8 + length:position + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise PngError('truncated chunk')
        if zlib.crc32(kind + body) != struct.unpack('>I', crc)[0]:
            raise PngError(f'bad CRC in {kind.decode("latin-1")} chunk')
        position += 12 + length
        if kind == b'IHDR':
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
    if header is None:
        raise PngError('missing IHDR chunk')
    width, height, depth, ctype, _, _, interlace = header
    if interlace:
        raise PngError('interlaced PNG is not supported')
    if ctype not in CHANNELS:
        raise PngError(f'unknown colour type {ctype}')
    if depth != 8 and not (ctype == 3 and depth in (1, 2, 4)):
        raise PngError(f'bit depth {depth} with colour type {ctype} is not supported')
    if ctype == 3 and not palette:
        raise PngError('indexed PNG without a palette')
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error as error:
        raise PngError(f'corrupt image data: {error}') from error
    bits = CHANNELS[ctype] * depth
    stride = (width * bits + 7) // 8
    if len(raw) != height * (stride + 1):
        raise PngError('image data size does not match the header')
    pixels = []
    for row in _unfilter(raw, stride, height, max(1, bits // 8)):
        pixels.extend(_row_pixels(row, width, depth, ctype, palette, trns))
    return Image(width, height, pixels)


def encode_png(image):
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)
        for pixel in image.pixels[y * image.width:(y + 1) * image.width]:
            raw.extend(pixel)
    header = struct.pack('>IIBBBBB', image.width, image.height, 8, 6, 0, 0, 0)
    return SIGNATURE + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(bytes(raw))) + _chunk(b'IEND', b'')


def _chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _unfilter(raw, stride, height, bpp):
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind > 4:
            raise PngError(f'bad filter type {kind}')
        if kind:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = previous[i]
                if kind == 1:
                    row[i] = (row[i] + left) & 255
                elif kind == 2:
                    row[i] = (row[i] + up) & 255
                elif kind == 3:
                    row[i] = (row[i] + (left + up) // 2) & 255
                else:
                    row[i] = (row[i] + _paeth(left, up, previous[i - bpp] if i >= bpp else 0)) & 255
        rows.append(row)
        previous = row
    return rows


def _row_pixels(row, width, depth, ctype, palette, trns):
    if ctype == 3:
        if depth == 8:
            indices = row[:width]
        else:
            mask = (1 << depth) - 1
            indices = [(byte >> shift) & mask for byte in row for shift in range(8 - depth, -1, -depth)][:width]
        pixels = []
        for index in indices:
            if index >= len(palette):
                raise PngError('palette index out of range')
            pixels.append(palette[index] + (trns[index] if index < len(trns) else 255,))
        return pixels
    channels = CHANNELS[ctype]
    groups = [tuple(row[i:i + channels]) for i in range(0, width * channels, channels)]
    if ctype == 6:
        return groups
    if ctype == 4:
        return [(v, v, v, a) for v, a in groups]
    if ctype == 2:
        key = struct.unpack('>HHH', trns) if len(trns) == 6 else None
        return [group + (0 if group == key else 255,) for group in groups]
    key = struct.unpack('>H', trns)[0] if len(trns) == 2 else None
    return [(v, v, v, 0 if v == key else 255) for (v,) in groups]
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_png.py' -v`
Expected: 9 tests OK

---

### Task 3: Style bible loading, validation and matching

**Files:**
- Create: `factory_art/style_bible.py`
- Create: `tests/art/art_fixtures.py`
- Test: `tests/art/test_style_bible.py`

- [ ] **Step 1: Write fixture helpers**

`tests/art/art_fixtures.py`:

```python
"""Build style bibles, sprites, models and a sample game repo for art tests."""
import json
from pathlib import Path

PALETTE = [(20, 20, 30), (200, 60, 60), (240, 220, 180), (60, 120, 200)]
RULES_MD = """# Test game style

**S1** (blocking) Characters read clearly at 1x zoom.
**S2** Light comes from the top left.
**T1** UI copy is short and calm.
"""


def write_bible(root, classes, rules_md=RULES_MD, files=None):
    style = Path(root) / 'art' / 'style'
    style.mkdir(parents=True, exist_ok=True)
    (style / 'STYLE.md').write_text(rules_md)
    (style / 'style.json').write_text(json.dumps({'version': 1, 'classes': classes}))
    for name, content in (files or {}).items():
        path = style / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
    return style


def gpl(colours):
    return 'GIMP Palette\nName: test\nColumns: 4\n#\n' + ''.join(f'{r} {g} {b}\tc{i}\n' for i, (r, g, b) in enumerate(colours))
```

- [ ] **Step 2: Write the failing tests**

`tests/art/test_style_bible.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path

from art_fixtures import PALETTE, gpl, write_bible
from factory_art.style_bible import BibleError, classify, glob_regex, is_art_file, load_bible, parse_rules

SPRITE = {'name': 'chars', 'kind': 'sprite', 'match': ['Assets/Characters/**/*.png'], 'rules': ['S1']}


class RuleTests(unittest.TestCase):
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
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_style_bible.py' -v`
Expected: ERROR `No module named 'factory_art.style_bible'`

- [ ] **Step 4: Implement `factory_art/style_bible.py`**

```python
"""Load and validate a repo's art/style bible, and match files to its asset classes."""
import json
from pathlib import Path
import re

from .findings import SEVERITIES

STYLE_DIR = 'art/style'
ART_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.psd', '.glb', '.gltf', '.fbx', '.obj', '.blend'}
COMMON_KEYS = {'name', 'kind', 'match', 'rules', 'references', 'severity'}
KIND_KEYS = {
    'sprite': {'size', 'alpha', 'pixel_art', 'palette'},
    'model': {'triangles_max', 'materials_max', 'texture_max_px', 'height_m', 'origin'},
    'text': {'max_chars', 'forbidden'},
}
CHECKS = {
    'sprite': {'unsupported', 'unreadable', 'size', 'alpha', 'pixel_art_edges', 'pixel_art_scale', 'palette'},
    'model': {'unsupported', 'import', 'triangles', 'materials', 'texture_size', 'height', 'origin'},
    'text': {'unsupported', 'unreadable', 'max_chars', 'forbidden'},
}
RULE_LINE = re.compile(r'^[\s#>*-]*\**([ST]\d+)\b\**\s*(\(blocking\))?', re.M)


class BibleError(ValueError):
    pass


def parse_rules(text):
    rules = {}
    for match in RULE_LINE.finditer(text):
        if match.group(1) in rules:
            raise BibleError(f'STYLE.md: rule {match.group(1)} is defined twice')
        rules[match.group(1)] = bool(match.group(2))
    return rules


def glob_regex(pattern):
    out, i = '', 0
    while i < len(pattern):
        if pattern.startswith('**/', i):
            out, i = out + '(?:.*/)?', i + 3
        elif pattern.startswith('**', i):
            out, i = out + '.*', i + 2
        elif pattern[i] == '*':
            out, i = out + '[^/]*', i + 1
        elif pattern[i] == '?':
            out, i = out + '[^/]', i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out)


def load_bible(repo):
    repo = Path(repo).resolve()
    style_dir = repo / STYLE_DIR
    for name in ('style.json', 'STYLE.md'):
        if not (style_dir / name).is_file():
            raise BibleError(f'{STYLE_DIR}/{name} not found')
    rules = parse_rules((style_dir / 'STYLE.md').read_text())
    try:
        data = json.loads((style_dir / 'style.json').read_text())
    except ValueError as error:
        raise BibleError(f'{STYLE_DIR}/style.json is not valid JSON: {error}') from error
    if not isinstance(data, dict) or data.get('version') != 1:
        raise BibleError('style.json: version must be 1')
    classes = data.get('classes')
    if not isinstance(classes, list) or not classes:
        raise BibleError('style.json: classes must be a non-empty list')
    problems, names = [], set()
    for position, cls in enumerate(classes):
        problems += _validate(f'classes[{position}]', cls, rules, style_dir, names)
    if problems:
        raise BibleError('style.json: ' + '; '.join(problems))
    for cls in classes:
        cls['_match'] = [glob_regex(pattern) for pattern in cls['match']]
    return {'repo': repo, 'style_dir': style_dir, 'rules': rules, 'classes': classes}


def classify(bible, rel):
    matches = [cls for cls in bible['classes'] if any(p.fullmatch(rel) for p in cls['_match'])]
    return (matches[0] if matches else None), [cls['name'] for cls in matches[1:]]


def is_art_file(bible, rel):
    if Path(rel).suffix.lower() in ART_EXTENSIONS:
        return True
    cls, _ = classify(bible, rel)
    return cls is not None and cls['kind'] == 'text'


def load_palette(path):
    colours = []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            colours.append(tuple(int(part) for part in parts[:3]))
    return colours


def _validate(where, cls, rules, style_dir, names):
    if not isinstance(cls, dict):
        return [f'{where} must be an object']
    kind = cls.get('kind')
    if kind not in KIND_KEYS:
        return [f'{where}.kind must be one of sprite, model, text']
    problems = []
    name = cls.get('name')
    if not isinstance(name, str) or not name:
        problems.append(f'{where}.name must be a non-empty string')
    elif name in names:
        problems.append(f'{where}.name {name!r} is duplicated')
    else:
        names.add(name)
    unknown = set(cls) - COMMON_KEYS - KIND_KEYS[kind]
    if unknown:
        problems.append(f'{where} has unknown fields {sorted(unknown)}')
    if not _strings(cls.get('match')) or not cls['match']:
        problems.append(f'{where}.match must be a non-empty list of globs')
    if not _strings(cls.get('rules', [])):
        problems.append(f'{where}.rules must be a list of rule IDs')
    else:
        problems += [f'{where}.rules references {rule}, which STYLE.md does not define'
                     for rule in cls.get('rules', []) if rule not in rules]
    if not _strings(cls.get('references', [])):
        problems.append(f'{where}.references must be a list of paths')
    else:
        problems += [f'{where}.references: {ref} does not exist under {STYLE_DIR}'
                     for ref in cls.get('references', []) if not _inside(style_dir, ref)]
    severity = cls.get('severity', {})
    if not isinstance(severity, dict):
        problems.append(f'{where}.severity must be an object')
    else:
        for check, level in severity.items():
            if check not in CHECKS[kind]:
                problems.append(f'{where}.severity has unknown check {check!r}')
            elif level not in SEVERITIES:
                problems.append(f'{where}.severity.{check} must be one of {", ".join(SEVERITIES)}')
    return problems + {'sprite': _sprite, 'model': _model, 'text': _text}[kind](where, cls, style_dir)


def _sprite(where, cls, style_dir):
    problems = []
    size = cls.get('size', {})
    if not isinstance(size, dict) or set(size) - {'width', 'height', 'multiple_of'}:
        problems.append(f'{where}.size may only have width, height, multiple_of')
    else:
        problems += [f'{where}.size.{axis} must be [min, max]' for axis in ('width', 'height')
                     if axis in size and not _range(size[axis])]
        if 'multiple_of' in size and not _count(size['multiple_of']):
            problems.append(f'{where}.size.multiple_of must be a positive integer')
    if 'alpha' in cls and cls['alpha'] != 'required':
        problems.append(f'{where}.alpha must be "required"')
    if 'pixel_art' in cls and not isinstance(cls['pixel_art'], bool):
        problems.append(f'{where}.pixel_art must be true or false')
    if 'palette' in cls:
        palette = cls['palette']
        if not isinstance(palette, dict) or set(palette) - {'file', 'tolerance'} or not isinstance(palette.get('file'), str):
            problems.append(f'{where}.palette must be {{"file": ..., "tolerance": n}}')
        elif not _inside(style_dir, palette['file']):
            problems.append(f'{where}.palette.file: {palette["file"]} does not exist under {STYLE_DIR}')
        elif 'tolerance' in palette and not (_count(palette['tolerance']) or palette['tolerance'] == 0):
            problems.append(f'{where}.palette.tolerance must be a non-negative integer')
        else:
            cls['_palette'] = load_palette(style_dir / palette['file'])
            if not cls['_palette']:
                problems.append(f'{where}.palette has no colours')
    return problems


def _model(where, cls, style_dir):
    problems = [f'{where}.{key} must be a positive integer'
                for key in ('triangles_max', 'materials_max', 'texture_max_px') if key in cls and not _count(cls[key])]
    if 'height_m' in cls and not _range(cls['height_m']):
        problems.append(f'{where}.height_m must be [min, max]')
    if 'origin' in cls and cls['origin'] not in ('bottom_center', 'center'):
        problems.append(f'{where}.origin must be "bottom_center" or "center"')
    return problems


def _text(where, cls, style_dir):
    problems = []
    if 'max_chars' in cls and not _count(cls['max_chars']):
        problems.append(f'{where}.max_chars must be a positive integer')
    if 'forbidden' in cls and not (_strings(cls['forbidden']) and all(cls['forbidden'])):
        problems.append(f'{where}.forbidden must be a list of non-empty strings')
    return problems


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _range(value):
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value) and value[0] <= value[1])


def _inside(style_dir, ref):
    path = (style_dir / ref).resolve()
    return path.is_file() and path.is_relative_to(style_dir.resolve())
```

Note: `Path.is_relative_to` needs Python 3.9+; the repo already targets 3.11+.

- [ ] **Step 5: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_style_bible.py' -v`
Expected: 9 tests OK (subtests included)

---

### Task 4: Sprite checks

**Files:**
- Create: `factory_art/sprite_checks.py`
- Modify: `tests/art/art_fixtures.py` (append `sprite()`)
- Test: `tests/art/test_sprite_checks.py`

- [ ] **Step 1: Append the sprite fixture to `tests/art/art_fixtures.py`**

```python
from factory_art.png import Image


def sprite(size=32, opaque=False):
    """A round, palette-coloured sprite whose neighbouring pixels differ (so it never looks upscaled)."""
    centre, radius, pixels = (size - 1) / 2, size * 0.4, []
    for y in range(size):
        for x in range(size):
            inside = (x - centre) ** 2 + (y - centre) ** 2 <= radius * radius
            pixels.append(PALETTE[(x + 2 * y) % 3 + 1] + (255,) if inside or opaque else (0, 0, 0, 0))
    return Image(size, size, pixels)


def upscale_pixels(image, factor):
    pixels = []
    for y in range(image.height):
        row = [p for p in image.pixels[y * image.width:(y + 1) * image.width] for _ in range(factor)]
        pixels.extend(row * factor)
    return Image(image.width * factor, image.height * factor, pixels)
```

Move the `from factory_art.png import Image` import to the top of the file with the other imports.

- [ ] **Step 2: Write the failing tests**

`tests/art/test_sprite_checks.py`:

```python
import unittest

from art_fixtures import PALETTE, sprite, upscale_pixels
from factory_art.png import Image
from factory_art.sprite_checks import check_sprite, upscale_factor

CLASS = {'size': {'width': [16, 64], 'height': [16, 64], 'multiple_of': 16}, 'alpha': 'required',
         'pixel_art': True, 'palette': {'file': 'p.gpl', 'tolerance': 4}, '_palette': PALETTE}


def checks(image, cls=CLASS):
    return [(f['severity'], f['check']) for f in check_sprite('a.png', image, cls)]


class SpriteTests(unittest.TestCase):
    def test_good_sprite_has_no_findings(self):
        self.assertEqual(checks(sprite()), [])

    def test_size_range_and_multiple(self):
        self.assertEqual(checks(sprite(96)), [('HIGH', 'size'), ('HIGH', 'size')])
        self.assertEqual(checks(sprite(24)), [('HIGH', 'size')])

    def test_alpha_required(self):
        self.assertEqual(checks(sprite(opaque=True)), [('HIGH', 'alpha')])

    def test_semi_transparent_edges(self):
        image = sprite()
        pixels = list(image.pixels)
        pixels[16 * 32 + 16] = pixels[16 * 32 + 16][:3] + (128,)
        self.assertEqual(checks(Image(32, 32, pixels)), [('MEDIUM', 'pixel_art_edges')])

    def test_upscaled_pixel_art(self):
        self.assertEqual(upscale_factor(upscale_pixels(sprite(16), 4)), 4)
        self.assertEqual(upscale_factor(sprite()), 1)
        self.assertEqual(checks(upscale_pixels(sprite(16), 2)), [('MEDIUM', 'pixel_art_scale')])

    def test_off_palette_within_and_beyond_tolerance(self):
        image = sprite()
        pixels = list(image.pixels)
        pixels[16 * 32 + 16] = (203, 57, 63, 255)   # within 4 of (200, 60, 60)
        self.assertEqual(checks(Image(32, 32, pixels)), [])
        pixels[16 * 32 + 17] = (255, 0, 255, 255)
        found = check_sprite('a.png', Image(32, 32, pixels), CLASS)
        self.assertEqual([(f['check'], f['problem']) for f in found],
                         [('palette', '1 colours off palette (tolerance 4), e.g. #ff00ff')])

    def test_unconfigured_checks_are_skipped(self):
        self.assertEqual(checks(sprite(opaque=True), {}), [])
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_sprite_checks.py' -v`
Expected: ERROR `No module named 'factory_art.sprite_checks'`

- [ ] **Step 4: Implement `factory_art/sprite_checks.py`**

```python
"""Measurable sprite checks: size, alpha, pixel-art edges and scale, palette."""
from .findings import finding

TRANSPARENT = (0, 0, 0, 0)


def check_sprite(rel, image, cls):
    found = []
    size = cls.get('size', {})
    for axis, value in (('width', image.width), ('height', image.height)):
        limits = size.get(axis)
        if limits and not limits[0] <= value <= limits[1]:
            found.append(finding('HIGH', 'size', rel, f'{axis} {value}px outside {limits[0]}-{limits[1]}px'))
    step = size.get('multiple_of')
    if step and (image.width % step or image.height % step):
        found.append(finding('HIGH', 'size', rel, f'{image.width}x{image.height}px is not a multiple of {step}'))
    alphas = [pixel[3] for pixel in image.pixels]
    if cls.get('alpha') == 'required' and min(alphas) == 255:
        found.append(finding('HIGH', 'alpha', rel, 'no transparent pixels; alpha is required'))
    if cls.get('pixel_art'):
        partial = sum(1 for alpha in alphas if 0 < alpha < 255)
        if partial:
            found.append(finding('MEDIUM', 'pixel_art_edges', rel,
                                 f'{partial} semi-transparent pixels; pixel art needs hard edges'))
        factor = upscale_factor(image)
        if factor > 1:
            found.append(finding('MEDIUM', 'pixel_art_scale', rel, f'appears upscaled {factor}x; export at 1x'))
    if cls.get('_palette'):
        tolerance = cls['palette'].get('tolerance', 0)
        off = off_palette(image, cls['_palette'], tolerance)
        if off:
            examples = ', '.join('#%02x%02x%02x' % colour for colour in off[:3])
            found.append(finding('MEDIUM', 'palette', rel,
                                 f'{len(off)} colours off palette (tolerance {tolerance}), e.g. {examples}'))
    return found


def upscale_factor(image):
    pixels = [pixel if pixel[3] else TRANSPARENT for pixel in image.pixels]
    best = 1
    for factor in range(2, min(16, min(image.width, image.height) // 2) + 1):
        if not image.width % factor and not image.height % factor and _uniform(pixels, image, factor):
            best = factor
    return best


def off_palette(image, palette, tolerance):
    colours = {pixel[:3] for pixel in image.pixels if pixel[3]}
    return sorted(colour for colour in colours
                  if all(max(abs(a - b) for a, b in zip(colour, entry)) > tolerance for entry in palette))


def _uniform(pixels, image, factor):
    width = image.width
    for top in range(0, image.height, factor):
        for left in range(0, width, factor):
            first = pixels[top * width + left]
            for y in range(top, top + factor):
                for x in range(left, left + factor):
                    if pixels[y * width + x] != first:
                        return False
    return True
```

- [ ] **Step 5: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_sprite_checks.py' -v`
Expected: 7 tests OK

---

### Task 5: Review views (upscale, backgrounds, contact sheet)

**Files:**
- Create: `factory_art/views.py`
- Test: `tests/art/test_views.py`

- [ ] **Step 1: Write the failing tests**

`tests/art/test_views.py`:

```python
import tempfile
import unittest
from pathlib import Path

from factory_art.png import Image, read_png, write_png
from factory_art.views import composite, contact_sheet, sprite_views, tile, upscale

RED, CLEAR = (255, 0, 0, 255), (0, 0, 0, 0)


class ViewTests(unittest.TestCase):
    def test_upscale_is_nearest_neighbour(self):
        self.assertEqual(upscale(Image(2, 1, [RED, CLEAR]), 2).pixels, [RED, RED, CLEAR, CLEAR] * 2)

    def test_composite_blends_alpha_over_background(self):
        image = composite(Image(2, 1, [(255, 255, 255, 128), CLEAR]), (0, 0, 0))
        self.assertEqual(image.pixels, [(128, 128, 128, 255), (0, 0, 0, 255)])

    def test_tile_fills_missing_cells(self):
        image = tile([Image(1, 1, [RED])] * 3, 2)
        self.assertEqual((image.width, image.height, image.pixels), (2, 2, [RED, RED, RED, CLEAR]))

    def test_sprite_views_writes_three_backgrounds_capped_at_1024(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = sprite_views(Image(300, 2, [RED] * 600), Path(temp) / 'v')
            self.assertEqual([Path(p).name for p in paths], ['transparent.png', 'grey.png', 'dark.png'])
            self.assertEqual(read_png(paths[0]).width, 900)

    def test_contact_sheet(self):
        with tempfile.TemporaryDirectory() as temp:
            parts = []
            for index in range(4):
                parts.append(Path(temp) / f'{index}.png')
                write_png(parts[-1], Image(2, 2, [RED] * 4))
            sheet = contact_sheet(parts, Path(temp) / 'contact.png')
            self.assertEqual(read_png(sheet).width, 4)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_views.py' -v`
Expected: ERROR `No module named 'factory_art.views'`

- [ ] **Step 3: Implement `factory_art/views.py`**

```python
"""Images prepared for the vision pass: upscaled sprites on fixed backgrounds, model contact sheets."""
from pathlib import Path

from .png import Image, read_png, write_png

BACKGROUNDS = (('transparent', None), ('grey', (128, 128, 128)), ('dark', (32, 32, 32)))
MAX_VIEW_PX = 1024


def upscale(image, factor):
    pixels = []
    for y in range(image.height):
        row = [pixel for pixel in image.pixels[y * image.width:(y + 1) * image.width] for _ in range(factor)]
        pixels.extend(row * factor)
    return Image(image.width * factor, image.height * factor, pixels)


def composite(image, background):
    r, g, b = background
    return Image(image.width, image.height, [
        ((p[0] * p[3] + r * (255 - p[3])) // 255, (p[1] * p[3] + g * (255 - p[3])) // 255,
         (p[2] * p[3] + b * (255 - p[3])) // 255, 255) for p in image.pixels])


def tile(images, columns):
    width, height = images[0].width, images[0].height
    if any((image.width, image.height) != (width, height) for image in images):
        raise ValueError('tiled images differ in size')
    rows, pixels = -(-len(images) // columns), []
    for row in range(rows):
        for y in range(height):
            for column in range(columns):
                index = row * columns + column
                pixels.extend(images[index].pixels[y * width:(y + 1) * width] if index < len(images)
                              else [(0, 0, 0, 0)] * width)
    return Image(width * columns, height * rows, pixels)


def sprite_views(image, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    big = upscale(image, max(1, min(4, MAX_VIEW_PX // max(image.width, image.height))))
    paths = []
    for name, background in BACKGROUNDS:
        path = out_dir / f'{name}.png'
        write_png(path, big if background is None else composite(big, background))
        paths.append(str(path))
    return paths


def contact_sheet(paths, out):
    write_png(out, tile([read_png(path) for path in paths], 2))
    return str(out)
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_views.py' -v`
Expected: 5 tests OK

---

### Task 6: Text checks

**Files:**
- Create: `factory_art/text_checks.py`
- Test: `tests/art/test_text_checks.py`

- [ ] **Step 1: Write the failing tests**

`tests/art/test_text_checks.py`:

```python
import json
import unittest

from factory_art.text_checks import check_text, strings

CLASS = {'max_chars': 10, 'forbidden': ['!!']}


def found(document):
    return [(f['severity'], f['check'], f['file']) for f in check_text('ui.json', json.dumps(document).encode(), CLASS)]


class TextTests(unittest.TestCase):
    def test_walks_nested_strings_with_key_paths(self):
        self.assertEqual(list(strings({'a': {'b': 'x'}, 'c': ['y', 3]})), [('a.b', 'x'), ('c[0]', 'y')])

    def test_length_and_forbidden(self):
        self.assertEqual(found({'menu': {'quit': 'Quit the game now', 'go': 'Go!!', 'ok': 'OK'}}),
                         [('HIGH', 'max_chars', 'ui.json#menu.quit'), ('MEDIUM', 'forbidden', 'ui.json#menu.go')])

    def test_unreadable_json_is_a_blocker(self):
        result = check_text('ui.json', b'{', CLASS)
        self.assertEqual([(f['severity'], f['check']) for f in result], [('BLOCKER', 'unreadable')])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_text_checks.py' -v`
Expected: ERROR `No module named 'factory_art.text_checks'`

- [ ] **Step 3: Implement `factory_art/text_checks.py`**

```python
"""Game text checks over every string value in a JSON file."""
import json

from .findings import finding


def check_text(rel, data, cls):
    try:
        document = json.loads(data.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        return [finding('BLOCKER', 'unreadable', rel, f'not UTF-8 JSON: {error}')]
    found = []
    for key, value in strings(document):
        where = f'{rel}#{key}'
        limit = cls.get('max_chars')
        if limit and len(value) > limit:
            found.append(finding('HIGH', 'max_chars', where, f'{len(value)} chars > {limit}: {value[:60]!r}'))
        found += [finding('MEDIUM', 'forbidden', where, f'contains {pattern!r}')
                  for pattern in cls.get('forbidden', []) if pattern in value]
    return found


def strings(node, prefix=''):
    if isinstance(node, str):
        yield prefix or '$', node
    elif isinstance(node, dict):
        for key, value in node.items():
            yield from strings(value, f'{prefix}.{key}' if prefix else key)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from strings(value, f'{prefix}[{index}]')
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_text_checks.py' -v`
Expected: 3 tests OK

---

### Task 7: Model checks (from Blender stats)

**Files:**
- Create: `factory_art/model_checks.py`
- Test: `tests/art/test_model_checks.py`

Stats JSON (written by Task 8's Blender script; Blender is Z-up, glTF Y-up is converted on import):
`{"triangles": int, "materials": int, "textures": [{"name", "width", "height"}], "bbox_min": [x,y,z], "bbox_max": [x,y,z]}` or `{"error": "..."}`.

- [ ] **Step 1: Write the failing tests**

`tests/art/test_model_checks.py`:

```python
import unittest

from factory_art.model_checks import check_model

CLASS = {'triangles_max': 100, 'materials_max': 1, 'texture_max_px': 512,
         'height_m': [0.5, 2.0], 'origin': 'bottom_center'}
GOOD = {'triangles': 12, 'materials': 1, 'textures': [{'name': 't', 'width': 512, 'height': 256}],
        'bbox_min': [-0.5, -0.5, 0.0], 'bbox_max': [0.5, 0.5, 1.0]}


def checks(stats, cls=CLASS):
    return [(f['severity'], f['check']) for f in check_model('crate.glb', stats, cls)]


class ModelTests(unittest.TestCase):
    def test_good_model(self):
        self.assertEqual(checks(GOOD), [])

    def test_limits(self):
        stats = dict(GOOD, triangles=101, materials=2, textures=[{'name': 't', 'width': 2048, 'height': 2048}])
        self.assertEqual(checks(stats), [('HIGH', 'triangles'), ('HIGH', 'materials'), ('HIGH', 'texture_size')])

    def test_height_and_origin(self):
        stats = dict(GOOD, bbox_min=[0.5, -0.5, 0.0], bbox_max=[1.5, 0.5, 3.0])
        self.assertEqual(checks(stats), [('MEDIUM', 'height'), ('MEDIUM', 'origin')])

    def test_centre_origin(self):
        self.assertEqual(checks(GOOD, {'origin': 'center'}), [('MEDIUM', 'origin')])
        centred = dict(GOOD, bbox_min=[-0.5, -0.5, -0.5], bbox_max=[0.5, 0.5, 0.5])
        self.assertEqual(checks(centred, {'origin': 'center'}), [])

    def test_import_error_is_a_blocker(self):
        self.assertEqual(checks({'error': 'RuntimeError: bad file'}), [('BLOCKER', 'import')])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_model_checks.py' -v`
Expected: ERROR `No module named 'factory_art.model_checks'`

- [ ] **Step 3: Implement `factory_art/model_checks.py`**

```python
"""Compare Blender-measured model stats with a style class's limits."""
from .findings import finding

MODEL_EXTENSIONS = {'.glb', '.gltf', '.fbx', '.obj'}


def check_model(rel, stats, cls):
    if 'error' in stats:
        return [finding('BLOCKER', 'import', rel, f'import failed: {stats["error"]}')]
    found = []
    limit = cls.get('triangles_max')
    if limit and stats['triangles'] > limit:
        found.append(finding('HIGH', 'triangles', rel, f'{stats["triangles"]} triangles > {limit}'))
    limit = cls.get('materials_max')
    if limit and stats['materials'] > limit:
        found.append(finding('HIGH', 'materials', rel, f'{stats["materials"]} materials > {limit}'))
    limit = cls.get('texture_max_px')
    for texture in stats['textures'] if limit else []:
        if max(texture['width'], texture['height']) > limit:
            found.append(finding('HIGH', 'texture_size', rel,
                                 f'texture {texture["name"]} {texture["width"]}x{texture["height"]}px > {limit}px'))
    low, high = stats['bbox_min'], stats['bbox_max']
    extent = [b - a for a, b in zip(low, high)]
    limits = cls.get('height_m')
    if limits and not limits[0] <= extent[2] <= limits[1]:
        found.append(finding('MEDIUM', 'height', rel, f'height {extent[2]:.2f} m outside {limits[0]}-{limits[1]} m'))
    origin = cls.get('origin')
    if origin:
        centre = [(a + b) / 2 for a, b in zip(low, high)]
        offsets = (centre[0], centre[1], low[2]) if origin == 'bottom_center' else tuple(centre)
        tolerance = max(0.01, 0.02 * max(extent))
        if any(abs(value) > tolerance for value in offsets):
            x, y, z = offsets
            found.append(finding('MEDIUM', 'origin', rel,
                                 f'origin is not at {origin} (offset x={x:.3f} y={y:.3f} z={z:.3f} m)'))
    return found
```

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_model_checks.py' -v`
Expected: 5 tests OK

---

### Task 8: Blender render script and runner

**Files:**
- Create: `factory_art/blender/render_model.py`, `factory_art/blender_runner.py`
- Modify: `tests/art/art_fixtures.py` (append `write_glb`, `cube`, `grid`)
- Test: `tests/art/test_blender.py`

- [ ] **Step 1: Append model fixtures to `tests/art/art_fixtures.py`**

Add `import struct` to the imports at the top, then append:

```python
def write_glb(path, positions, indices):
    """Minimal glTF 2.0 binary: one mesh, POSITION + uint32 indices, no material."""
    vertices = struct.pack(f'<{len(positions) * 3}f', *[c for p in positions for c in p])
    faces = struct.pack(f'<{len(indices)}I', *indices)
    binary = vertices + faces
    binary += b'\0' * (-len(binary) % 4)
    gltf = {
        'asset': {'version': '2.0'}, 'scene': 0, 'scenes': [{'nodes': [0]}], 'nodes': [{'mesh': 0}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1}]}],
        'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(vertices), 'target': 34962},
                        {'buffer': 0, 'byteOffset': len(vertices), 'byteLength': len(faces), 'target': 34963}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': len(positions), 'type': 'VEC3',
                       'min': [min(p[i] for p in positions) for i in range(3)],
                       'max': [max(p[i] for p in positions) for i in range(3)]},
                      {'bufferView': 1, 'componentType': 5125, 'count': len(indices), 'type': 'SCALAR'}],
    }
    text = json.dumps(gltf).encode()
    text += b' ' * (-len(text) % 4)
    total = 12 + 8 + len(text) + 8 + len(binary)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(struct.pack('<III', 0x46546C67, 2, total) + struct.pack('<I4s', len(text), b'JSON')
                           + text + struct.pack('<I4s', len(binary), b'BIN\0') + binary)


def cube(path):
    """1 m cube standing on the ground (glTF Y-up: y from 0 to 1), 12 triangles."""
    positions = [(x, y, z) for x in (-0.5, 0.5) for y in (0.0, 1.0) for z in (-0.5, 0.5)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    write_glb(path, positions, [i for a, b, c, d in faces for i in (a, b, c, a, c, d)])


def grid(path, cells=60):
    """Flat 1 m square of cells x cells quads: 2 * cells^2 triangles."""
    side = cells + 1
    positions = [(x / cells - 0.5, 0.0, z / cells - 0.5) for z in range(side) for x in range(side)]
    indices = []
    for z in range(cells):
        for x in range(cells):
            a = z * side + x
            indices += [a, a + side, a + 1, a + 1, a + side, a + side + 1]
    write_glb(path, positions, indices)
```

- [ ] **Step 2: Write the failing tests**

`tests/art/test_blender.py` (runner semantics use a fake Blender; the real-Blender test skips when Blender is absent):

```python
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from art_fixtures import cube, grid
from factory_art.blender_runner import BlenderUnavailable, find_blender, render_model
from factory_art.model_checks import check_model
from factory_art.views import contact_sheet

FAKE = f"""#!{sys.executable}
import json, pathlib, sys, time
model, out = sys.argv[sys.argv.index('--') + 1:]
mode = pathlib.Path(model).read_text()
if mode == 'sleep':
    time.sleep(5)
elif mode == 'stats':
    pathlib.Path(out).mkdir(parents=True, exist_ok=True)
    (pathlib.Path(out) / 'stats.json').write_text(json.dumps({{'triangles': 12}}))
sys.exit(1)
"""


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fake = self.root / 'blender'
        self.fake.write_text(FAKE)
        self.fake.chmod(self.fake.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.temp.cleanup()

    def run_fake(self, mode, timeout=30):
        model = self.root / 'model.glb'
        model.write_text(mode)
        return render_model(str(self.fake), model, self.root / 'out', timeout)

    def test_find_blender_order(self):
        self.assertIsNone(find_blender('/nonexistent/blender'))
        self.assertEqual(find_blender(str(self.fake)), str(self.fake))
        with mock.patch.dict(os.environ, {'BLENDER': str(self.fake)}):
            self.assertEqual(find_blender(), str(self.fake))

    def test_reads_stats_even_on_nonzero_exit(self):
        self.assertEqual(self.run_fake('stats'), {'triangles': 12})

    def test_missing_stats_and_timeout_are_environment_failures(self):
        with self.assertRaisesRegex(BlenderUnavailable, 'without stats'):
            self.run_fake('crash')
        with self.assertRaisesRegex(BlenderUnavailable, 'timed out after 1s'):
            self.run_fake('sleep', timeout=1)


@unittest.skipUnless(find_blender(), 'Blender not installed: set BLENDER or install /Applications/Blender.app')
class RealBlenderTests(unittest.TestCase):
    def test_cube_and_dense_grid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cube(root / 'crate.glb')
            grid(root / 'dense.glb')
            stats = render_model(find_blender(), root / 'crate.glb', root / 'crate', 120)
            self.assertEqual(stats['triangles'], 12)
            self.assertEqual(stats['materials'], 0)
            self.assertAlmostEqual(stats['bbox_min'][2], 0.0, places=4)
            self.assertAlmostEqual(stats['bbox_max'][2], 1.0, places=4)
            views = [root / 'crate' / f'{view}.png' for view in ('front', 'three_quarter', 'side', 'top')]
            self.assertTrue(all(view.is_file() for view in views))
            contact_sheet(views, root / 'crate' / 'contact.png')   # Blender PNGs decode with factory_art.png
            prop = {'triangles_max': 5000, 'height_m': [0.2, 2.0], 'origin': 'bottom_center'}
            self.assertEqual(check_model('crate.glb', stats, prop), [])
            dense = render_model(find_blender(), root / 'dense.glb', root / 'dense', 120)
            self.assertEqual(dense['triangles'], 7200)
            self.assertIn('triangles', [f['check'] for f in check_model('dense.glb', dense, prop)])
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_blender.py' -v`
Expected: ERROR `No module named 'factory_art.blender_runner'`

- [ ] **Step 4: Implement `factory_art/blender/render_model.py`**

```python
"""Run inside Blender: blender -b --factory-startup -P render_model.py -- MODEL OUT_DIR

Writes OUT_DIR/stats.json and front/three_quarter/side/top PNG renders, or stats.json with an error.
"""
import json
from pathlib import Path
import sys
import traceback

import bpy
from mathutils import Vector

VIEWS = {'front': (0, -1, 0.0001), 'three_quarter': (1, -1, 0.8), 'side': (1, 0, 0.0001), 'top': (0, -0.0001, 1)}
IMPORTERS = {
    '.glb': lambda path: bpy.ops.import_scene.gltf(filepath=path),
    '.gltf': lambda path: bpy.ops.import_scene.gltf(filepath=path),
    '.fbx': lambda path: bpy.ops.import_scene.fbx(filepath=path),
    '.obj': lambda path: bpy.ops.wm.obj_import(filepath=path),
}


def main(model, out):
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    importer = IMPORTERS.get(Path(model).suffix.lower())
    if importer is None:
        raise ValueError(f'unsupported model format {Path(model).suffix}')
    importer(model)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError('no mesh objects after import')
    depsgraph = bpy.context.evaluated_depsgraph_get()
    triangles, corners, materials = 0, [], set()
    for obj in meshes:
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        triangles += sum(len(polygon.vertices) - 2 for polygon in mesh.polygons)
        evaluated.to_mesh_clear()
        corners += [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        materials.update(slot.material.name for slot in obj.material_slots if slot.material)
    low = [min(corner[i] for corner in corners) for i in range(3)]
    high = [max(corner[i] for corner in corners) for i in range(3)]
    textures = [{'name': image.name, 'width': image.size[0], 'height': image.size[1]}
                for image in bpy.data.images if image.size[0] > 0]
    render(low, high, out)
    (out / 'stats.json').write_text(json.dumps({'triangles': triangles, 'materials': len(materials),
                                                'textures': textures, 'bbox_min': low, 'bbox_max': high}))


def render(low, high, out):
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'STUDIO'
    scene.display.shading.color_type = 'TEXTURE'
    scene.render.resolution_x = scene.render.resolution_y = 512
    scene.render.image_settings.file_format = 'PNG'
    scene.render.image_settings.color_mode = 'RGB'
    scene.render.image_settings.color_depth = '8'
    world = bpy.data.worlds.new('neutral')
    world.color = (0.5, 0.5, 0.5)
    scene.world = world
    centre = Vector([(a + b) / 2 for a, b in zip(low, high)])
    size = max(b - a for a, b in zip(low, high)) or 1.0
    data = bpy.data.cameras.new('review')
    data.type = 'ORTHO'
    data.ortho_scale = size * 1.8
    data.clip_end = size * 20
    camera = bpy.data.objects.new('review', data)
    scene.collection.objects.link(camera)
    scene.camera = camera
    for name, direction in VIEWS.items():
        direction = Vector(direction).normalized()
        camera.location = centre + direction * size * 5
        camera.rotation_euler = (-direction).to_track_quat('-Z', 'Y').to_euler()
        scene.render.filepath = str(out / f'{name}.png')
        bpy.ops.render.render(write_still=True)


if __name__ == '__main__':
    model, out = sys.argv[sys.argv.index('--') + 1:]
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        main(model, out)
    except Exception as error:
        (out / 'stats.json').write_text(json.dumps({'error': f'{type(error).__name__}: {error}'}))
        traceback.print_exc()
        sys.exit(1)
```

- [ ] **Step 5: Implement `factory_art/blender_runner.py`**

```python
"""Locate Blender and run the model render script with a timeout."""
import json
import os
from pathlib import Path
import shutil
import subprocess

DEFAULT_APP = '/Applications/Blender.app/Contents/MacOS/Blender'
SCRIPT = Path(__file__).parent / 'blender' / 'render_model.py'


class BlenderUnavailable(RuntimeError):
    pass


def find_blender(explicit=None):
    if explicit:
        return explicit if _executable(explicit) else None
    for candidate in (os.environ.get('BLENDER'), shutil.which('blender'), DEFAULT_APP):
        if candidate and _executable(candidate):
            return candidate
    return None


def render_model(blender, model, out, timeout=120):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    command = [blender, '-b', '--factory-startup', '--python-exit-code', '1', '-P', str(SCRIPT),
               '--', str(model), str(out)]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise BlenderUnavailable(f'Blender timed out after {timeout}s') from error
    stats = out / 'stats.json'
    if not stats.is_file():
        raise BlenderUnavailable(f'Blender exited {completed.returncode} without stats: {completed.stderr[-300:]}')
    return json.loads(stats.read_text())


def _executable(path):
    return Path(path).is_file() and os.access(path, os.X_OK)
```

- [ ] **Step 6: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_blender.py' -v`
Expected: 4 tests OK (the real-Blender test runs on this machine and takes about 20 s; elsewhere it reports `skipped 'Blender not installed...'`). If the real test fails on the bounding box or triangle count, open `<temp>/crate/three_quarter.png` with the Read tool to inspect the render before changing code.

---

### Task 9: Lint orchestration, CLI and end-to-end fixture repo

**Files:**
- Create: `factory_art/lint.py`, `scripts/art_lint.py`
- Modify: `tests/art/art_fixtures.py` (append `build_testgame`, `__main__`)
- Test: `tests/art/test_lint.py`

- [ ] **Step 1: Append the sample game builder to `tests/art/art_fixtures.py`**

Add `import sys` to the imports at the top, then append:

```python
from factory_art.png import write_png

TESTGAME_CLASSES = [
    {'name': 'character_sprite', 'kind': 'sprite', 'match': ['Assets/Art/Characters/**'],
     'size': {'width': [16, 64], 'height': [16, 64], 'multiple_of': 16}, 'alpha': 'required', 'pixel_art': True,
     'palette': {'file': 'palette.gpl', 'tolerance': 4}, 'rules': ['S1', 'S2'], 'references': ['reference/hero.png']},
    {'name': 'prop_model', 'kind': 'model', 'match': ['Assets/Models/**'], 'triangles_max': 5000,
     'materials_max': 2, 'texture_max_px': 1024, 'height_m': [0.2, 2.0], 'origin': 'bottom_center', 'rules': ['S2']},
    {'name': 'ui_copy', 'kind': 'text', 'match': ['Assets/Text/ui/*.json'], 'max_chars': 20,
     'forbidden': ['!!'], 'rules': ['T1']},
]
TESTGAME_EXPECTED = sorted([
    ('BLOCKER', 'unreadable', 'Assets/Art/Characters/broken.png'),
    ('HIGH', 'alpha', 'Assets/Art/Characters/opaque.png'),
    ('HIGH', 'max_chars', 'Assets/Text/ui/menu.json#menu.quit'),
    ('HIGH', 'size', 'Assets/Art/Characters/huge.png'),
    ('HIGH', 'size', 'Assets/Art/Characters/huge.png'),
    ('MEDIUM', 'forbidden', 'Assets/Text/ui/menu.json#menu.start'),
    ('MEDIUM', 'palette', 'Assets/Art/Characters/blurry.png'),
    ('MEDIUM', 'pixel_art_edges', 'Assets/Art/Characters/blurry.png'),
    ('MEDIUM', 'pixel_art_scale', 'Assets/Art/Characters/huge.png'),
    ('MEDIUM', 'unclassified', 'Assets/Art/Misc/rock.png'),
    ('LOW', 'unsupported', 'Assets/Art/Characters/sketch.jpg'),
])


def build_testgame(root):
    """A sample game repo with one good and several deliberately bad assets of each kind."""
    root = Path(root)
    hero = sprite()
    blurry = list(hero.pixels)
    blurry[16 * 32 + 16] = (255, 0, 255, 255)
    for index in [i for i, pixel in enumerate(blurry) if pixel[3]][:3]:
        blurry[index] = blurry[index][:3] + (128,)
    write_bible(root, TESTGAME_CLASSES, files={'palette.gpl': gpl(PALETTE)})
    (root / 'art/style/reference').mkdir(parents=True, exist_ok=True)
    write_png(root / 'art/style/reference/hero.png', hero)
    chars = root / 'Assets/Art/Characters'
    chars.mkdir(parents=True)
    write_png(chars / 'hero.png', hero)
    write_png(chars / 'blurry.png', Image(32, 32, blurry))
    write_png(chars / 'huge.png', upscale_pixels(hero, 3))
    write_png(chars / 'opaque.png', sprite(opaque=True))
    (chars / 'broken.png').write_bytes(b'not a png')
    (chars / 'sketch.jpg').write_bytes(b'\xff\xd8\xff')
    (chars / 'hero.png.meta').write_text('guid: 1')
    (root / 'Assets/Art/Misc').mkdir(parents=True)
    write_png(root / 'Assets/Art/Misc/rock.png', hero)
    cube(root / 'Assets/Models/crate.glb')
    (root / 'Assets/Text/ui').mkdir(parents=True)
    (root / 'Assets/Text/ui/menu.json').write_text(json.dumps(
        {'menu': {'play': 'Play', 'quit': 'Quit the game right now', 'start': 'Go!!'}}))
    (root / '.git').mkdir()
    write_png(root / '.git/ignored.png', hero)
    (root / 'Library').mkdir()
    write_png(root / 'Library/ignored.png', hero)
    return root


if __name__ == '__main__':
    print(build_testgame(sys.argv[1]))
```

- [ ] **Step 2: Write the failing tests**

`tests/art/test_lint.py`:

```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import TESTGAME_EXPECTED, build_testgame, sprite
from factory_art.lint import collect, run_lint
from factory_art.png import write_png

ROOT = Path(__file__).resolve().parents[2]


class LintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = build_testgame(Path(self.temp.name) / 'game')
        self.out = Path(self.temp.name) / 'lint'

    def tearDown(self):
        self.temp.cleanup()

    def test_collect_skips_hidden_engine_and_bible_dirs(self):
        files = collect(self.repo)
        self.assertIn('Assets/Art/Characters/hero.png', files)
        self.assertFalse([f for f in files if f.startswith(('.git/', 'Library/', 'art/style/'))])
        with self.assertRaises(ValueError):
            collect(self.repo, ['../outside'])

    def test_testgame_produces_exactly_the_expected_findings(self):
        result = run_lint(self.repo, self.out, blender=None)
        self.assertEqual(sorted((f['severity'], f['check'], f['file']) for f in result['findings']), TESTGAME_EXPECTED)
        self.assertEqual(result['unverified'], [{'file': 'Assets/Models/crate.glb', 'cause': 'environment',
                                                 'reason': 'Blender not found'}])
        self.assertEqual(result['blocked_tools'][0]['cmd'], 'blender')
        self.assertTrue(result['lint_blocking'])
        self.assertEqual(json.loads((self.out / 'lint.json').read_text())['lines'], result['lines'])
        hero = next(a for a in result['assets'] if a['file'] == 'Assets/Art/Characters/hero.png')
        self.assertEqual((hero['rules'], len(hero['images']), hero['vision']), (['S1', 'S2'], 3, True))
        self.assertTrue(hero['references'][0].endswith('art/style/reference/hero.png'))

    def test_image_budget_respects_first(self):
        result = run_lint(self.repo, self.out, blender=None, first=['Assets/Art/Characters/opaque.png'], max_images=3)
        reviewed = [a['file'] for a in result['assets'] if a['vision'] and a['images']]
        self.assertEqual(reviewed, ['Assets/Art/Characters/opaque.png'])
        self.assertIn('Assets/Art/Characters/hero.png', result['not_reviewed'])
        self.assertEqual(result['images'], 3)

    def test_severity_override_applies_per_class(self):
        style = self.repo / 'art/style/style.json'
        data = json.loads(style.read_text())
        data['classes'][0]['severity'] = {'alpha': 'LOW'}
        style.write_text(json.dumps(data))
        found = run_lint(self.repo, self.out, blender=None)['findings']
        self.assertIn(('LOW', 'alpha'), [(f['severity'], f['check']) for f in found])

    def test_missing_bible_blocks_only_when_art_exists(self):
        empty = Path(self.temp.name) / 'empty'
        (empty / 'src').mkdir(parents=True)
        (empty / 'src/main.py').write_text('')
        self.assertEqual(run_lint(empty, self.out)['art_files'], 0)
        self.assertEqual(run_lint(empty, self.out)['findings'], [])
        write_png(empty / 'src/hero.png', sprite())
        found = run_lint(empty, self.out)['findings']
        self.assertEqual([(f['severity'], f['check']) for f in found], [('BLOCKER', 'bible')])

    def test_cli_summary_and_bad_path(self):
        cli = [sys.executable, str(ROOT / 'scripts/art_lint.py'), str(self.repo), '--out', str(self.out),
               '--blender', '/nonexistent/blender']
        completed = subprocess.run(cli, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        summary = json.loads(completed.stdout)
        self.assertEqual((summary['findings'], summary['unverified']), (len(TESTGAME_EXPECTED), 1))
        bad = subprocess.run(cli + ['../escape'], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertIn('not an existing path inside', bad.stderr)
```

- [ ] **Step 3: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_lint.py' -v`
Expected: ERROR `No module named 'factory_art.lint'`

- [ ] **Step 4: Implement `factory_art/lint.py`**

```python
"""Deterministic art lint: match files to style classes, measure them, prepare images for review."""
import json
import os
from pathlib import Path

from .blender_runner import BlenderUnavailable, render_model
from .findings import BLOCKING, finding, lines, ordered, override
from .model_checks import MODEL_EXTENSIONS, check_model
from .png import PngError, read_png
from .sprite_checks import check_sprite
from .style_bible import ART_EXTENSIONS, STYLE_DIR, BibleError, classify, is_art_file, load_bible
from .text_checks import check_text
from .views import contact_sheet, sprite_views

SKIP_DIRS = {'node_modules', 'Library', 'Temp', 'Logs'}
VIEWS = ('front', 'three_quarter', 'side', 'top')


def collect(repo, paths=()):
    repo = Path(repo).resolve()
    found = set()
    for path in paths or ['.']:
        target = (repo / path).resolve()
        if not target.is_relative_to(repo) or not target.exists():
            raise ValueError(f'{path} is not an existing path inside {repo}')
        if target.is_file():
            found.add(target.relative_to(repo).as_posix())
            continue
        for directory, dirs, files in os.walk(target):
            dirs[:] = [name for name in dirs if not name.startswith('.') and name not in SKIP_DIRS]
            for name in files:
                file = Path(directory) / name
                if not name.startswith('.') and not file.is_symlink():
                    found.add(file.relative_to(repo).as_posix())
    return sorted(file for file in found if not file.startswith(STYLE_DIR + '/'))


def run_lint(repo, out, paths=(), blender=None, first=(), max_images=40, timeout=120):
    repo, out = Path(repo).resolve(), Path(out)
    files = collect(repo, paths)
    result = {'schema': 'factory-art-lint/v1', 'repo': str(repo), 'art_files': 0, 'images': 0, 'findings': [],
              'assets': [], 'not_reviewed': [], 'unverified': [], 'blocked_tools': [], 'warnings': []}
    try:
        bible = load_bible(repo)
    except BibleError as error:
        art = [file for file in files if Path(file).suffix.lower() in ART_EXTENSIONS]
        result['art_files'] = len(art)
        if art:
            result['findings'].append(finding('BLOCKER', 'bible', STYLE_DIR, str(error)))
        return _finish(result, out)
    art = [file for file in files if is_art_file(bible, file)]
    result['art_files'] = len(art)
    context = {'repo': repo, 'out': out, 'blender': blender, 'timeout': timeout, 'result': result}
    for rel in art:
        cls, overlaps = classify(bible, rel)
        if cls is None:
            result['findings'].append(finding('MEDIUM', 'unclassified', rel, f'matches no class in {STYLE_DIR}/style.json'))
            continue
        if overlaps:
            result['warnings'].append(f"{rel} also matches {', '.join(overlaps)}; using {cls['name']}")
        asset = {'file': rel, 'class': cls['name'], 'kind': cls['kind'], 'rules': cls.get('rules', []),
                 'references': [str(bible['style_dir'] / ref) for ref in cls.get('references', [])], 'images': []}
        found = CHECKERS[cls['kind']](rel, cls, asset, context)
        result['findings'] += override(found, cls.get('severity', {}))
        result['assets'].append(asset)
    _budget(result, first, max_images)
    return _finish(result, out)


def _sprite(rel, cls, asset, context):
    if not rel.lower().endswith('.png'):
        return [finding('LOW', 'unsupported', rel, f'{Path(rel).suffix} sprites are not decoded in this version')]
    try:
        image = read_png(context['repo'] / rel)
    except (OSError, PngError) as error:
        return [finding('BLOCKER', 'unreadable', rel, str(error))]
    asset['images'] = sprite_views(image, context['out'] / 'views' / _slug(rel))
    return check_sprite(rel, image, cls)


def _model(rel, cls, asset, context):
    if Path(rel).suffix.lower() not in MODEL_EXTENSIONS:
        return [finding('LOW', 'unsupported', rel, f'{Path(rel).suffix} models are not checked in this version')]
    renders = context['out'] / 'views' / _slug(rel)
    try:
        if context['blender'] is None:
            raise BlenderUnavailable('Blender not found')
        stats = render_model(context['blender'], context['repo'] / rel, renders, context['timeout'])
        if 'error' not in stats:
            asset['images'] = [contact_sheet([renders / f'{view}.png' for view in VIEWS], renders / 'contact.png')]
    except (BlenderUnavailable, OSError, PngError) as error:
        reason = str(error)
        context['result']['unverified'].append({'file': rel, 'cause': 'environment', 'reason': reason})
        context['result']['blocked_tools'].append(
            {'cmd': 'blender', 'block': reason[:200], 'needed_for': rel, 'attempts': 1})
        return []
    return check_model(rel, stats, cls)


def _text(rel, cls, asset, context):
    if not rel.lower().endswith('.json'):
        return [finding('LOW', 'unsupported', rel, 'only JSON text files are checked in this version')]
    try:
        data = (context['repo'] / rel).read_bytes()
    except OSError as error:
        return [finding('BLOCKER', 'unreadable', rel, str(error))]
    return check_text(rel, data, cls)


CHECKERS = {'sprite': _sprite, 'model': _model, 'text': _text}


def _slug(rel):
    return rel.replace('/', '__')


def _budget(result, first, max_images):
    priority = {path: index for index, path in enumerate(first)}
    assets = sorted(result['assets'], key=lambda asset: priority.get(asset['file'], len(priority)))
    used = 0
    for asset in assets:
        asset['vision'] = used + len(asset['images']) <= max_images
        if asset['vision']:
            used += len(asset['images'])
        else:
            result['not_reviewed'].append(asset['file'])
    result['assets'], result['images'] = assets, used


def _finish(result, out):
    result['findings'] = ordered(result['findings'])
    result['lines'] = lines(result['findings'])
    result['lint_blocking'] = any(item['severity'] in BLOCKING for item in result['findings'])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'lint.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
```

- [ ] **Step 5: Implement `scripts/art_lint.py`**

```python
#!/usr/bin/env python3
"""Lint game art against the repo's art/style bible and prepare images for the vision review."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.blender_runner import find_blender
from factory_art.lint import run_lint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo')
    parser.add_argument('paths', nargs='*', help='files or directories relative to repo (default: all)')
    parser.add_argument('--out', required=True, help='directory for lint.json and review images')
    parser.add_argument('--first', action='append', default=[], help='review this file first (repeatable)')
    parser.add_argument('--max-images', type=int, default=40)
    parser.add_argument('--blender', help='Blender executable (default: $BLENDER, PATH, /Applications)')
    parser.add_argument('--timeout', type=int, default=120, help='seconds per model')
    args = parser.parse_args()
    try:
        result = run_lint(args.repo, args.out, args.paths, find_blender(args.blender), args.first,
                          args.max_images, args.timeout)
    except ValueError as error:
        parser.exit(2, f'art_lint: {error}\n')
    summary = {key: result[key] for key in ('art_files', 'images', 'lint_blocking')}
    summary.update(findings=len(result['findings']), not_reviewed=len(result['not_reviewed']),
                   unverified=len(result['unverified']), lint=str(Path(args.out) / 'lint.json'))
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
```

Then: `chmod +x scripts/art_lint.py`

- [ ] **Step 6: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_lint.py' -v`
Expected: 6 tests OK

- [ ] **Step 7: Run the full suite**

Run: `python3 -m unittest discover -s tests/art -p 'test_*.py' -v`
Expected: all tests OK (Blender test included on this machine)

---

### Task 10: Standalone wrapper `art_check.sh`

**Files:**
- Create: `scripts/art_check.sh`
- Test: `tests/art/test_art_check.py`

- [ ] **Step 1: Write the failing tests** (a stub `hermes` on PATH records its arguments; no model runs)

`tests/art/test_art_check.py`:

```python
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame

ROOT = Path(__file__).resolve().parents[2]
STUB = """#!/bin/sh
printf '%s\\n' "$@" > "$ART_STUB_LOG"
echo stub report > "$(dirname "$ART_STUB_LOG")/out/report.md"
"""


class ArtCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = build_testgame(self.root / 'game')
        bin_dir = self.root / 'bin'
        bin_dir.mkdir()
        (bin_dir / 'hermes').write_text(STUB)
        (bin_dir / 'hermes').chmod(0o755)
        self.env = dict(os.environ, PATH=f'{bin_dir}:{os.environ["PATH"]}', ART_STUB_LOG=str(self.root / 'args.txt'),
                        ART_CHECK_OUT=str(self.root / 'out'))

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self, *paths):
        return subprocess.run(['sh', str(ROOT / 'scripts/art_check.sh'), str(self.repo), *paths],
                              capture_output=True, text=True, env=self.env)

    def test_copies_art_privately_and_runs_profile_once(self):
        completed = self.run_check('Assets/Art')
        self.assertEqual(completed.returncode, 0, completed.stderr)
        out = self.root / 'out'
        self.assertIn(f'REPORT={out}/report.md', completed.stdout)
        self.assertTrue((out / 'src/art/style/style.json').is_file())
        self.assertTrue((out / 'src/Assets/Art/Characters/hero.png').is_file())
        self.assertFalse((out / 'src/Assets/Models').exists())
        self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o700)
        query = (out / 'query.txt').read_text()
        self.assertIn('MODE=standalone', query)
        self.assertIn(f'SRC_DIR={out}/src', query)
        self.assertIn(f'LINT=python3 {ROOT}/scripts/art_lint.py', query)
        args = (self.root / 'args.txt').read_text().split('\n')
        self.assertEqual(args[:3], ['-p', 'art-reviewer', 'chat'])
        self.assertIn('art-review', args)
        self.assertIn(str(out / 'query.txt'), args)

    def test_whole_repo_skips_hidden_and_engine_dirs(self):
        self.assertEqual(self.run_check().returncode, 0)
        src = self.root / 'out/src'
        self.assertTrue((src / 'Assets/Models/crate.glb').is_file())
        self.assertFalse((src / '.git').exists())
        self.assertFalse((src / 'Library').exists())

    def test_rejects_escaping_and_missing_paths(self):
        for path in ('../x', '/etc', 'Assets/../../x', 'missing'):
            with self.subTest(path=path):
                completed = self.run_check(path)
                self.assertEqual(completed.returncode, 2)
                self.assertFalse((self.root / 'args.txt').exists())
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_art_check.py' -v`
Expected: FAIL (`sh: .../scripts/art_check.sh: No such file or directory`, return code 127)

- [ ] **Step 3: Implement `scripts/art_check.sh`**

```sh
#!/bin/sh
# Standalone art review: copy the bible and art into a private workspace, then run the art-reviewer once.
# usage: art_check.sh <repo> [path...]   (paths relative to repo; default: whole repo)
set -eu
usage() { echo "usage: art_check.sh <repo> [path...]" >&2; exit 2; }
[ $# -ge 1 ] && [ -d "$1" ] || usage
repo=$(cd "$1" && pwd)
shift
here=$(cd "$(dirname "$0")" && pwd)
for path in "$@"; do
  case "$path" in
    /*|..|../*|*/..|*/../*) echo "art_check: $path must be relative to the repo, without .." >&2; exit 2 ;;
  esac
  [ -e "$repo/$path" ] || { echo "art_check: $path does not exist in $repo" >&2; exit 2; }
done
out=${ART_CHECK_OUT:-$(mktemp -d "${TMPDIR:-/tmp}/art-check.XXXXXX")}
mkdir -p "$out/src"
chmod 700 "$out"
cd "$repo"
if [ -d art/style ]; then rsync -a --relative --no-links art/style "$out/src/"; fi
[ $# -gt 0 ] || set -- .
rsync -a --relative --no-links --exclude '.?*' --exclude node_modules --exclude Library \
  --exclude Temp --exclude Logs "$@" "$out/src/"
cat > "$out/query.txt" <<EOF
MODE=standalone
SRC_DIR=$out/src
OUT_DIR=$out
LINT=python3 $here/art_lint.py
Review the game art in SRC_DIR against SRC_DIR/art/style. Follow the art-review skill, standalone mode.
EOF
status=0
hermes -p "${ART_REVIEWER_PROFILE:-art-reviewer}" chat --oneshot -Q -s art-review --in "$out" \
  --query-file "$out/query.txt" || status=$?
echo "REPORT=$out/report.md"
exit "$status"
```

Then: `chmod +x scripts/art_check.sh`

- [ ] **Step 4: Run to verify pass**

Run: `python3 -m unittest discover -s tests/art -p 'test_art_check.py' -v`
Expected: 3 tests OK

---

### Task 11: Skill, profile soul and installer

**Files:**
- Create: `factory_art/install/SKILL.md`, `factory_art/install/SOUL.md`, `scripts/install_art_review.sh`
- Test: `tests/art/test_install.py`

- [ ] **Step 1: Write the failing test**

`tests/art/test_install.py`:

```python
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from art_fixtures import build_testgame

ROOT = Path(__file__).resolve().parents[2]


class InstallTests(unittest.TestCase):
    def test_installs_runnable_skill_and_refuses_to_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            skills = Path(temp) / 'skills'
            env = dict(os.environ, HERMES_FACTORY_SKILLS=str(skills))
            command = ['sh', str(ROOT / 'scripts/install_art_review.sh')]
            first = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(first.returncode, 0, first.stderr)
            skill = skills / 'art-review'
            self.assertTrue((skill / 'SKILL.md').read_text().startswith('---\nname: art-review\n'))
            self.assertTrue((skill / 'SOUL.md').is_file())
            self.assertFalse(list(skill.rglob('__pycache__')))
            self.assertFalse((skill / 'factory_art/install').exists())
            repo = build_testgame(Path(temp) / 'game')
            lint = subprocess.run([sys.executable, str(skill / 'scripts/art_lint.py'), str(repo),
                                   '--out', str(Path(temp) / 'lint'), '--blender', '/nonexistent'],
                                  capture_output=True, text=True)
            self.assertEqual(lint.returncode, 0, lint.stderr)
            self.assertEqual(json.loads(lint.stdout)['unverified'], 1)
            again = subprocess.run(command, capture_output=True, text=True, env=env)
            self.assertEqual(again.returncode, 1)
            self.assertIn('already exists', again.stderr)
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m unittest discover -s tests/art -p 'test_install.py' -v`
Expected: FAIL (installer missing, return code 127)

- [ ] **Step 3: Write `factory_art/install/SKILL.md`**

````markdown
---
name: art-review
description: Procedure and scripts for the art-reviewer - lint sprites, 3D models and game text against a repo's art/style bible, then judge the prepared images against its numbered rules.
---

# Art review

`LINT` means `python3 ${HERMES_SKILL_DIR}/scripts/art_lint.py` (standalone queries give the exact command). Run it as its own terminal command, never through `bash -c` or a pipe.

## 1. Lint

`LINT <src_dir> --out <workspace>/lint [--first <changed file>]...`

It prints a one-line JSON summary. Full results are in `<workspace>/lint/lint.json`:

- `art_files`: 0 means there is nothing to review.
- `findings` and `lines`: lint findings. They are measured facts. Never drop, downgrade or dispute them.
- `assets[]`: `file`, `class`, `kind`, `rules` (STYLE.md IDs), `references` (absolute image paths), `images` (absolute paths prepared for you), `vision` (false means over the image budget).
- `not_reviewed`, `unverified` (Blender unavailable: environment, not the asset's fault), `blocked_tools`, `warnings`.

## 2. Judge

Read `<src_dir>/art/style/STYLE.md`. For each asset with `vision: true`:

- Sprite: open all three `images` (transparent, grey and dark backgrounds, nearest-neighbour upscaled) and each `references` image with `vision_analyze`.
- Model: open its contact sheet (front, three-quarter, side and top views) and the references.
- Text: read the file in `<src_dir>` and judge every string against the class's T rules.

Judge only against that asset's `rules`. Each vision finding names the rule ID (or reference image) it breaks and the image path you judged. A vision finding is at most MEDIUM unless STYLE.md marks the cited rule `(blocking)`. Something that bothers you but breaks no listed rule is a NIT `style gap: <suggested rule>`. Never judge an image you did not open.

## 3. Report

Write `report.md`:
1. Summary and verdict.
2. Lint findings, in lint.json order.
3. Vision findings: severity, rule, file, image path, problem, recommended fix.
4. Not reviewed, unverified and blocked tools.
5. Bible warnings and style-gap suggestions.

Number the findings F1... with lint findings first, then vision findings. Verdict: `CHANGES_REQUIRED` if any BLOCKER or HIGH finding exists (lint or vision); otherwise `NO_BLOCKING_FINDINGS`.

## Standalone mode (query starts with MODE=standalone)

The query gives `SRC_DIR`, `OUT_DIR` and `LINT`. Run `LINT SRC_DIR --out OUT_DIR/lint`, judge, and write `OUT_DIR/report.md`. Finding lines use `F<n>|SEV|<rule or check>|<file>|<problem>`. Write nothing outside `OUT_DIR`. End your reply with `VERDICT=<verdict> REPORT=OUT_DIR/report.md`.

## Factory mode (card with a STAGE header)

Follow the factory-worker contract preloaded on the card.

1. `fw.py snapshot` and work only in the printed `src_dir`.
2. From cycle 2: run `fw.py delta`, then pass each changed art file as `--first`, and re-check every file named in SCOPE findings.
3. `LINT <src_dir> --out "$HERMES_KANBAN_WORKSPACE/lint"`. If `art_files` is 0, complete `NO_BLOCKING_FINDINGS` with metadata `art_surface: "none"` and one sentence why.
4. A `bible` BLOCKER on a factory task usually means `art/style` is missing from `.factory/include.txt`. Say so in the finding.
5. Metadata finding lines keep the contract's AC field: `F<n>|SEV|<AC id or ->|<file>|[<rule or check>] <problem>`. Map each finding to the AC it threatens in `.factory/PLAN.md`.
6. Extra metadata: `art_surface: "assets"`, `images_inspected` (count), `not_reviewed`, `unverified`, and the lint `blocked_tools`.
7. Attach `report.md`, `lint/lint.json` and every image you cite. Then `fw.py clean` and `kanban_complete`.
````

- [ ] **Step 4: Write `factory_art/install/SOUL.md`**

```markdown
# Role

You are an independent art reviewer. You did not make these assets. Check sprites, 3D models and game text against the game's own style bible (`art/style/STYLE.md` and `style.json`) and try to show where they break it.

# Rules

1. Follow the art-review skill. It runs the linter first; lint findings are measured facts you never drop, downgrade or dispute.
2. Your own findings come only from images you opened with `vision_analyze` (or text you read). Each one cites a STYLE.md rule ID or a reference image, plus the image path you judged.
3. A vision finding is at most MEDIUM unless the cited rule is marked `(blocking)`. An observation that breaks no listed rule is a NIT `style gap: <suggested rule>`. Never invent a style or impose your taste.
4. Never modify, regenerate or "fix" assets. Never write inside the reviewed repo.
5. Mode: a query starting with `MODE=standalone` uses the skill's standalone section. A kanban card uses factory mode and the factory-worker contract. If a card lacks the "Factory worker contract" section, `kanban_block(reason="factory-worker contract missing")` and stop.
6. Never run Git or GitHub writes. If a command returns BLOCKED, do not work around it; record it in `blocked_tools`.

# Output

Severities: BLOCKER, HIGH, MEDIUM, LOW, NIT. Verdict: `NO_BLOCKING_FINDINGS`, or `CHANGES_REQUIRED` when any BLOCKER or HIGH exists.
```

- [ ] **Step 5: Implement `scripts/install_art_review.sh`**

```sh
#!/bin/sh
# Install the art-review worker skill (skill text, profile soul, factory_art package, scripts).
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
dest=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}/art-review
if [ -e "$dest" ]; then
  echo "install_art_review: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts"
cp "$root/factory_art/install/SKILL.md" "$root/factory_art/install/SOUL.md" "$dest/"
rsync -a --exclude __pycache__ --exclude install "$root/factory_art/" "$dest/factory_art/"
cp "$root/scripts/art_lint.py" "$root/scripts/art_check.sh" "$dest/scripts/"
chmod +x "$dest/scripts/art_lint.py" "$dest/scripts/art_check.sh"
echo "installed $dest"
```

Then: `chmod +x scripts/install_art_review.sh`

- [ ] **Step 6: Run to verify pass, then the full suite**

Run: `python3 -m unittest discover -s tests/art -p 'test_install.py' -v`
Expected: 1 test OK
Run: `python3 -m unittest discover -s tests/art -p 'test_*.py' -v`
Expected: all tests OK

---

### Task 12: Operator docs, install and validation run

**Files:**
- Create: `docs/art-verifier.md`, `docs/art-verifier-results.md`

Steps 2–4 modify `~/.hermes` and step 4 spends model tokens: **ask the user before each of them.**

- [ ] **Step 1: Write `docs/art-verifier.md`**

```markdown
# Art verifier

Checks a game's sprites (PNG), 3D models (glb/gltf/fbx/obj, rendered with Blender) and JSON game text against the game repo's own style bible in `art/style/`. Level 1 only: assets are checked on their own, not inside the engine.

## Style bible

`art/style/STYLE.md` holds numbered rules (`**S1** ...` for visuals, `**T1** ...` for text; add `(blocking)` after an ID to let vision findings on that rule block). `art/style/style.json` holds asset classes; see `docs/superpowers/specs/2026-10-21-art-verifier-design.md` for every field. Optional `palette.gpl` and `reference/` images live alongside.

## Lint only (no model, free)

    python3 scripts/art_lint.py <game-repo> [paths...] --out /tmp/art-lint

Review images and `lint.json` land in the output directory.

## Full review (lint + vision, one paid run)

    ~/.hermes/factory-skills/worker/art-review/scripts/art_check.sh <game-repo> [paths...]

Copies the bible and the given paths to a private temporary directory, runs the `art-reviewer` profile once and prints `REPORT=<path>`. The game repo is never written.

## Install

    sh scripts/install_art_review.sh
    hermes profile create art-reviewer --clone-from ui-reviewer --no-alias \
      --description "Independent art reviewer: checks sprites, 3D models and game text against the repo style bible."
    cp ~/.hermes/factory-skills/worker/art-review/SOUL.md ~/.hermes/profiles/art-reviewer/SOUL.md

The profile is not in any dispatch roster or workflow template; the factory cannot schedule it yet.

## Validation

    python3 -m unittest discover -s tests/art -p 'test_*.py' -v
```

- [ ] **Step 2: Install the skill (ask the user first)**

Run: `sh scripts/install_art_review.sh`
Expected: `installed /Users/example/.hermes/factory-skills/worker/art-review`

- [ ] **Step 3: Create the profile (ask the user first)**

Run:
```sh
hermes profile create art-reviewer --clone-from ui-reviewer --no-alias --description "Independent art reviewer: checks sprites, 3D models and game text against the repo style bible."
cp ~/.hermes/factory-skills/worker/art-review/SOUL.md ~/.hermes/profiles/art-reviewer/SOUL.md
grep -n "dispatch_in_gateway" ~/.hermes/profiles/art-reviewer/config.yaml
grep -n "art-reviewer" ~/.hermes/config.yaml || echo "not in root roster"
```
Expected: profile created; `dispatch_in_gateway: false`; `not in root roster`. Then confirm the skill loads: `hermes -p art-reviewer chat --oneshot -Q -s art-review -q "Reply with the first heading of the art-review skill only."` should answer `Art review`. That costs one short model call; include it in the ask.

- [ ] **Step 4: Manual validation run (paid; ask the user first)**

Run:
```sh
python3 tests/art/art_fixtures.py /private/tmp/art-testgame
scripts/art_check.sh /private/tmp/art-testgame
```
Expected: `REPORT=.../report.md`. Read the report and `lint/lint.json` and check:
- every lint finding from `TESTGAME_EXPECTED` appears unchanged,
- the crate model has a contact sheet and no model findings (Blender is installed),
- every vision finding cites S1/S2/T1 or a reference image plus an image path,
- no vision finding above MEDIUM except on S1,
- the verdict is `CHANGES_REQUIRED` (the fixture has a BLOCKER).

If the user supplies a real Codex-generated sprite, also copy it to `/private/tmp/art-testgame/Assets/Art/Characters/real.png`, run `python3 scripts/art_lint.py /private/tmp/art-testgame Assets/Art/Characters/real.png --out /private/tmp/art-real` and record whether it decodes. Expect palette and pixel-art findings: AI images are not true pixel art.

- [ ] **Step 5: Write `docs/art-verifier-results.md`**

Record: the full test-suite output summary (counts, skips), installer and profile results, and the manual run (report path, verdict, how many vision findings and whether each cited a rule, any deviations). Record each deviation found in steps 2–4 and its fix. State plainly which checks were not run.

---

## Self-review notes

- Spec coverage: bible format and validation (Task 3), lint severities (Tasks 4, 6, 7, 9), unclassified and unsupported (Task 9), Blender path, timeout and environment failures (Task 8, 9), 40-image budget and `--first` for cycle-2 ordering (Task 9), standalone privacy (Task 10), factory-mode contract fields and AC-preserving finding lines (Task 11 SKILL.md), rollout without roster changes (Task 12), real-sprite check (Task 12 step 4, needs the user's file).
- The spec listed `tests/art/fixtures/testgame/`; the plan generates that repo at test time (`build_testgame`) instead of storing binary fixtures, and `python3 tests/art/art_fixtures.py <dir>` materialises it for the manual run.
````
