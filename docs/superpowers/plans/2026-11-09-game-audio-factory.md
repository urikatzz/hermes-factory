# Game Audio Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make game audio a Factory product:
- an `audio` task type with a default **Game Audio** workflow;
- the stages: audio-director prepares, sound-designer synthesizes WAV sound effects or processes Suno music into OGG, audio-reviewer and claude-reviewer review, verifier runs the audio lint gate;
- `audio-reviewer` selectable in any template.

**Architecture:** the same three parts as the game-art rollout (`docs/superpowers/plans/2026-10-26-game-art-factory.md`).
- **Part A** lives in this repo and touches nothing under `~/.hermes`. It adds:
  - a standard-library `factory_audio/` package (WAV I/O, sound bible, measurements, lint);
  - an `audio_production/` package (sfxr-style synthesizer, music processing through ffmpeg);
  - CLIs, skill texts, profile souls and installers.
- **Part B** edits a fresh copy of the live Factory (`artifacts/game-audio-2026-11-06/build/`), which already contains the art edits. Tests in `tests/factory_audio_type/` import that copy, as `tests/factory_art_type` did. This part also adds a one-off migration and an install checker.
- **Part C** is the live rollout. Every step that changes `~/.hermes` says **ASK THE USER FIRST**.

**Tech Stack:** Python 3.11+ standard library (`wave`, `struct`, `math`, `random`, `subprocess`), unittest, ffmpeg 9.0.1 (`/opt/homebrew/bin/ffmpeg`, `ffprobe`), sqlite3, POSIX sh, Hermes CLI (Part C only).

**Spec:** `docs/superpowers/specs/2026-11-06-game-audio-factory-design.md`

**Git:** the user commits manually. Never run `git add` or `git commit`. Each task ends with a test run instead.

**Running tests:**
- Part A: `python3 -m unittest discover -s tests/audio -p 'test_*.py' -v`.
- Part B: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_*.py' -v`. Run it in its own process.
- Regression check after Part B: `HERMES_GAME_ART_COPY=artifacts/game-audio-2026-11-06/build python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py'` must still pass on the audio copy, because the art behaviour must not change.

---

## Decisions grounded in the installed tools and code

1. **ffmpeg's OGG encoder is the native `vorbis`, not libvorbis.** It needs `-strict -2` and **supports only 2 channels**. A mono source fails with "Current FFmpeg Vorbis encoder only supports 2 channels" (checked 2026-11-09). Consequences:
   - The bible rejects an `ogg` class with `channels: 1`.
   - `music_process.py` always encodes stereo, upmixing mono with `-ac 2`.
2. **Loudness and peak come from `ffmpeg -af ebur128=peak=sample -f null -`.** The stderr summary contains `I:         -16.0 LUFS` and, under `Sample peak:`, `Peak:      -1.2 dBFS`; we parse those two. Normalization is two-pass `loudnorm` (`print_format=json` on pass one, then measured values on pass two, with `linear=true`).
3. **WAV handling uses the standard library only.** `wave` reads and writes 16-bit PCM. Other bit depths are a lint finding (format), not a crash. OGG and MP3 are decoded to a temporary 16-bit WAV by ffmpeg before measuring.
4. **GATE lines can only come from the root header.** This is the art decision 1, still true. The Game Audio verify, implement and repair instructions carry the lint command. They name the lint as "audio_lint.py from the audio-review skill (the skill's LINT line gives its absolute path)".
5. **Presets are code.** `_preset('audio')` must exist. The migration reuses it, like art.
6. **The migration mirrors `factory_game_art/migration.py`.** Rather than duplicating it, Task 9 generalizes it into `factory_type_migration/`:
   - The general version takes a spec (`roles`, `choices_from`, `task_type`, `template_name`).
   - Art and audio each pass their own spec.
   - `scripts/migrate_game_art.py` keeps its exact CLI and receipts. Its tests in `tests/factory_art_type/test_migration.py` must keep passing unchanged.
7. **The plugin bundle is copied into the root home and every profile home**, which is 14 homes today plus 3 new profiles. All copies are swapped, using the same procedure as art Task 18.
8. **Every `hermes` CLI call can finish a pending update and stop the gateway.** Check `~/.hermes/gateway_state.json` and `hermes gateway status` after each call (memory: hermes-chat-triggers-pending-update). The gateway runs detached, started with `hermes gateway run`. The dashboard starts with `artifacts/game-art-2026-10-26/start_dashboard.sh`.
9. **The art install must stay untouched.** The audio rollout never edits the art profiles, the art skills or the Game Art template.

---

## File structure

```
factory_audio/
  __init__.py
  wavio.py           read/write 16-bit PCM WAV; samples as floats in [-1, 1], per channel
  bible.py           load audio/style (AUDIO.md rules + audio.json classes), classify, style_hash
  ffmpeg.py          locate ffmpeg/ffprobe, probe, decode to WAV, loudness+peak, waveform/spectrum PNG
  measure.py         pure-Python measures: duration, peak, clipping runs, DC offset, edge silence, loop seam
  lint.py            run_lint(repo, out, paths, ffmpeg): findings per class, lint.json
  install/SKILL.md   audio-review skill text
  install/SOUL.md    audio-reviewer soul
audio_production/
  __init__.py
  synth.py           recipe -> samples (sfxr-style), deterministic
  music.py           trim, loop point, loudnorm, OGG encode
  install/SKILL.md   audio-production skill text
  install/audio-director.SOUL.md
  install/sound-designer.SOUL.md
scripts/
  audio_lint.py  sfx_synth.py  music_process.py
  install_audio_review.sh  install_audio_production.sh
  make_audio_sample.py           sample game with a sound bible for the paid runs
  migrate_game_audio.py          --dry-run / --apply / --rollback [--purge-template]
  check_game_audio_install.py    read-only post-rollout check
factory_type_migration/__init__.py  migration.py   (generalized from factory_game_art)
factory_game_art/migration.py       becomes a thin spec over factory_type_migration
factory_game_audio/__init__.py  migration.py
tests/audio/
  audio_fixtures.py  test_wavio.py  test_bible.py  test_measure.py  test_ffmpeg.py
  test_lint.py  test_lint_cli.py  test_synth.py  test_music.py  test_install.py  test_sample.py
tests/factory_audio_type/
  factory_copy.py  test_copy.py  test_workflow_types.py  test_enumerations.py  test_scripts.py
  test_migration.py  test_bundle.py  test_check_install.py
artifacts/game-audio-2026-11-06/   baseline checksums, build/, patches (untracked)
docs/game-audio-factory-results.md
```

Factory files edited in the copy (Part B). These are the same places the art type touched:

```
factory-dashboard/factory_dashboard/workflow_types.py         CAPABILITIES + TASK_TYPES
factory-dashboard/factory_dashboard/workflow_templates.py     GAME_AUDIO notes + _preset('audio')
factory-dashboard/factory_dashboard/assets/workflow_forms.js  type select
factory-dashboard/factory_dashboard/assets/task_forms.js      type select
scripts/factory_lib.py:156  scripts/factory_ticket.py:12  scripts/factory_intake.py:91  scripts/factory_publish.py:172
factory-skills/orchestrator/software-factory/SKILL.md         TYPE list for chat tickets
```

---

# Part A: this repository (no changes under ~/.hermes)

### Task 1: WAV I/O and test fixtures

**Files:**
- Create: `factory_audio/__init__.py`, `factory_audio/wavio.py`, `tests/audio/audio_fixtures.py`
- Test: `tests/audio/test_wavio.py`

- [ ] **Step 1: Write the fixtures and the failing test**

`factory_audio/__init__.py`:
```python
"""Measure game audio against a repo's audio/style bible (standard library plus the ffmpeg binary)."""
```

`tests/audio/audio_fixtures.py`:
```python
"""Sound bibles, generated tones and a sample game repo for audio tests."""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from factory_audio.wavio import write_wav

RULES_MD = """# Test game sound

**A1** (blocking) UI sounds are short and never harsh.
**A2** Music loops without an audible seam.
"""
SFX_CLASS = {'name': 'ui_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/**'], 'format': 'wav',
             'sample_rate': 44100, 'channels': 1, 'duration_s': [0.05, 1.0], 'peak_dbfs_max': -1.0,
             'loudness_lufs': {'target': -18, 'tolerance': 3}, 'silence_max_ms': 30, 'loop': False, 'rules': ['A1']}
MUSIC_CLASS = {'name': 'music', 'kind': 'music', 'match': ['Assets/Audio/Music/**'], 'format': 'ogg',
               'sample_rate': 44100, 'channels': 2, 'duration_s': [4, 300], 'peak_dbfs_max': -1.0,
               'loudness_lufs': {'target': -16, 'tolerance': 2}, 'silence_max_ms': 200, 'loop': True, 'rules': ['A2']}


def write_bible(root, classes=(SFX_CLASS, MUSIC_CLASS), rules_md=RULES_MD):
    style = Path(root) / 'audio' / 'style'
    style.mkdir(parents=True, exist_ok=True)
    (style / 'AUDIO.md').write_text(rules_md)
    (style / 'audio.json').write_text(json.dumps({'version': 1, 'classes': list(classes)}))
    return style


def tone(seconds, freq=440.0, amp=0.5, rate=44100, channels=1, lead=0.0, tail=0.0, fade=0.005):
    """A sine with optional leading/trailing silence and short fades; returns per-channel float lists."""
    body = int(seconds * rate)
    samples = []
    for i in range(body):
        env = min(1.0, i / (fade * rate), (body - 1 - i) / (fade * rate)) if fade else 1.0
        samples.append(amp * env * math.sin(2 * math.pi * freq * i / rate))
    mono = [0.0] * int(lead * rate) + samples + [0.0] * int(tail * rate)
    return [list(mono) for _ in range(channels)]


def loop_tone(seconds, freq=441.0, amp=0.3, rate=44100, channels=2):
    """A sine with a whole number of cycles, so the end joins the start without a click."""
    cycles = round(seconds * freq)
    count = int(round(cycles * rate / freq))
    mono = [amp * math.sin(2 * math.pi * cycles * i / count) for i in range(count)]
    return [list(mono) for _ in range(channels)]


def write_tone(path, channels_data, rate=44100):
    write_wav(path, channels_data, rate)
    return Path(path)
```

`tests/audio/test_wavio.py`:
```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_wavio -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory_audio.wavio'`

- [ ] **Step 3: Implement**

`factory_audio/wavio.py`:
```python
"""16-bit PCM WAV with the standard library. Samples are floats in [-1, 1], one list per channel."""
from dataclasses import dataclass
import array
import sys
import wave


class WavError(ValueError):
    pass


@dataclass
class Wav:
    rate: int
    channels: int
    bits: int
    data: list  # per-channel lists of floats

    @property
    def frames(self):
        return len(self.data[0]) if self.data else 0

    @property
    def seconds(self):
        return self.frames / self.rate if self.rate else 0.0


def read_wav(path):
    try:
        with wave.open(str(path), 'rb') as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            raw = wav.readframes(frames)
    except (wave.Error, EOFError, OSError) as error:
        raise WavError(f'unreadable WAV: {error}') from error
    if width != 2:
        raise WavError(f'{width * 8}-bit WAV; only 16-bit PCM is supported')
    samples = array.array('h')
    samples.frombytes(raw[:len(raw) - len(raw) % (2 * channels)])
    if sys.byteorder == 'big':
        samples.byteswap()
    data = [[value / 32768 for value in samples[c::channels]] for c in range(channels)]
    return Wav(rate, channels, 16, data)


def write_wav(path, data, rate):
    channels = len(data)
    frames = len(data[0]) if channels else 0
    if any(len(channel) != frames for channel in data):
        raise ValueError('channels differ in length')
    out = array.array('h', bytes(2 * channels * frames))
    for c, channel in enumerate(data):
        for i, value in enumerate(channel):
            out[i * channels + c] = max(-32768, min(32767, int(round(value * 32768))))
    if sys.byteorder == 'big':
        out.byteswap()
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(out.tobytes())
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_wavio -v`
Expected: 3 tests OK.

### Task 2: Sound bible

**Files:**
- Create: `factory_audio/bible.py`
- Test: `tests/audio/test_bible.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_bible -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory_audio.bible'`

- [ ] **Step 3: Implement**

`factory_audio/bible.py`:
```python
"""Load a repo's audio/style bible: AUDIO.md numbered rules and audio.json asset classes."""
import fnmatch
import hashlib
import json
import re
from pathlib import Path

STYLE_DIR = 'audio/style'
AUDIO_EXTENSIONS = {'.wav', '.ogg', '.mp3', '.flac'}
FORMATS = {'wav', 'ogg'}
KINDS = {'sfx', 'music'}
RATES = {22050, 32000, 44100, 48000}
RULE = re.compile(r'\*\*([A-Z][0-9]+)\*\*\s*(\(blocking\))?\s*(.*)')


class BibleError(ValueError):
    pass


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _text(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        raise BibleError(f'{STYLE_DIR}/{path.name} is missing') from None
    except UnicodeDecodeError:
        raise BibleError(f'{STYLE_DIR}/{path.name} is not UTF-8') from None


def _range(cls, key):
    value = cls.get(key)
    if not (isinstance(value, list) and len(value) == 2 and all(_number(v) for v in value) and 0 <= value[0] <= value[1]):
        raise BibleError(f"class {cls.get('name')!r}: {key} must be [min, max] with 0 <= min <= max")


def _check_class(cls, rules):
    name = cls.get('name')
    if not isinstance(name, str) or not name:
        raise BibleError('every class needs a name')
    if cls.get('kind') not in KINDS:
        raise BibleError(f'class {name!r}: kind must be one of {sorted(KINDS)}')
    if cls.get('format') not in FORMATS:
        raise BibleError(f'class {name!r}: format must be one of {sorted(FORMATS)}')
    if not (isinstance(cls.get('match'), list) and cls['match'] and all(isinstance(m, str) for m in cls['match'])):
        raise BibleError(f'class {name!r}: match must be a non-empty list of globs')
    if cls.get('sample_rate') not in RATES:
        raise BibleError(f'class {name!r}: sample_rate must be one of {sorted(RATES)}')
    if cls.get('channels') not in (1, 2):
        raise BibleError(f'class {name!r}: channels must be 1 or 2')
    if cls['format'] == 'ogg' and cls['channels'] != 2:
        raise BibleError(f'class {name!r}: ogg needs 2 channels (the installed ffmpeg Vorbis encoder is stereo only)')
    _range(cls, 'duration_s')
    if not (_number(cls.get('peak_dbfs_max')) and cls['peak_dbfs_max'] <= 0):
        raise BibleError(f'class {name!r}: peak_dbfs_max must be a number <= 0')
    loud = cls.get('loudness_lufs')
    if not (isinstance(loud, dict) and _number(loud.get('target')) and _number(loud.get('tolerance'))
            and loud['target'] < 0 and loud['tolerance'] > 0):
        raise BibleError(f'class {name!r}: loudness_lufs must be {{"target": <0, "tolerance": >0}}')
    if not (_number(cls.get('silence_max_ms', 0)) and cls.get('silence_max_ms', 0) >= 0):
        raise BibleError(f'class {name!r}: silence_max_ms must be a number >= 0')
    if not isinstance(cls.get('loop', False), bool):
        raise BibleError(f'class {name!r}: loop must be true or false')
    for rule in cls.get('rules', []):
        if rule not in rules:
            raise BibleError(f'class {name!r}: rule {rule} is not in AUDIO.md')


def load_bible(repo):
    style = Path(repo) / STYLE_DIR
    try:
        document = json.loads(_text(style / 'audio.json'))
    except json.JSONDecodeError as error:
        raise BibleError(f'{STYLE_DIR}/audio.json is not valid JSON: {error}') from None
    rules = {}
    for line in _text(style / 'AUDIO.md').splitlines():
        match = RULE.match(line.strip())
        if match:
            rules[match.group(1)] = {'blocking': bool(match.group(2)), 'text': match.group(3)}
    if not isinstance(document, dict) or document.get('version') != 1 or not isinstance(document.get('classes'), list):
        raise BibleError(f'{STYLE_DIR}/audio.json needs version 1 and a classes list')
    names = set()
    for cls in document['classes']:
        if not isinstance(cls, dict):
            raise BibleError('every class must be an object')
        _check_class(cls, rules)
        if cls['name'] in names:
            raise BibleError(f"duplicate class {cls['name']!r}")
        names.add(cls['name'])
    return {'rules': rules, 'classes': document['classes']}


def is_audio_file(rel):
    return Path(rel).suffix.lower() in AUDIO_EXTENSIONS


def classify(bible, rel):
    """First class whose glob matches (classes are ordered), plus the names of any later overlaps."""
    hits = [cls for cls in bible['classes'] if any(fnmatch.fnmatch(rel, glob) for glob in cls['match'])]
    return (hits[0] if hits else None), [cls['name'] for cls in hits[1:]]


def style_hash(repo):
    style = Path(repo) / STYLE_DIR
    digest = hashlib.sha256()
    if style.is_dir():
        for file in sorted(p for p in style.rglob('*') if p.is_file() and not p.is_symlink()):
            digest.update(file.relative_to(style).as_posix().encode() + b'\0' + file.read_bytes() + b'\0')
    return digest.hexdigest()
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_bible -v`
Expected: 5 tests OK.

### Task 3: Pure-Python measures

**Files:**
- Create: `factory_audio/measure.py`
- Test: `tests/audio/test_measure.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_measure -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`factory_audio/measure.py`:
```python
"""Sample-level measures on per-channel float lists."""
import math

SILENCE = 10 ** (-60 / 20)  # -60 dBFS
FULL_SCALE = 32767 / 32768


def peak_dbfs(data):
    peak = max((abs(v) for channel in data for v in channel), default=0.0)
    return 20 * math.log10(peak) if peak > 0 else float('-inf')


def clip_runs(data, run=3):
    """Number of runs of `run` or more consecutive samples at full scale."""
    count = 0
    for channel in data:
        length = 0
        for value in channel:
            if abs(value) >= FULL_SCALE:
                length += 1
                if length == run:
                    count += 1
            else:
                length = 0
    return count


def dc_offset(data):
    values = [v for channel in data for v in channel]
    return sum(values) / len(values) if values else 0.0


def edge_silence_ms(data, rate):
    frames = len(data[0]) if data else 0
    loud = [i for i in range(frames) if any(abs(channel[i]) > SILENCE for channel in data)]
    if not loud:
        return frames * 1000 / rate, frames * 1000 / rate
    return loud[0] * 1000 / rate, (frames - 1 - loud[-1]) * 1000 / rate


def _rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def loop_seam(data, rate, window_ms=20):
    """jump: largest last->first sample step relative to the typical step near the seam; rms_ratio_db: level change."""
    window = max(2, int(rate * window_ms / 1000))
    jump, ratio = 0.0, 0.0
    for channel in data:
        if len(channel) < 2 * window:
            continue
        tail, head = channel[-window:], channel[:window]
        steps = [abs(b - a) for a, b in zip(tail, tail[1:])] + [abs(b - a) for a, b in zip(head, head[1:])]
        typical = max(sorted(steps)[len(steps) // 2], 1e-4)
        jump = max(jump, abs(head[0] - tail[-1]) - typical)
        a, b = _rms(tail), _rms(head)
        if a > SILENCE and b > SILENCE:
            ratio = max(ratio, abs(20 * math.log10(a / b)))
    return {'jump': round(max(jump, 0.0), 4), 'rms_ratio_db': round(ratio, 2)}
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_measure -v`
Expected: 5 tests OK. If the good-loop jump is not below 0.05, the median-step baseline is wrong. Fix the measure. Never loosen the test.

### Task 4: ffmpeg wrapper

**Files:**
- Create: `factory_audio/ffmpeg.py`
- Test: `tests/audio/test_ffmpeg.py`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_ffmpeg -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`factory_audio/ffmpeg.py`:
```python
"""Thin wrappers over the ffmpeg and ffprobe binaries. Each call has a timeout and never uses a shell."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from .wavio import read_wav

TIMEOUT = 120


class FFmpegUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str


def find_ffmpeg(explicit=None):
    candidates = [explicit] if explicit else [os.environ.get('FFMPEG'), shutil.which('ffmpeg'), '/opt/homebrew/bin/ffmpeg']
    for path in filter(None, candidates):
        probe_path = str(Path(path).with_name('ffprobe'))
        if os.access(path, os.X_OK) and os.access(probe_path, os.X_OK):
            return Tools(path, probe_path)
    return None


def require(tools):
    if tools is None:
        raise FFmpegUnavailable('ffmpeg/ffprobe not found (set $FFMPEG)')
    return tools


def _run(args, timeout=TIMEOUT):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise FFmpegUnavailable(f'{Path(args[0]).name} timed out after {timeout}s') from error


def probe(tools, path):
    done = _run([tools.ffprobe, '-v', 'error', '-show_entries', 'stream=codec_name,channels,sample_rate:format=duration,format_name',
                 '-select_streams', 'a:0', '-of', 'json', str(path)])
    try:
        data = json.loads(done.stdout or '{}')
        stream = data['streams'][0]
        return {'codec': stream['codec_name'], 'channels': int(stream['channels']),
                'sample_rate': int(stream['sample_rate']), 'container': data['format']['format_name'],
                'duration': float(data['format']['duration'])}
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        raise ValueError(f'ffprobe could not read {path}: {done.stderr.strip()[:200]}') from None


def decode_wav(tools, path, out):
    done = _run([tools.ffmpeg, '-v', 'error', '-y', '-i', str(path), '-c:a', 'pcm_s16le', str(out)])
    if done.returncode:
        raise ValueError(f'ffmpeg could not decode {path}: {done.stderr.strip()[:200]}')
    return read_wav(out)


def loudness(tools, path):
    done = _run([tools.ffmpeg, '-hide_banner', '-nostats', '-i', str(path), '-af', 'ebur128=peak=sample', '-f', 'null', '-'])
    summary = done.stderr.rsplit('Summary:', 1)[-1]
    lufs = re.search(r'I:\s+(-?[\d.]+|-inf) LUFS', summary)
    peak = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', summary)
    if done.returncode or not lufs or not peak:
        raise ValueError(f'ffmpeg ebur128 failed on {path}')
    return {'lufs': float(lufs.group(1)), 'peak_dbfs': float(peak.group(1))}


def pictures(tools, path, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wave_png, spec_png = out_dir / f'{stem}.wave.png', out_dir / f'{stem}.spectrum.png'
    for target, graph in ((wave_png, 'showwavespic=s=1200x240:split_channels=1'), (spec_png, 'showspectrumpic=s=1200x400:legend=1')):
        done = _run([tools.ffmpeg, '-v', 'error', '-y', '-i', str(path), '-filter_complex', graph, '-frames:v', '1', str(target)])
        if done.returncode:
            raise ValueError(f'ffmpeg picture failed on {path}: {done.stderr.strip()[:200]}')
    return [str(wave_png), str(spec_png)]
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_ffmpeg -v`
Expected: 3 tests OK.

### Task 5: Audio lint and CLI

**Files:**
- Create: `factory_audio/lint.py`, `scripts/audio_lint.py`
- Modify: `tests/audio/audio_fixtures.py` (add `build_testgame`)
- Test: `tests/audio/test_lint.py`, `tests/audio/test_lint_cli.py`

- [ ] **Step 1: Add the sample game fixture**

Append to `tests/audio/audio_fixtures.py`:
```python
import subprocess

TESTGAME_EXPECTED = sorted([
    ('BLOCKER', 'unreadable', 'Assets/Audio/SFX/broken.wav'),
    ('HIGH', 'clipping', 'Assets/Audio/SFX/loud.wav'),
    ('HIGH', 'duration', 'Assets/Audio/SFX/long.wav'),
    ('HIGH', 'format', 'Assets/Audio/SFX/stereo.wav'),
    ('HIGH', 'loop_seam', 'Assets/Audio/Music/clicky.ogg'),
    ('HIGH', 'peak', 'Assets/Audio/SFX/loud.wav'),
    ('MEDIUM', 'dc_offset', 'Assets/Audio/SFX/offset.wav'),
    ('MEDIUM', 'silence', 'Assets/Audio/SFX/late.wav'),
    ('MEDIUM', 'unclassified', 'Assets/Other/stray.wav'),
    ('LOW', 'stale_cue', 'audio/cues/boss.md'),
])


def _ogg(ffmpeg, wav, ogg):
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(wav), '-c:a', 'vorbis', '-strict', '-2', str(ogg)], check=True)
    Path(wav).unlink()


def build_testgame(root, ffmpeg):
    """One good and one bad asset per check. Loudness values stay within tolerance except where expected."""
    root = Path(root)
    write_bible(root)
    sfx, music = root / 'Assets/Audio/SFX', root / 'Assets/Audio/Music'
    sfx.mkdir(parents=True); music.mkdir(parents=True)
    write_tone(sfx / 'click.wav', tone(0.12, freq=1200, amp=0.25))
    write_tone(sfx / 'loud.wav', [[max(-1.0, min(1.0, 3 * v)) for v in tone(0.3, amp=0.9)[0]]])
    write_tone(sfx / 'long.wav', tone(2.0, amp=0.25))
    write_tone(sfx / 'stereo.wav', tone(0.2, amp=0.25, channels=2))
    write_tone(sfx / 'offset.wav', [[v + 0.05 for v in tone(0.3, amp=0.2)[0]]])
    write_tone(sfx / 'late.wav', tone(0.2, amp=0.25, lead=0.2))
    (sfx / 'broken.wav').write_bytes(b'RIFF0000WAVEjunk')
    write_tone(music / 'theme.wav', loop_tone(6.0, amp=0.35))
    _ogg(ffmpeg, music / 'theme.wav', music / 'theme.ogg')
    write_tone(music / 'clicky.wav', tone(6.0, freq=437.3, amp=0.35, channels=2, fade=0))
    _ogg(ffmpeg, music / 'clicky.wav', music / 'clicky.ogg')
    (root / 'Assets/Other').mkdir(parents=True)
    write_tone(root / 'Assets/Other/stray.wav', tone(0.1))
    cues = root / 'audio/cues'
    cues.mkdir(parents=True)
    (cues / 'theme.md').write_text('# theme\ntarget: Assets/Audio/Music/theme.ogg\n')
    (cues / 'boss.md').write_text('# boss\ntarget: Assets/Audio/Music/boss.ogg\n')
    return root
```

Loudness is not in the expected list because the test tones are constant-level sines. The tolerances in the fixture classes are set so that `click.wav` and `theme.ogg` pass. Step 4 checks that. If a good asset gets a loudness finding, change the fixture amplitude, not the lint.

- [ ] **Step 2: Write the failing tests**

`tests/audio/test_lint.py`:
```python
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
            (repo / 'Assets/Audio/Music/a.ogg').write_bytes(b'OggS')
            fx.write_tone(repo / 'Assets/Audio/SFX/a.wav', fx.tone(0.12, freq=1200, amp=0.25))
            result = run_lint(repo, Path(tmp) / 'o', (), None)
            self.assertEqual([u['file'] for u in result['unverified']], ['Assets/Audio/Music/a.ogg'])
            self.assertFalse(result['lint_blocking'])


if __name__ == '__main__':
    unittest.main()
```

`tests/audio/test_lint_cli.py`:
```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures as fx
from factory_audio.ffmpeg import find_ffmpeg

CLI = Path(__file__).resolve().parents[2] / 'scripts/audio_lint.py'
FF = find_ffmpeg()


def run(*args):
    return subprocess.run([sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True)


@unittest.skipUnless(FF, 'ffmpeg not installed')
class CliTest(unittest.TestCase):
    def test_gate_and_bible_modes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = fx.build_testgame(Path(tmp) / 'g', FF.ffmpeg)
            self.assertEqual(run(repo, '--out', Path(tmp) / 'o').returncode, 0)
            self.assertEqual(run(repo, '--out', Path(tmp) / 'o2', '--fail-on-blocking').returncode, 1)
            good = run(repo, 'Assets/Audio/SFX/click.wav', '--out', Path(tmp) / 'o3', '--fail-on-blocking')
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            self.assertEqual(json.loads(run(repo, '--check-bible').stdout)['bible'], 'ok')
            self.assertEqual(len(json.loads(run(repo, '--style-hash').stdout)['style_sha256']), 64)
            empty = Path(tmp) / 'e'
            empty.mkdir()
            self.assertEqual(run(empty, '--check-bible').returncode, 1)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd tests/audio && python3 -m unittest test_lint test_lint_cli -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'factory_audio.lint'`

- [ ] **Step 4: Implement**

`factory_audio/lint.py`:
```python
"""Deterministic audio lint: match files to sound classes, measure them, write lint.json and review pictures."""
import json
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.findings import BLOCKING, finding, lines, ordered  # noqa: E402

from .bible import STYLE_DIR, BibleError, classify, is_audio_file, load_bible, style_hash
from .ffmpeg import FFmpegUnavailable, decode_wav, loudness, pictures, probe
from .measure import clip_runs, dc_offset, edge_silence_ms, loop_seam, peak_dbfs
from .wavio import WavError, read_wav

SKIP_DIRS = {'node_modules', 'Library', 'Temp', 'Logs'}
CUES_DIR = 'audio/cues'
INCOMING_DIR = 'audio/incoming'
CODECS = {'wav': ('pcm_s16le',), 'ogg': ('vorbis',)}
SEAM_JUMP_MAX = 0.1
SEAM_RMS_DB_MAX = 3.0
DC_MAX = 0.01


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
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS]
            for name in files:
                file = Path(directory) / name
                if not name.startswith('.') and not file.is_symlink():
                    found.add(file.relative_to(repo).as_posix())
    return sorted(f for f in found if not f.startswith((STYLE_DIR + '/', INCOMING_DIR + '/')))


def _stem(rel):
    return rel.replace('_', '_u').replace('/', '__')


def check_asset(repo, rel, cls, ff, out, result):
    path, found, measures = Path(repo) / rel, [], {}
    if Path(rel).suffix.lower() == '.wav':
        try:
            wav = read_wav(path)
            info = {'codec': 'pcm_s16le', 'channels': wav.channels, 'sample_rate': wav.rate, 'duration': wav.seconds}
        except WavError as error:
            return [finding('BLOCKER', 'unreadable', rel, str(error))], measures, []
    else:
        if ff is None:
            result['unverified'].append({'file': rel, 'reason': 'environment: ffmpeg not found'})
            return [], measures, []
        try:
            info = probe(ff, path)
            with tempfile.TemporaryDirectory() as tmp:
                wav = decode_wav(ff, path, Path(tmp) / 'd.wav')
        except (ValueError, WavError) as error:
            return [finding('BLOCKER', 'unreadable', rel, str(error))], measures, []
    measures.update(info)
    want_ext = '.' + cls['format']
    if Path(rel).suffix.lower() != want_ext or info['codec'] not in CODECS[cls['format']]:
        found.append(finding('HIGH', 'format', rel, f"{info['codec']} file; class {cls['name']} needs {cls['format']}"))
    if info['sample_rate'] != cls['sample_rate'] or info['channels'] != cls['channels']:
        found.append(finding('HIGH', 'format', rel, f"{info['sample_rate']} Hz x{info['channels']}; class needs "
                                                   f"{cls['sample_rate']} Hz x{cls['channels']}"))
    low, high = cls['duration_s']
    if not low <= wav.seconds <= high:
        found.append(finding('HIGH', 'duration', rel, f'{wav.seconds:.2f}s; class allows {low}-{high}s'))
    peak = peak_dbfs(wav.data)
    measures['peak_dbfs'] = round(peak, 2)
    if peak > cls['peak_dbfs_max']:
        found.append(finding('HIGH', 'peak', rel, f"peak {peak:.1f} dBFS above {cls['peak_dbfs_max']}"))
    clips = clip_runs(wav.data)
    if clips:
        found.append(finding('HIGH', 'clipping', rel, f'{clips} clipped runs (3+ full-scale samples)'))
    offset = dc_offset(wav.data)
    if abs(offset) > DC_MAX:
        found.append(finding('MEDIUM', 'dc_offset', rel, f'DC offset {offset:.3f}'))
    lead, tail = edge_silence_ms(wav.data, wav.rate)
    measures.update(lead_silence_ms=round(lead), tail_silence_ms=round(tail))
    limit = cls.get('silence_max_ms', 0)
    if not cls.get('loop') and limit and max(lead, tail) > limit:
        found.append(finding('MEDIUM', 'silence', rel, f'{lead:.0f} ms lead / {tail:.0f} ms tail silence; max {limit} ms'))
    if cls.get('loop'):
        seam = loop_seam(wav.data, wav.rate)
        measures['loop_seam'] = seam
        if seam['jump'] > SEAM_JUMP_MAX or seam['rms_ratio_db'] > SEAM_RMS_DB_MAX:
            found.append(finding('HIGH', 'loop_seam', rel, f"loop seam click: jump {seam['jump']}, level change {seam['rms_ratio_db']} dB"))
    images = []
    if ff is not None:
        try:
            loud = loudness(ff, path)
            measures['lufs'] = loud['lufs']
            target, tol = cls['loudness_lufs']['target'], cls['loudness_lufs']['tolerance']
            off = abs(loud['lufs'] - target)
            if off > 2 * tol:
                found.append(finding('HIGH', 'loudness', rel, f"{loud['lufs']} LUFS; target {target} +/- {tol}"))
            elif off > tol:
                found.append(finding('MEDIUM', 'loudness', rel, f"{loud['lufs']} LUFS; target {target} +/- {tol}"))
            images = pictures(ff, path, Path(out) / 'pictures', _stem(rel))
        except (ValueError, FFmpegUnavailable) as error:
            result['unverified'].append({'file': rel, 'reason': f'environment: {error}'})
    else:
        result['unverified'].append({'file': rel, 'reason': 'environment: ffmpeg not found (loudness not measured)'})
    return found, measures, images


def stale_cues(repo, files):
    found = []
    cues = Path(repo) / CUES_DIR
    if not cues.is_dir():
        return found
    for cue in sorted(cues.glob('*.md')):
        match = re.search(r'^target:\s*(\S+)', cue.read_text(errors='replace'), re.M)
        if match and not (Path(repo) / match.group(1)).is_file():
            found.append(finding('LOW', 'stale_cue', cue.relative_to(repo).as_posix(), f'no file at {match.group(1)} yet'))
    return found


def run_lint(repo, out, paths=(), ff=None, expect_style_hash=None):
    repo, out = Path(repo).resolve(), Path(out)
    files = collect(repo, paths)
    result = {'schema': 'factory-audio-lint/v1', 'repo': str(repo), 'audio_files': 0, 'findings': [], 'assets': [],
              'unverified': [], 'warnings': []}
    if expect_style_hash and style_hash(repo) != expect_style_hash.lower():
        result['findings'].append(finding('BLOCKER', 'style', STYLE_DIR, f'{STYLE_DIR} changed during an asset task'))
    audio = [f for f in files if is_audio_file(f)]
    result['audio_files'] = len(audio)
    try:
        bible = load_bible(repo)
    except BibleError as error:
        if audio:
            result['findings'].append(finding('BLOCKER', 'bible', STYLE_DIR, str(error)))
        return _finish(result, out)
    for rel in audio:
        cls, overlaps = classify(bible, rel)
        if cls is None:
            result['findings'].append(finding('MEDIUM', 'unclassified', rel, f'matches no class in {STYLE_DIR}/audio.json'))
            continue
        if overlaps:
            result['warnings'].append(f'{rel} also matches {overlaps}; using {cls["name"]}')
        found, measures, images = check_asset(repo, rel, cls, ff, out, result)
        result['findings'].extend(found)
        result['assets'].append({'file': rel, 'class': cls['name'], 'kind': cls['kind'], 'rules': cls.get('rules', []),
                                 'measures': measures, 'images': images})
    if not paths:
        result['findings'].extend(stale_cues(repo, files))
    return _finish(result, out)


def _finish(result, out):
    result['findings'] = ordered(result['findings'])
    result['lines'] = lines(result['findings'])
    result['lint_blocking'] = any(f['severity'] in BLOCKING for f in result['findings'])
    out.mkdir(parents=True, exist_ok=True)
    (out / 'lint.json').write_text(json.dumps(result, indent=2) + '\n')
    return result
```

`scripts/audio_lint.py`:
```python
#!/usr/bin/env python3
"""Lint game audio against the repo's audio/style bible and prepare waveform/spectrum pictures for review."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_audio.bible import BibleError, load_bible, style_hash
from factory_audio.ffmpeg import find_ffmpeg
from factory_audio.lint import run_lint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo')
    parser.add_argument('paths', nargs='*', help='files or directories relative to repo (default: all)')
    parser.add_argument('--out', help='directory for lint.json and pictures (required unless --check-bible/--style-hash)')
    parser.add_argument('--ffmpeg', help='ffmpeg executable (default: $FFMPEG, PATH, /opt/homebrew/bin)')
    parser.add_argument('--fail-on-blocking', action='store_true', help='gate mode: exit 1 on any BLOCKER or HIGH')
    parser.add_argument('--check-bible', action='store_true', help='only validate audio/style: exit 0 ok, 1 invalid')
    parser.add_argument('--style-hash', action='store_true', help='only print {"style_sha256": ...} for audio/style')
    parser.add_argument('--expect-style-hash', metavar='HEX', help='BLOCKER "style" when audio/style changed')
    args = parser.parse_args()
    if args.style_hash:
        print(json.dumps({'style_sha256': style_hash(args.repo)}))
        return 0
    if args.check_bible:
        try:
            bible = load_bible(args.repo)
        except BibleError as error:
            print(json.dumps({'bible': 'invalid', 'error': str(error)}))
            return 1
        print(json.dumps({'bible': 'ok', 'classes': [c['name'] for c in bible['classes']], 'rules': sorted(bible['rules'])}))
        return 0
    if not args.out:
        parser.error('--out is required unless --check-bible or --style-hash is given')
    try:
        result = run_lint(args.repo, args.out, args.paths, find_ffmpeg(args.ffmpeg), args.expect_style_hash)
    except ValueError as error:
        parser.exit(2, f'audio_lint: {error}\n')
    print(json.dumps({'audio_files': result['audio_files'], 'findings': len(result['findings']),
                      'unverified': len(result['unverified']), 'lint_blocking': result['lint_blocking'],
                      'lint': str(Path(args.out) / 'lint.json')}))
    return 1 if args.fail_on_blocking and result['lint_blocking'] else 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `cd tests/audio && python3 -m unittest test_lint test_lint_cli -v`
Expected: 5 tests OK. If `TESTGAME_EXPECTED` differs, print `got` and decide per item:
- A good asset (`click`, `theme`) has a finding: fix the fixture amplitude or the measure.
- A bad asset is missing its finding: fix the lint.
- Never delete an expected row to make it pass.

### Task 6: SFX synthesizer

**Files:**
- Create: `audio_production/__init__.py`, `audio_production/synth.py`, `scripts/sfx_synth.py`
- Test: `tests/audio/test_synth.py`

Recipe JSON (all keys optional except `wave`):

| key | meaning | default |
|---|---|---|
| `wave` | `square` `saw` `sine` `triangle` `noise` | (required) |
| `freq_start`, `freq_end` | Hz; linear-in-log slide from start to end | 440, = start |
| `attack`, `sustain`, `decay` | seconds | 0.005, 0.1, 0.15 |
| `sustain_punch` | 0–1 extra level at sustain start, fading out | 0 |
| `vibrato_depth`, `vibrato_hz` | semitones, Hz | 0, 6 |
| `arp_semitones`, `arp_at` | jump after `arp_at` fraction of length | 0, 0.5 |
| `duty` | square duty 0.05–0.95 | 0.5 |
| `lowpass_hz`, `highpass_hz` | one-pole filters; 0 = off | 0, 0 |
| `volume` | linear 0–1 | 0.5 |
| `seed` | noise seed | 1 |
| `sample_rate`, `channels` | output | 44100, 1 |
| `peak_dbfs_max` | output peak clamp (normalize down only) | -1.0 |

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_synth -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'audio_production'`

- [ ] **Step 3: Implement**

`audio_production/__init__.py`:
```python
"""Make game audio: sfxr-style sound effect synthesis and Suno music processing (ffmpeg)."""
```

`audio_production/synth.py`:
```python
"""sfxr-style sound effect synthesis from a JSON recipe. Deterministic for a given recipe and seed."""
import math
import random

WAVES = ('square', 'saw', 'sine', 'triangle', 'noise')
DEFAULTS = {'freq_start': 440.0, 'attack': 0.005, 'sustain': 0.1, 'decay': 0.15, 'sustain_punch': 0.0,
            'vibrato_depth': 0.0, 'vibrato_hz': 6.0, 'arp_semitones': 0.0, 'arp_at': 0.5, 'duty': 0.5,
            'lowpass_hz': 0.0, 'highpass_hz': 0.0, 'volume': 0.5, 'seed': 1, 'sample_rate': 44100, 'channels': 1,
            'peak_dbfs_max': -1.0}
MAX_SECONDS = 30.0


class RecipeError(ValueError):
    pass


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def parse(recipe):
    if not isinstance(recipe, dict) or recipe.get('wave') not in WAVES:
        raise RecipeError(f'recipe needs wave in {WAVES}')
    unknown = set(recipe) - set(DEFAULTS) - {'wave', 'freq_end', 'name', 'notes'}
    if unknown:
        raise RecipeError(f'unknown recipe keys {sorted(unknown)}')
    r = dict(DEFAULTS, **recipe)
    r.setdefault('freq_end', r['freq_start'])
    for key in set(DEFAULTS) | {'freq_end'}:
        if not _number(r[key]):
            raise RecipeError(f'{key} must be a number')
    for key in ('attack', 'sustain', 'decay', 'sustain_punch', 'vibrato_depth', 'lowpass_hz', 'highpass_hz', 'volume'):
        if r[key] < 0:
            raise RecipeError(f'{key} must be >= 0')
    if not 20 <= r['freq_start'] <= 20000 or not 20 <= r['freq_end'] <= 20000:
        raise RecipeError('freq_start and freq_end must be 20-20000 Hz')
    if not 0.05 <= r['duty'] <= 0.95 or not 0 <= r['arp_at'] <= 1 or r['volume'] > 1 or r['sustain_punch'] > 1:
        raise RecipeError('duty 0.05-0.95, arp_at 0-1, volume and sustain_punch 0-1')
    if r['channels'] not in (1, 2) or r['sample_rate'] not in (22050, 32000, 44100, 48000):
        raise RecipeError('channels 1 or 2; sample_rate 22050/32000/44100/48000')
    if r['peak_dbfs_max'] > 0:
        raise RecipeError('peak_dbfs_max must be <= 0')
    length = r['attack'] + r['sustain'] + r['decay']
    if not 0 < length <= MAX_SECONDS:
        raise RecipeError(f'attack+sustain+decay must be > 0 and <= {MAX_SECONDS}s')
    return r


def _envelope(t, r):
    a, s = r['attack'], r['sustain']
    if t < a:
        return t / a
    if t < a + s:
        return 1.0 + r['sustain_punch'] * (1 - (t - a) / s) if s else 1.0
    return max(0.0, 1 - (t - a - s) / r['decay']) if r['decay'] else 0.0


def render(recipe):
    r = parse(recipe)
    rate = int(r['sample_rate'])
    frames = int((r['attack'] + r['sustain'] + r['decay']) * rate)
    rng = random.Random(r['seed'])
    phase, noise, low, high_prev_in, high_prev_out, out = 0.0, rng.uniform(-1, 1), 0.0, 0.0, 0.0, []
    lp = 1 - math.exp(-2 * math.pi * r['lowpass_hz'] / rate) if r['lowpass_hz'] else 1.0
    hp = math.exp(-2 * math.pi * r['highpass_hz'] / rate) if r['highpass_hz'] else 0.0
    for i in range(frames):
        t, frac = i / rate, i / max(1, frames - 1)
        freq = r['freq_start'] * (r['freq_end'] / r['freq_start']) ** frac
        if r['arp_semitones'] and frac >= r['arp_at']:
            freq *= 2 ** (r['arp_semitones'] / 12)
        if r['vibrato_depth']:
            freq *= 2 ** (r['vibrato_depth'] * math.sin(2 * math.pi * r['vibrato_hz'] * t) / 12)
        step = min(freq, rate / 2) / rate
        phase += step
        if phase >= 1:
            phase -= int(phase)
            noise = rng.uniform(-1, 1)
        wave = r['wave']
        if wave == 'square':
            v = 1.0 if phase < r['duty'] else -1.0
        elif wave == 'saw':
            v = 2 * phase - 1
        elif wave == 'sine':
            v = math.sin(2 * math.pi * phase)
        elif wave == 'triangle':
            v = 4 * abs(phase - 0.5) - 1
        else:
            v = noise
        low += lp * (v - low)
        v = low
        if hp:
            high = hp * (high_prev_out + v - high_prev_in)
            high_prev_in, high_prev_out = v, high
            v = high
        out.append(v * _envelope(t, r) * r['volume'])
    limit = 10 ** (r['peak_dbfs_max'] / 20)
    peak = max((abs(v) for v in out), default=0.0)
    if peak > limit:
        out = [v * limit / peak for v in out]
    return [list(out) for _ in range(int(r['channels']))], rate
```

`scripts/sfx_synth.py`:
```python
#!/usr/bin/env python3
"""Render one sfxr-style recipe JSON to a 16-bit WAV. Exit 2 on a bad recipe."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_production.synth import RecipeError, render
from factory_audio.measure import peak_dbfs
from factory_audio.wavio import write_wav


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    try:
        data, rate = render(json.loads(args.recipe.read_text()))
    except (RecipeError, json.JSONDecodeError, OSError) as error:
        parser.exit(2, f'sfx_synth: {error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(args.out, data, rate)
    print(json.dumps({'out': str(args.out), 'seconds': round(len(data[0]) / rate, 3), 'channels': len(data),
                      'peak_dbfs': round(peak_dbfs(data), 2)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_synth -v`
Expected: 6 tests OK.

### Task 7: Music processing

**Files:**
- Create: `audio_production/music.py`, `scripts/music_process.py`
- Test: `tests/audio/test_music.py`

The processing steps, in this order:
1. Decode to 16-bit WAV at the class rate, using ffmpeg `-ar`.
2. Trim edges below -60 dBFS, keeping 10 ms.
3. For a looping cue, find the loop end and crossfade it into the start:
   - search for the end within the last 25% of the track, or `--loop-end S` if given;
   - prefer a zero crossing on a bar boundary when `--bpm` is given (bar = 4 beats);
   - otherwise use the upward zero crossing whose next 20 ms best matches the first 20 ms (lowest sum of squared differences);
   - crossfade 10 ms.
4. Write a temporary WAV.
5. Run two-pass `loudnorm` to the class target, with true peak at the class `peak_dbfs_max`, and encode `vorbis -strict -2 -ac 2 -q:a 5` (OGG) or `pcm_s16le` (WAV).
6. Re-measure with the lint and print JSON.

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd tests/audio && python3 -m unittest test_music -v`
Expected: FAIL (`music_process.py` missing, so the return code is 2 and `stderr` names the file).

- [ ] **Step 3: Implement**

`audio_production/music.py`:
```python
"""Turn a user-supplied Suno file into a game-ready track: trim, optional seamless loop, loudness, encode."""
import json
from pathlib import Path
import re
import subprocess
import tempfile

from factory_audio.ffmpeg import decode_wav, require
from factory_audio.measure import SILENCE
from factory_audio.wavio import write_wav

KEEP_MS = 10
MATCH_MS = 20
FADE_MS = 10


def trim(data, rate):
    frames = len(data[0])
    loud = [i for i in range(frames) if any(abs(c[i]) > SILENCE for c in data)]
    if not loud:
        raise ValueError('the file is silent')
    keep = int(rate * KEEP_MS / 1000)
    start, end = max(0, loud[0] - keep), min(frames, loud[-1] + keep + 1)
    return [c[start:end] for c in data]


def _upward_zero_crossings(mono, lo, hi):
    return [i for i in range(max(1, lo), min(hi, len(mono))) if mono[i - 1] <= 0 < mono[i]]


def find_loop_end(data, rate, bpm=None, loop_end=None):
    mono = [sum(c[i] for c in data) / len(data) for i in range(len(data[0]))]
    n, window = len(mono), int(rate * MATCH_MS / 1000)
    if loop_end is not None:
        lo = hi_target = int(loop_end * rate)
        candidates = _upward_zero_crossings(mono, lo - window, lo + window)
    elif bpm:
        bar = rate * 240 / bpm
        bars = [int(k * bar) for k in range(1, int(n / bar) + 1) if k * bar >= n * 0.75 and k * bar <= n - window]
        candidates = [min(_upward_zero_crossings(mono, b - window, b + window) or [b], key=lambda i, b=b: abs(i - b)) for b in bars]
    else:
        candidates = _upward_zero_crossings(mono, int(n * 0.75), n - window)
    if not candidates:
        raise ValueError('no loop point found; pass --loop-end')
    head = mono[:window]
    def cost(i):
        return sum((a - b) ** 2 for a, b in zip(mono[i:i + window], head))
    return min(candidates, key=cost)


def make_loop(data, rate, end):
    fade = int(rate * FADE_MS / 1000)
    out = []
    for c in data:
        body = c[:end]
        for k in range(fade):
            w = k / fade
            body[k] = body[k] * w + c[end + k] * (1 - w) if end + k < len(c) else body[k]
        out.append(body)
    return out


def _loudnorm(ff, src, dst, target, peak, codec_args):
    first = subprocess.run([ff.ffmpeg, '-hide_banner', '-nostats', '-i', str(src), '-af',
                            f'loudnorm=I={target}:TP={peak}:LRA=11:print_format=json', '-f', 'null', '-'],
                           capture_output=True, text=True, timeout=300)
    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', first.stderr, re.S)
    if first.returncode or not match:
        raise ValueError('loudnorm analysis failed')
    m = json.loads(match.group(0))
    graph = (f"loudnorm=I={target}:TP={peak}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
             f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    done = subprocess.run([ff.ffmpeg, '-v', 'error', '-y', '-i', str(src), '-af', graph, *codec_args, str(dst)],
                          capture_output=True, text=True, timeout=300)
    if done.returncode:
        raise ValueError(f'encode failed: {done.stderr.strip()[:200]}')


def process(ff, src, dst, cls, loop=False, bpm=None, loop_end=None):
    ff = require(ff)
    dst = Path(dst)
    with tempfile.TemporaryDirectory() as tmp:
        resampled = Path(tmp) / 'in.wav'
        done = subprocess.run([ff.ffmpeg, '-v', 'error', '-y', '-i', str(src), '-ar', str(cls['sample_rate']),
                               '-ac', str(cls['channels']), '-c:a', 'pcm_s16le', str(resampled)],
                              capture_output=True, text=True, timeout=300)
        if done.returncode:
            raise ValueError(f'cannot decode {src}: {done.stderr.strip()[:200]}')
        wav = decode_wav(ff, resampled, Path(tmp) / 'pcm.wav')
        data = trim(wav.data, wav.rate)
        report = {'source': str(src), 'out': str(dst), 'trimmed_s': round(wav.seconds - len(data[0]) / wav.rate, 3)}
        if loop:
            end = find_loop_end(data, wav.rate, bpm, loop_end)
            data = make_loop(data, wav.rate, end)
            report['loop_end_s'] = round(end / wav.rate, 3)
        staged = Path(tmp) / 'staged.wav'
        write_wav(staged, data, wav.rate)
        codec = (['-c:a', 'vorbis', '-strict', '-2', '-ac', '2', '-q:a', '5'] if cls['format'] == 'ogg'
                 else ['-c:a', 'pcm_s16le', '-ac', str(cls['channels'])])
        dst.parent.mkdir(parents=True, exist_ok=True)
        _loudnorm(ff, staged, dst, cls['loudness_lufs']['target'], cls['peak_dbfs_max'] - 0.5, ['-ar', str(cls['sample_rate']), *codec])
    report['seconds'] = round(len(data[0]) / wav.rate, 3)
    return report
```

`loudnorm` measures true peak, which can sit above the sample peak. Using `peak_dbfs_max - 0.5` as its TP target leaves headroom. That way the lint's sample-peak check passes, and so does the OGG re-encode, which can overshoot slightly.

`scripts/music_process.py`:
```python
#!/usr/bin/env python3
"""Process one Suno file into a game track for a bible class. Exit 1 on processing failure, 2 on bad arguments."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_production.music import process
from factory_audio.ffmpeg import FFmpegUnavailable, find_ffmpeg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--class', dest='cls', required=True, help='class name in audio.json')
    parser.add_argument('--bible', required=True, type=Path, help='audio/style/audio.json')
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--bpm', type=float)
    parser.add_argument('--loop-end', type=float, help='seconds; search around this point')
    parser.add_argument('--ffmpeg')
    args = parser.parse_args()
    try:
        classes = {c['name']: c for c in json.loads(args.bible.read_text())['classes']}
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f'music_process: cannot read bible: {error}\n')
    if args.cls not in classes or classes[args.cls].get('kind') != 'music':
        parser.exit(2, f'music_process: no music class {args.cls!r} in {args.bible}\n')
    try:
        report = process(find_ffmpeg(args.ffmpeg), args.src, args.out, classes[args.cls], args.loop, args.bpm, args.loop_end)
    except (ValueError, FFmpegUnavailable, OSError) as error:
        print(f'music_process: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 4: Run the test**

Run: `cd tests/audio && python3 -m unittest test_music -v`
Expected: 2 tests OK. If the lint reports `loop_seam` on the processed file, fix the loop search or the crossfade. Do not relax `SEAM_JUMP_MAX`.

- [ ] **Step 5: Run the whole audio suite**

Run: `python3 -m unittest discover -s tests/audio -p 'test_*.py' -v`
Expected: all OK, none skipped (ffmpeg is installed).

### Task 8: Skills, souls, installers and the sample game

**Files:**
- Create:
  - `factory_audio/install/SKILL.md`, `factory_audio/install/SOUL.md`
  - `audio_production/install/SKILL.md`, `audio_production/install/audio-director.SOUL.md`, `audio_production/install/sound-designer.SOUL.md`
  - `scripts/install_audio_review.sh`, `scripts/install_audio_production.sh`, `scripts/make_audio_sample.py`
- Test: `tests/audio/test_install.py`, `tests/audio/test_sample.py`

- [ ] **Step 1: Write the failing tests**

`tests/audio/test_install.py`:
```python
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import audio_fixtures  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


class InstallTest(unittest.TestCase):
    def run_install(self, script, skills):
        return subprocess.run(['sh', str(ROOT / 'scripts' / script)], env=dict(os.environ, HERMES_FACTORY_SKILLS=str(skills)),
                              capture_output=True, text=True)

    def test_both_installers(self):
        with tempfile.TemporaryDirectory() as tmp:
            skills = Path(tmp)
            self.assertEqual(self.run_install('install_audio_review.sh', skills).returncode, 0)
            self.assertEqual(self.run_install('install_audio_production.sh', skills).returncode, 0)
            review, production = skills / 'audio-review', skills / 'audio-production'
            for path in (review / 'scripts/audio_lint.py', review / 'factory_audio/lint.py', review / 'factory_art/findings.py',
                         production / 'scripts/sfx_synth.py', production / 'scripts/music_process.py',
                         production / 'audio_production/synth.py', production / 'factory_audio/wavio.py',
                         production / 'souls/audio-director.SOUL.md', production / 'souls/sound-designer.SOUL.md'):
                self.assertTrue(path.is_file(), path)
            for text in (review / 'SKILL.md', production / 'SKILL.md', production / 'souls/sound-designer.SOUL.md'):
                body = text.read_text()
                self.assertNotIn('${', body, text)
                self.assertIn(str(skills), body, text)
            lint = subprocess.run(['python3', str(review / 'scripts/audio_lint.py'), tmp, '--check-bible'], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 1)
            self.assertIn('invalid', lint.stdout)
            self.assertNotEqual(self.run_install('install_audio_review.sh', skills).returncode, 0)


if __name__ == '__main__':
    unittest.main()
```

`tests/audio/test_sample.py`:
```python
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import audio_fixtures  # noqa: F401
from factory_audio.bible import load_bible

ROOT = Path(__file__).resolve().parents[2]


class SampleTest(unittest.TestCase):
    def test_sample_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'audio-sample'
            done = subprocess.run([sys.executable, str(ROOT / 'scripts/make_audio_sample.py'), str(out)], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            bible = load_bible(out)
            self.assertEqual({c['name'] for c in bible['classes']}, {'ui_sfx', 'game_sfx', 'music'})
            self.assertTrue((out / '.git').is_dir())
            self.assertEqual(subprocess.run(['git', '-C', str(out), 'status', '--porcelain'], capture_output=True, text=True).stdout, '')
            self.assertEqual(json.loads(done.stdout)['repo'], str(out))


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd tests/audio && python3 -m unittest test_install test_sample -v`
Expected: FAIL (the scripts don't exist yet).

- [ ] **Step 3: Write the skill texts and souls**

`factory_audio/install/SKILL.md`:
```markdown
---
name: audio-review
description: Procedure and scripts for the audio-reviewer - measure sound effects and music against a repo's audio/style bible, then judge each asset against its recipe or cue and the AUDIO.md rules.
---

# Audio review

`LINT` means `python3 ${HERMES_SKILL_DIR}/scripts/audio_lint.py`. Run it as its own terminal command, never through `bash -c` or a pipe.

## 1. Lint

`LINT <src_dir> --out <workspace>/lint`

It prints a one-line JSON summary. Full results are in `<workspace>/lint/lint.json`:
- `audio_files`: 0 means there is nothing to review. Complete `NO_BLOCKING_FINDINGS` with `audio_surface: "none"`.
- `findings` and `lines`: measured facts. Never drop, downgrade or dispute them.
- `assets[]`: `file`, `class`, `kind`, `rules`, `measures` (duration, sample rate, channels, peak_dbfs, lufs, edge silence, loop_seam), `images` (waveform and spectrum PNGs).
- `unverified`: ffmpeg missing or failing is an environment problem, not the asset's fault.

## 2. Judge

You cannot listen. Judge from the measures, the recipe or cue, and the pictures.

Read `<src_dir>/audio/style/AUDIO.md`, then for each asset:
- **SFX:** read its recipe in `audio/recipes/<name>.json`. Check that the recipe matches what the PLAN describes (for example, a "jump" should rise in pitch: `freq_end > freq_start`; a "UI click" should be short with a fast decay) and the asset's AUDIO.md rules. Open the waveform picture with `vision_analyze` when the envelope matters.
- **Music:** read its cue in `audio/cues/<name>.md`. Check that the duration, loop flag and BPM are consistent with the cue, and that the measures meet the class.

Each finding names the rule ID (or the PLAN/recipe line) it breaks. A finding is at most MEDIUM unless AUDIO.md marks the cited rule `(blocking)`. Something that breaks no listed rule is a NIT `style gap: <suggested rule>`.

## 3. Report

In factory mode, follow the factory-worker review contract. Findings are `F<n>|SEV|<AC or ->|<file>|[<rule>] <problem>`. Lint findings are copied as they are, with the check name as the rule.
```

`factory_audio/install/SOUL.md`:
```markdown
You are the audio-reviewer: an independent reviewer of game sound effects and music.

Use the audio-review skill at ${HERMES_SKILL_DIR}/SKILL.md for every review. You cannot hear audio; you judge from measurements, recipes, cue sheets and waveform/spectrum pictures, and you say so when a question can only be settled by listening (report it as a NIT "needs listening: <what>").

You never edit files. You never soften a lint finding. You cite a rule ID for every judgment.
```

`audio_production/install/SKILL.md`:
```markdown
---
name: audio-production
description: Procedure and scripts for the Factory sound-designer - sfxr-style sound effect synthesis from JSON recipes, Suno music cue sheets, and processing user-supplied Suno files into game-ready OGG.
---

# Audio production

Tools. Run each as its own terminal command:
- `SYNTH` = `python3 ${HERMES_SKILL_DIR}/scripts/sfx_synth.py <recipe.json> <out.wav>`. Exit 2 means a bad recipe; the message names the key.
- `MUSIC` = `python3 ${HERMES_SKILL_DIR}/scripts/music_process.py <incoming file> <out> --class <music class> --bible <PROJECT_DIR>/audio/style/audio.json [--loop] [--bpm N] [--loop-end S]`. Exit 1 means processing failed; read stderr.
- `LINT` = `python3 ${AUDIO_REVIEW_DIR}/scripts/audio_lint.py <PROJECT_DIR> <changed audio paths> --out <PROJECT_DIR>/.factory/tmp/audio-lint --fail-on-blocking`. Exit 1 means a BLOCKER or HIGH finding; read `lint.json` there.

Scratch output goes under `PROJECT_DIR/.factory/tmp/`. Deliverables go only to the paths in PLAN.md.

## Before you start

Read `.factory/PLAN.md`, `audio/style/AUDIO.md` and `audio/style/audio.json`. For each asset, note its class: format, rate, channels, duration range, loudness, peak and loop.

## Recipe keys (SFX)

- `wave`: square, saw, sine, triangle or noise.
- `freq_start` and `freq_end`: Hz, sliding from start to end.
- `attack`, `sustain`, `decay`: seconds.
- `sustain_punch`: 0–1.
- `vibrato_depth` (semitones) and `vibrato_hz`.
- `arp_semitones` and `arp_at`: 0–1.
- `duty`: square duty.
- `lowpass_hz` and `highpass_hz`.
- `volume`: 0–1.
- `seed`.
- `sample_rate` and `channels`: set these from the class.
- `peak_dbfs_max`: set from the class.

Common shapes:
- **Jump:** square, rising slide.
- **Coin:** square with a +7 semitone arp at about 0.3.
- **Hit:** noise with a fast decay and low-pass.
- **Laser:** saw with a falling slide.
- **UI click:** sine or triangle, under 80 ms, high-pass.

## SFX task

1. Write `audio/recipes/<name>.json` for each effect.
2. Run `SYNTH` to its target path.
3. Run `LINT` on the targets. If it reports a finding, change only that recipe (volume, length, filters) and re-render, up to twice per asset.

## Music cues task

For each cue, write `audio/cues/<name>.md` with these lines:
- `target: <class path>.ogg`
- `class: <music class>`
- `loop: true|false`
- `bpm: <n>`
- `length: <seconds>`

Then add a section `## Suno prompt` containing:
- the style tags, under 200 characters;
- `Instrumental` or the lyrics;
- a one-line description.

Then add `## Save as` naming `audio/incoming/<name>.mp3` (or .wav).

Write no audio. Your completion summary lists every cue and the incoming file name the user must save.

## Music import task

For each cue with a file in `audio/incoming/`, run `MUSIC` to the cue's `target`, using `--loop` and `--bpm` from the cue. Run `LINT` on the targets. List cues without an incoming file under `missing` in the metadata. Never edit or delete anything in `audio/incoming/`.

## Completion

Metadata:
- `assets`: a list of `{path, kind: sfx|music, route: synth|suno, recipe|cue}`.
- `missing`: a list.
- `checks_run`: includes the LINT command.

## Rules

- Never write `audio/style/` except in a style task.
- Never write `audio/incoming/`.
- Never call a paid audio service.
```

`audio_production/install/audio-director.SOUL.md`:
```markdown
You are the audio-director: you plan game audio for the Factory and never write audio files.

Every plan follows the factory-worker contract (PLAN.md, numbered ACs, include list). Read the audio-review skill at ${AUDIO_REVIEW_DIR}/SKILL.md for how assets are checked.

1. Check the bible: `python3 ${AUDIO_REVIEW_DIR}/scripts/audio_lint.py <PROJECT_DIR> --check-bible`.
   - Exit 1, and the prompt is not asking for a sound bible: complete `VERDICT=BLOCKED` with `blocked_reason: "no approved sound bible: submit an Audio task asking for a sound bible"`.
2. Decide the task kind from the prompt and say it in PLAN.md as `audio_task: style|sfx|music-cues|music-import`.

**style**
- Plan AUDIO.md rules, with IDs `A<n>` and `(blocking)` where a breach must stop delivery.
- Plan the audio.json classes, version 1. Every class needs:
  - `name` and `kind` (sfx or music);
  - `match` globs;
  - `format`: wav for sfx, ogg for music;
  - `sample_rate`;
  - `channels`, which must be 2 for ogg;
  - `duration_s` as [min, max];
  - `peak_dbfs_max`;
  - `loudness_lufs` as {target, tolerance};
  - `silence_max_ms`;
  - `loop`;
  - `rules`.
- ACs: `audio_lint --check-bible` exits 0. The include list is `audio/style/`.

**sfx**
- One AC per effect: target path in a class, what it should sound like, recipe hints (wave, slide direction, length).
- Plus one AC: "audio_lint reports no BLOCKER or HIGH".
- Include list: `audio/style/`, `audio/recipes/` and every target.

**music-cues**
- One AC per cue: name, target path, class, mood, BPM, length, loop, and instrumental or lyrics.
- Include list: `audio/style/` and `audio/cues/`.

**music-import**
- List the cues in `audio/cues/` and which have files in `audio/incoming/`.
- One AC per present file, plus the lint AC.
- Include list: `audio/style/`, `audio/cues/`, `audio/incoming/` (read only) and the targets.

For every task except style, run `python3 ${AUDIO_REVIEW_DIR}/scripts/audio_lint.py <PROJECT_DIR> --style-hash` and record `style_sha256: <hex>` in PLAN.md.
```

`audio_production/install/sound-designer.SOUL.md`:
```markdown
You are the sound-designer: you make the planned game audio and nothing else.

Use the audio-production skill at ${HERMES_SKILL_DIR}/SKILL.md. Work in PROJECT_DIR as a writer under the factory-worker contract.

Rules:
- Write only to the paths in PLAN.md.
- Never write `audio/style/` unless PLAN.md says `audio_task: style`.
- Never write `audio/incoming/`.
- Before completing, run the LINT gate with `--expect-style-hash <style_sha256 from PLAN.md>` when PLAN.md records one. Record the command in checks_run.
- In repair, change only the assets named in the findings.
- Never use a paid audio service.
```

- [ ] **Step 4: Write the installers and the sample script**

`scripts/install_audio_review.sh`:
```sh
#!/bin/sh
# Install the audio-review worker skill: skill text, reviewer soul, factory_audio + factory_art.findings, audio_lint.py.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/audio-review
if [ -e "$dest" ]; then
  echo "install_audio_review: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/factory_art"
rsync -a --exclude __pycache__ --exclude install "$root/factory_audio/" "$dest/factory_audio/"
cp "$root/factory_art/__init__.py" "$root/factory_art/findings.py" "$dest/factory_art/"
cp "$root/scripts/audio_lint.py" "$dest/scripts/audio_lint.py"
chmod +x "$dest/scripts/audio_lint.py"
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" "$root/factory_audio/install/SKILL.md" > "$dest/SKILL.md"
sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" "$root/factory_audio/install/SOUL.md" > "$dest/SOUL.md"
echo "installed $dest"
```

`factory_art/__init__.py` imports nothing heavy, so copying it with `findings.py` is enough. The test checks this by running the installed `audio_lint.py`. If `factory_art/__init__.py` imports other modules, copy the whole `factory_art/` with rsync instead, as `install_art_production.sh` does.

`scripts/install_audio_production.sh`:
```sh
#!/bin/sh
# Install the audio-production worker skill: skill text, audio profile souls, packages and scripts.
set -eu
root=$(cd "$(dirname "$0")/.." && pwd)
skills=${HERMES_FACTORY_SKILLS:-$HOME/.hermes/factory-skills/worker}
dest=$skills/audio-production
if [ -e "$dest" ]; then
  echo "install_audio_production: $dest already exists; move it aside to reinstall" >&2
  exit 1
fi
mkdir -p "$dest/scripts" "$dest/souls" "$dest/factory_art"
rsync -a --exclude __pycache__ --exclude install "$root/factory_audio/" "$dest/factory_audio/"
rsync -a --exclude __pycache__ --exclude install "$root/audio_production/" "$dest/audio_production/"
cp "$root/factory_art/__init__.py" "$root/factory_art/findings.py" "$dest/factory_art/"
for name in sfx_synth.py music_process.py; do cp "$root/scripts/$name" "$dest/scripts/$name"; done
chmod +x "$dest"/scripts/*
esc() { printf '%s' "$1" | sed 's/[|&\\]/\\&/g'; }
fill() {
  sed -e "s|\${HERMES_SKILL_DIR}|$(esc "$dest")|g" -e "s|\${AUDIO_REVIEW_DIR}|$(esc "$skills/audio-review")|g" "$1" > "$2"
}
fill "$root/audio_production/install/SKILL.md" "$dest/SKILL.md"
fill "$root/audio_production/install/audio-director.SOUL.md" "$dest/souls/audio-director.SOUL.md"
fill "$root/audio_production/install/sound-designer.SOUL.md" "$dest/souls/sound-designer.SOUL.md"
echo "installed $dest"
```

`scripts/make_audio_sample.py`:
```python
#!/usr/bin/env python3
"""Create a sample game repo with an approved sound bible, for the paid end-to-end Audio tasks. Prints {"repo": ...}."""
import json
from pathlib import Path
import subprocess
import sys

RULES = """# Sample game sound

**A1** (blocking) UI sounds are short (under 150 ms) and never harsh: no energy above 8 kHz dominates.
**A2** (blocking) Music loops without an audible seam.
**A3** Game effects are retro chiptune: square, triangle and noise voices.
**A4** Jump sounds rise in pitch; damage sounds fall.
"""
CLASSES = [
    {'name': 'ui_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/UI/**'], 'format': 'wav', 'sample_rate': 44100,
     'channels': 1, 'duration_s': [0.02, 0.15], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -20, 'tolerance': 4},
     'silence_max_ms': 20, 'loop': False, 'rules': ['A1']},
    {'name': 'game_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/Game/**'], 'format': 'wav', 'sample_rate': 44100,
     'channels': 1, 'duration_s': [0.05, 1.5], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -16, 'tolerance': 4},
     'silence_max_ms': 30, 'loop': False, 'rules': ['A3', 'A4']},
    {'name': 'music', 'kind': 'music', 'match': ['Assets/Audio/Music/**'], 'format': 'ogg', 'sample_rate': 44100,
     'channels': 2, 'duration_s': [20, 240], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -16, 'tolerance': 2},
     'silence_max_ms': 200, 'loop': True, 'rules': ['A2']},
]


def main():
    repo = Path(sys.argv[1]).resolve()
    if repo.exists():
        sys.exit(f'{repo} already exists')
    style = repo / 'audio/style'
    style.mkdir(parents=True)
    (style / 'AUDIO.md').write_text(RULES)
    (style / 'audio.json').write_text(json.dumps({'version': 1, 'classes': CLASSES}, indent=2) + '\n')
    (repo / 'README.md').write_text('# Audio sample game\n\nSample repo for Factory Audio tasks.\n')
    for args in (['init', '-q', '-b', 'main'], ['add', '-A'],
                 ['-c', 'user.name=factory', '-c', 'user.email=factory@localhost', 'commit', '-q', '-m', 'Sound bible']):
        subprocess.run(['git', '-C', str(repo), *args], check=True)
    print(json.dumps({'repo': str(repo)}))


if __name__ == '__main__':
    main()
```

- [ ] **Step 5: Run the tests and the full Part A suite**

Run: `python3 -m unittest discover -s tests/audio -p 'test_*.py' -v`
Expected: all OK. Also run `python3 -m unittest discover -s tests/art -p 'test_*.py'` and `python3 -m unittest discover -s tests/production -p 'test_*.py'`, which must still be 67 and 43 OK.

---

# Part B: Factory copy (still nothing under ~/.hermes is written)

### Task 9: Generalize the type migration (art behaviour unchanged)

**Files:**
- Create: `factory_type_migration/__init__.py`, `factory_type_migration/migration.py`
- Modify: `factory_game_art/migration.py` (becomes a spec)
- Test: the existing `tests/factory_art_type/test_migration.py`, unchanged

- [ ] **Step 1: Run the art migration tests first (the baseline)**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_migration.py' -v`
Expected: all OK. Write down the count.

- [ ] **Step 2: Move the code**

1. Copy `factory_game_art/migration.py` to `factory_type_migration/migration.py`.
2. In the copy:
   - Replace the module constants `NEW_ROLES`, `CHOICES_FROM` and `TEMPLATE_NAME`, and the literal `'art'` and the schema names, with fields of a `TypeSpec`:
     ```python
     from dataclasses import dataclass

     @dataclass(frozen=True)
     class TypeSpec:
         task_type: str          # 'art'
         template_name: str      # 'Game Art'
         roles: dict             # role -> {'provider','model','effort'}
         choices_from: dict      # role -> existing role whose catalog choices it inherits
         schema: str             # 'factory-game-art' -> receipts f'{schema}-migration/v1', f'{schema}-rollback/v1'
     ```
   - Change `load_source(dashboard_source)` to `load_source(dashboard_source, spec)`. The check becomes `spec.task_type not in workflow_types.TASK_TYPES or not set(spec.roles) <= set(workflow_types.CAPABILITIES)`, with the message `f'{source} lacks the {spec.task_type} task type and roles; install the {spec.template_name} source edits first'`.
   - Change `catalog_changes(catalog)` to `catalog_changes(catalog, spec)`, reading `spec.roles` and `spec.choices_from`.
   - Change `Migration.__init__(self, dashboard_source, settings_db, catalog_path)` to `Migration(spec, dashboard_source, settings_db, catalog_path)`, storing `self.spec`.
   - Rename `_game_art` to `_existing`. Every `'art'` becomes `self.spec.task_type`, `TEMPLATE_NAME` becomes `self.spec.template_name`, and `NEW_ROLES` becomes `self.spec.roles`.
   - The purge snapshot probe becomes `(f'%"task_type":"{self.spec.task_type}"%',)`. Its messages use the type name.
   - Keep `profiles`, `write_atomic` and `write_receipt` unchanged.
3. `factory_type_migration/__init__.py`: `"""Add a task type's roles, catalog entries, template and type default to the Factory; reverse it."""`
4. Rewrite `factory_game_art/migration.py` as:

```python
"""Game Art spec over the generic type migration. Public names kept for scripts/migrate_game_art.py and its tests."""
from factory_type_migration.migration import (ALLOWED_PROVIDERS, TypeSpec, profiles, write_atomic, write_receipt)  # noqa: F401
from factory_type_migration import migration as _m

NEW_ROLES = {
    'art-director': {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'effort': 'high'},
    'artist': {'provider': 'openai-codex', 'model': 'gpt-6-luna', 'effort': 'medium'},
    'art-reviewer': {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'effort': 'high'},
}
CHOICES_FROM = {'art-director': 'architect', 'artist': 'developer', 'art-reviewer': 'verifier'}
TEMPLATE_NAME = 'Game Art'
SPEC = TypeSpec('art', TEMPLATE_NAME, NEW_ROLES, CHOICES_FROM, 'factory-game-art')


def load_source(dashboard_source):
    return _m.load_source(dashboard_source, SPEC)


def catalog_changes(catalog):
    return _m.catalog_changes(catalog, SPEC)


class Migration(_m.Migration):
    def __init__(self, dashboard_source, settings_db, catalog_path):
        super().__init__(SPEC, dashboard_source, settings_db, catalog_path)
```

- [ ] **Step 3: Run the art migration tests again**

Run: `python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py' -v`
Expected: the same count as Step 1, all OK, with no test edited. If a test patches a module-level name (for example `factory_game_art.migration.NEW_ROLES`), keep that name as the object the spec holds, which this code already does. Do not change the test.

### Task 10: Build the audio copy and the test harness

**Files:**
- Create: `artifacts/game-audio-2026-11-06/` (baseline and build), `tests/factory_audio_type/factory_copy.py`, `tests/factory_audio_type/test_copy.py`

- [ ] **Step 1: Make the copy from the live install (read only)**

```sh
A=/Users/example/orca/projects/hermes/artifacts/game-audio-2026-11-06
mkdir -p "$A/build"
cd ~/.hermes
for d in factory-dashboard scripts factory-skills/orchestrator; do
  mkdir -p "$A/build/$(dirname $d)"; rsync -a --exclude __pycache__ --exclude .git "$d" "$A/build/$(dirname $d)/"
done
mkdir -p "$A/build/factory-dashboard/integrations/hermes_factory_models"
cp ~/.hermes/plugins/factory-models/plugin.yaml ~/.hermes/plugins/factory-models/__init__.py "$A/build/factory-dashboard/integrations/hermes_factory_models/"
find factory-dashboard scripts factory-skills/orchestrator -type f ! -path '*/__pycache__/*' -exec shasum -a 256 {} + > "$A/baseline.sha256"
```

Then check that the copy has the art edits: `grep -c "'art'" "$A/build/factory-dashboard/factory_dashboard/workflow_types.py"` must print at least 1.

- [ ] **Step 2: The harness**

`tests/factory_audio_type/factory_copy.py`: this is `tests/factory_art_type/factory_copy.py` with three changes:
- the env var is `HERMES_GAME_AUDIO_COPY`;
- the default is `REPO / 'artifacts/game-audio-2026-11-06/build'`;
- the docstring says Game Audio.

All the other lines, including the live-home refusal and the import-origin check, stay the same.

`tests/factory_audio_type/test_copy.py`:
```python
import unittest
from pathlib import Path

import factory_copy as fc


class CopyTest(unittest.TestCase):
    def test_copy_is_separate_and_has_art(self):
        self.assertNotIn(fc.LIVE.resolve(), [fc.COPY, *fc.COPY.parents])
        types = (fc.DASHBOARD / 'factory_dashboard/workflow_types.py').read_text()
        self.assertIn("'art'", types)
        self.assertTrue((fc.DASHBOARD / 'integrations/hermes_factory_models/plugin.yaml').is_file())


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 3: Run it**

Run: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_*.py' -v`
Expected: 1 test OK.

### Task 11: Capabilities, audio type and Game Audio preset

**Files:**
- Modify in the copy: `factory-dashboard/factory_dashboard/workflow_types.py`, `factory-dashboard/factory_dashboard/workflow_templates.py`
- Test: `tests/factory_audio_type/test_workflow_types.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest

import factory_copy  # noqa: F401
from factory_dashboard import workflow_types as wt
from factory_dashboard.workflow_templates import _preset

AUDIO = ('audio-director', 'sound-designer', 'audio-reviewer')


class AudioTypeTest(unittest.TestCase):
    def test_capabilities(self):
        self.assertEqual(wt.CAPABILITIES['audio-director'], ('prepare',))
        self.assertEqual(wt.CAPABILITIES['sound-designer'], ('implement', 'repair'))
        self.assertEqual(wt.CAPABILITIES['audio-reviewer'], ('review',))
        self.assertEqual(wt.TASK_TYPES, ('feature', 'bug', 'chore', 'art', 'audio'))

    def test_preset(self):
        doc = _preset('audio')
        self.assertEqual(doc['name'], 'Game Audio')
        self.assertEqual(doc['prepare']['profile'], 'audio-director')
        self.assertEqual(doc['implement']['profile'], 'sound-designer')
        self.assertEqual(doc['repair']['profile'], 'sound-designer')
        self.assertEqual([r['profile'] for r in doc['reviewers']], ['audio-reviewer', 'claude-reviewer'])
        self.assertEqual(doc['verify']['profile'], 'verifier')
        self.assertEqual(doc['max_repairs'], 2)
        self.assertIn('audio_lint.py', doc['verify']['instructions'])
        self.assertIn('--fail-on-blocking', doc['implement']['instructions'])
        self.assertIn('--check-bible', doc['prepare']['instructions'])

    def test_preset_validates(self):
        for kind in wt.TASK_TYPES:
            wt.validate_document(_preset(kind)) if hasattr(wt, 'validate_document') else None
        from factory_dashboard.workflow_templates import WorkflowTemplates
        self.assertTrue(hasattr(WorkflowTemplates, 'save'))

    def test_art_unchanged(self):
        art = _preset('art')
        self.assertEqual(art['name'], 'Game Art')
        self.assertEqual(art['implement']['profile'], 'artist')
        self.assertEqual(art['max_repairs'], 2)
        self.assertEqual(_preset('feature')['max_repairs'], 3)


if __name__ == '__main__':
    unittest.main()
```

`test_preset_validates` must use the copy's actual validator. Before writing it, run `grep -n "^def \|ConfigurationError" <copy>/factory-dashboard/factory_dashboard/workflow_types.py`. Then call the function that `tests/factory_art_type/test_workflow_types.py` calls for the art preset. Replace the `hasattr` lines with that call, plus an `assertRaises(ConfigurationError)` for an audio preset whose implement profile is changed to `audio-reviewer`.

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_workflow_types.py' -v`
Expected: FAIL (`KeyError: 'audio-director'`).

- [ ] **Step 3: Edit the copy**

In `workflow_types.py`:
```python
    'art-director': ('prepare',), 'artist': ('implement', 'repair'), 'art-reviewer': ('review',),
    'audio-director': ('prepare',), 'sound-designer': ('implement', 'repair'), 'audio-reviewer': ('review',),
}
TASK_TYPES = ('feature', 'bug', 'chore', 'art', 'audio')
```

In `workflow_templates.py`, after the `GAME_ART` dict add:
```python
AUDIO_LINT = "audio_lint.py from the audio-review skill (the skill's LINT line gives its absolute path)"
GAME_AUDIO = {
    'description': 'Audio Director plans, Sound Designer synthesizes WAV effects or processes your Suno files into OGG music, audio-reviewer and claude-reviewer review, verifier runs the audio lint gate.',
    'prepare': ('Plan game audio as the audio-director SOUL says. First check the sound bible: python3 <audio_lint.py> <PROJECT_DIR> --check-bible, where audio_lint.py is ' + AUDIO_LINT + '. '
                'If it exits 1 and the prompt does not ask for a sound bible, complete VERDICT=BLOCKED with blocked_reason "no approved sound bible: submit an Audio task asking for a sound bible". '
                'Otherwise record audio_task: style|sfx|music-cues|music-import in PLAN.md, one AC per asset or cue plus "audio_lint reports no BLOCKER or HIGH" (not for style or music-cues), and the include list from the SOUL. '
                'For every task except style run python3 <audio_lint.py> <PROJECT_DIR> --style-hash and record style_sha256: <hex> in PLAN.md.'),
    'implement': ('Make the planned audio with the audio-production skill (sound-designer SOUL). Before completing run the audio lint gate: python3 <audio_lint.py> <PROJECT_DIR> <changed audio paths> --out <PROJECT_DIR>/.factory/tmp/audio-lint --fail-on-blocking, where audio_lint.py is ' + AUDIO_LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one. '
                  'Record it in checks_run, and assets and missing in metadata. Never write audio/style/ outside a style task, never write audio/incoming/.'),
    'repair': 'Change only the recipes or processing of the assets named in SCOPE findings with the audio-production skill, never audio/style/ outside a style task and never audio/incoming/, and rerun the audio lint gate (with --expect-style-hash when PLAN.md records style_sha256) before completing.',
    'verify': ('Run the audio lint gate on the frozen copy as a required check: python3 <audio_lint.py> <src_dir> --out "$HERMES_KANBAN_WORKSPACE/audio-lint" --fail-on-blocking, where audio_lint.py is ' + AUDIO_LINT + ', adding --expect-style-hash <style_sha256 from PLAN.md> when PLAN.md records one. '
               'Exit 1 means a BLOCKER or HIGH lint finding: record the command in failed_checks and fail the AC it threatens. ffmpeg missing makes affected ACs unverified:environment. Missing Suno files listed under missing are not failures. Attach audio-lint/lint.json.'),
    'claude-reviewer': 'Review the changed recipes, cue sheets, audio.json and any engine import settings for correctness and consistency with PLAN.md. Do not judge how it sounds; audio-reviewer does that.',
    'audio-reviewer': 'Follow the audio-review skill in factory mode.',
}
```

In `_preset`:
- Add `'audio': ('audio-director', 'sound-designer', ('audio-reviewer', 'claude-reviewer')),` to the profile map.
- Add `'audio': GAME_AUDIO['prepare']` to `instructions`.
- Change the remaining lines as follows:
```python
    notes = {'art': GAME_ART, 'audio': GAME_AUDIO}.get(kind, {})
    writer = {'art': 'artist', 'audio': 'sound-designer'}.get(kind, 'fixer')
    return dict(template_id=str(uuid.uuid4()), revision=1, name={'feature':'Feature', 'bug':'Bug fix', 'chore':'Chore', 'art':'Game Art', 'audio':'Game Audio'}[kind], description=notes.get('description', ''), task_type=kind,
                prepare=stage('prepare', prepare, instructions[kind]), implement=stage('implement', implement, notes.get('implement', '')),
                reviewers=[stage(p, p, notes.get(p, ''), stage_kind='review') for p in reviewers], verify=stage('verify', 'verifier', notes.get('verify', '')),
                repair=stage('repair', writer, notes.get('repair', '')), max_repairs=2 if kind in ('art', 'audio') else 3)
```

- [ ] **Step 4: Run the audio and art suites against the copy**

Run: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_*.py' -v`
Then run: `HERMES_GAME_ART_COPY=$PWD/artifacts/game-audio-2026-11-06/build python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py'`
Expected: both OK. If an art test asserts that `TASK_TYPES` equals exactly the four types, that is the only art test allowed to fail. Report it, and do not edit it.

### Task 12: Every enumeration, ticket, intake and publish

**Files:**
- Modify in the copy:
  - `factory-dashboard/factory_dashboard/assets/workflow_forms.js:38`
  - `factory-dashboard/factory_dashboard/assets/task_forms.js:43`
  - `scripts/factory_lib.py:156`
  - `scripts/factory_ticket.py:12`
  - `scripts/factory_intake.py:91`
  - `scripts/factory_publish.py:172`
  - `factory-skills/orchestrator/software-factory/SKILL.md` (the TYPE list that names `art`)
- Test: `tests/factory_audio_type/test_enumerations.py`, `tests/factory_audio_type/test_scripts.py`

- [ ] **Step 1: Write the failing tests**

`tests/factory_audio_type/test_enumerations.py`:
```python
import re
import unittest

import factory_copy as fc

FILES = {
    fc.DASHBOARD / 'factory_dashboard/assets/workflow_forms.js': "['feature','bug','chore','art','audio']",
    fc.DASHBOARD / 'factory_dashboard/assets/task_forms.js': "['feature','bug','chore','art','audio']",
    fc.SCRIPTS / 'factory_lib.py': '{"feature", "bug", "chore", "art", "audio"}',
    fc.SCRIPTS / 'factory_ticket.py': 'choices=["feature", "bug", "chore", "art", "audio"]',
    fc.SCRIPTS / 'factory_intake.py': '"art": "art", "audio": "audio"',
    fc.SCRIPTS / 'factory_publish.py': '"art": "feat(art)", "audio": "feat(audio)"',
}


class EnumerationTest(unittest.TestCase):
    def test_every_enumeration_has_audio(self):
        for path, needle in FILES.items():
            self.assertIn(needle, path.read_text(), path)

    def test_software_factory_skill_names_audio(self):
        text = (fc.SKILLS / 'orchestrator/software-factory/SKILL.md').read_text()
        self.assertRegex(text, r'art\|audio|art, audio|`audio`')

    def test_no_other_art_only_enumeration_left(self):
        for root in (fc.DASHBOARD / 'factory_dashboard', fc.SCRIPTS):
            for path in root.rglob('*'):
                if path.suffix in ('.py', '.js') and '__pycache__' not in path.parts and 'tests' not in path.parts:
                    for line in path.read_text(errors='replace').splitlines():
                        if re.search(r"""['"]chore['"]\s*,\s*['"]art['"]""", line):
                            self.assertIn('audio', line, f'{path}: {line.strip()}')


if __name__ == '__main__':
    unittest.main()
```

`tests/factory_audio_type/test_scripts.py`: copy `tests/factory_art_type/test_scripts.py` and change it to import `factory_copy` from this folder. For each test that exercises `--type art`, branch `art/<slug>` or the commit type `feat(art)`, add a matching audio test that expects `--type audio`, branch `audio/<slug>` and `feat(audio): ...`. Before adapting it, read `tests/factory_art_type/test_scripts.py` (77 lines) in full. The audio tests call the same helpers with `'audio'`.

- [ ] **Step 2: Run them to verify they fail**

Run: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_[es]*.py' -v`
Expected: FAIL in each enumeration assertion.

- [ ] **Step 3: Edit the copy**

- `workflow_forms.js:38` and `task_forms.js:43`: change `['feature','bug','chore','art']` to `['feature','bug','chore','art','audio']`.
- `factory_lib.py:156`: change the set to `{"feature", "bug", "chore", "art", "audio"}`.
- `factory_ticket.py:12`: change the choices to `choices=["feature", "bug", "chore", "art", "audio"]`.
- `factory_intake.py:91`: change the map to `{"bug": "fix", "chore": "chore", "art": "art", "audio": "audio"}`.
- `factory_publish.py:172`: change the map to `{"bug": "fix", "chore": "chore", "art": "feat(art)", "audio": "feat(audio)"}`. Then check with `grep -n "feat(art)" factory_publish.py` that the title regex the art patch widened also accepts `feat(audio)`. Widen it the same way if it doesn't.
- `software-factory/SKILL.md`: find the line the art patch changed (`grep -n "art" artifacts/game-art-2026-10-26/software-factory.patch`) and add `audio` next to `art` in the same form.

- [ ] **Step 4: Run both suites**

Run the audio suite and the art suite on this copy, as in Task 11 Step 4.
Expected: OK.

### Task 13: Audio migration and rollback

**Files:**
- Create: `factory_game_audio/__init__.py`, `factory_game_audio/migration.py`, `scripts/migrate_game_audio.py`
- Test: `tests/factory_audio_type/test_migration.py`

- [ ] **Step 1: The spec and CLI**

`factory_game_audio/__init__.py`: `"""Game Audio spec for the generic Factory type migration."""`

`factory_game_audio/migration.py`:
```python
"""Game Audio roles, catalog entries, template and audio type default over factory_type_migration."""
from factory_type_migration import migration as _m
from factory_type_migration.migration import TypeSpec, write_receipt  # noqa: F401

NEW_ROLES = {
    'audio-director': {'provider': 'anthropic', 'model': 'claude-opus-5-5', 'effort': 'high'},
    'sound-designer': {'provider': 'openai-codex', 'model': 'gpt-6-luna', 'effort': 'medium'},
    'audio-reviewer': {'provider': 'anthropic', 'model': 'claude-sonnet-5-5', 'effort': 'high'},
}
CHOICES_FROM = {'audio-director': 'architect', 'sound-designer': 'developer', 'audio-reviewer': 'verifier'}
SPEC = TypeSpec('audio', 'Game Audio', NEW_ROLES, CHOICES_FROM, 'factory-game-audio')


class Migration(_m.Migration):
    def __init__(self, dashboard_source, settings_db, catalog_path):
        super().__init__(SPEC, dashboard_source, settings_db, catalog_path)
```

`scripts/migrate_game_audio.py`: start from `scripts/migrate_game_art.py` and make these changes:
- the import becomes `from factory_game_audio.migration import Migration, write_receipt`;
- the docstring and every help text say "Game Audio" or "audio" instead of "Game Art" or "art";
- the error prefix becomes `migrate_game_audio:`.

The flags stay exactly as they are.

- [ ] **Step 2: Write the test**

Read `tests/factory_art_type/test_migration.py` (197 lines) and copy it to `tests/factory_audio_type/test_migration.py`. In the copy:
- `factory_game_art` becomes `factory_game_audio`;
- `migrate_game_art.py` becomes `migrate_game_audio.py`;
- the role names become the three audio roles;
- `'art'` becomes `'audio'` and `Game Art` becomes `Game Audio`;
- the receipt schema becomes `factory-game-audio-migration/v1`.

Then add these tests:
```python
    def test_audio_after_art_keeps_art(self):
        """Running the art migration, then the audio migration, leaves both type defaults and both templates active."""
        # Use the same store-building helper the art test file uses (setUp builds a store from the copy).
        from factory_game_art.migration import Migration as ArtMigration
        ArtMigration(fc.DASHBOARD, self.db, self.catalog).apply()
        receipt = self.migration().apply()
        mapping = self.migration().templates.defaults()['templates']
        self.assertIn('art', mapping)
        self.assertEqual(mapping['audio'], receipt['template_created'])

    def test_audio_purge_leaves_art_rows(self):
        from factory_game_art.migration import Migration as ArtMigration
        ArtMigration(fc.DASHBOARD, self.db, self.catalog).apply()
        self.migration().apply()
        result = self.migration().rollback(purge=True)
        names = {d['name'] for d in self.migration().templates.list()}
        self.assertIn('Game Art', names)
        self.assertNotIn('Game Audio', names)
        self.assertEqual(len(result['purged']), 1)
```

Name `self.migration()`, `self.db` and `self.catalog` after whatever the copied `setUp` uses.

- [ ] **Step 3: Run it**

Run: `python3 -m unittest discover -s tests/factory_audio_type -p 'test_migration.py' -v`
Expected: all OK. Also re-run `tests/factory_art_type` on the art copy (the default env), which must still pass.

### Task 14: Bundle, install checker, full Part B run and patches

**Files:**
- Create: `scripts/check_game_audio_install.py`, `tests/factory_audio_type/test_bundle.py`, `tests/factory_audio_type/test_check_install.py`, and three patches in `artifacts/game-audio-2026-11-06/`

- [ ] **Step 1: Bundle test**

Copy `tests/factory_art_type/test_bundle.py` (29 lines) to `tests/factory_audio_type/test_bundle.py` and import this folder's `factory_copy`. Add an assertion that the bundled `workflow_types.py` contains `'audio-director'`.

- [ ] **Step 2: The checker**

Write `scripts/check_game_audio_install.py` as a parameterized copy of `scripts/check_game_art_install.py` (128 lines). Read it in full first, then change:
- `ART_PROFILES` → `AUDIO_PROFILES = ('audio-director', 'sound-designer', 'audio-reviewer')`;
- `STAGES` → `{'prepare': ('audio-director', 'scratch'), 'implement': ('sound-designer', 'dir'), 'repair': ('sound-designer', 'dir'), 'audio-reviewer': ('audio-reviewer', 'scratch'), 'claude-reviewer': ('claude-reviewer', 'scratch'), 'verify': ('verifier', 'scratch')}`;
- the captured task type becomes `'audio'` and the template name becomes `'Game Audio'`;
- the skills checked become `audio-review/SKILL.md`, `audio-review/scripts/audio_lint.py`, `audio-production/SKILL.md` and `audio-production/scripts/sfx_synth.py`;
- the art check in the checker also confirms that `art` is still a type default.

The profile model check expects:
- `audio-director`: anthropic / claude-opus-5-5;
- `sound-designer`: openai-codex / gpt-6-luna;
- `audio-reviewer`: anthropic / claude-sonnet-5-5.

`tests/factory_audio_type/test_check_install.py`: copy `tests/factory_art_type/test_check_install.py` (88 lines) and change it the same way. Keep its fake Hermes home layout. It must also assert that a home missing `audio-review/SKILL.md` reports exactly that problem.

- [ ] **Step 3: Full Part B run**

Run:
```sh
python3 -m unittest discover -s tests/factory_audio_type -p 'test_*.py' -v
HERMES_GAME_ART_COPY=$PWD/artifacts/game-audio-2026-11-06/build python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py'
python3 -m unittest discover -s tests/factory_art_type -p 'test_*.py'
python3 -m unittest discover -s tests/audio -p 'test_*.py'
```
Expected: all OK.

- [ ] **Step 4: Check the baseline, then write the patches**

```sh
A=artifacts/game-audio-2026-11-06
cd ~/.hermes && shasum -a 256 -c "/Users/example/orca/projects/hermes/$A/baseline.sha256" --quiet && echo LIVE-UNCHANGED
cd /Users/example/orca/projects/hermes
diff -ruN -x __pycache__ -x integrations ~/.hermes/factory-dashboard "$A/build/factory-dashboard" > "$A/factory-dashboard.patch"
diff -ruN -x __pycache__ -x tests ~/.hermes/scripts "$A/build/scripts" > "$A/scripts.patch"
diff -ruN ~/.hermes/factory-skills/orchestrator/software-factory "$A/build/factory-skills/orchestrator/software-factory" > "$A/software-factory.patch"
grep -c '^+++' "$A"/*.patch
```
Expected: `LIVE-UNCHANGED`. The patches touch only the 9 files in the file-structure list. If the live files changed since Task 10, stop and tell the user. Do not rebuild over their edits.

---

# Part C: live rollout (every step ASK THE USER FIRST unless marked read-only)

Use the art rollout's Tasks 14–21 (`docs/superpowers/plans/2026-10-26-game-art-factory.md:3247-3560`) as the step-by-step reference. Below are the exact audio commands. Before every `hermes` command, check `tail -3 ~/.hermes/logs/update.log`. After it, run `hermes gateway status`.

### Task 15: Preflight (read-only)

- [ ] Run the commands below and confirm all of the following:
  - the gateway is running;
  - the dashboard answers on port 4610;
  - no kanban task is `running`;
  - the baseline still matches;
  - `check_game_art_install.py` reports `ok: true`.

```sh
hermes gateway status; curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:4610/
sqlite3 ~/.hermes/kanban.db "select status, count(*) from tasks group by status"
(cd ~/.hermes && shasum -a 256 -c /Users/example/orca/projects/hermes/artifacts/game-audio-2026-11-06/baseline.sha256 --quiet) && echo OK
python3 scripts/check_game_art_install.py
```

Use the table and column names that art Task 14 used for the kanban query.

### Task 16: Pause, stop the dashboard, back up (ASK THE USER FIRST)

```sh
hermes pause
pkill -f serve_factory_dashboard.py
B=~/.hermes/backups/game-audio-$(date +%Y%m%d-%H%M%S); mkdir -m 700 "$B"
cd ~/.hermes && tar czf "$B/hermes-parts.tgz" factory-dashboard plugins/factory-models config.yaml state/factory \
  factory-skills profiles/architect profiles/developer profiles/art-reviewer $(ls -d profiles/*/plugins/factory-models)
echo "$B" > /Users/example/orca/projects/hermes/artifacts/game-audio-2026-11-06/backup-path.txt
```

### Task 17: Install the source edits and the skills (ASK THE USER FIRST)

```sh
A=/Users/example/orca/projects/hermes/artifacts/game-audio-2026-11-06
cd ~/.hermes
patch -p0 --dry-run -d / < "$A/factory-dashboard.patch" && patch -p0 -d / < "$A/factory-dashboard.patch"
patch -p0 --dry-run -d / < "$A/scripts.patch" && patch -p0 -d / < "$A/scripts.patch"
patch -p0 --dry-run -d / < "$A/software-factory.patch" && patch -p0 -d / < "$A/software-factory.patch"
cd /Users/example/orca/projects/hermes && sh scripts/install_audio_review.sh && sh scripts/install_audio_production.sh
```

If `patch -d /` cannot apply the absolute-path headers, use what art Task 16 did instead: copy each changed file from the build to the matching live path, with the file list taken from `grep '^+++' "$A"/*.patch`.

### Task 18: Migration on the live store (ASK THE USER FIRST)

```sh
S=~/.hermes/state/factory
python3 scripts/migrate_game_audio.py --dashboard-source ~/.hermes/factory-dashboard --settings-db $S/task-settings.db --catalog $S/model-catalog.json --dry-run
python3 scripts/migrate_game_audio.py --dashboard-source ~/.hermes/factory-dashboard --settings-db $S/task-settings.db --catalog $S/model-catalog.json --apply --receipt artifacts/game-audio-2026-11-06/migration-receipt.json
```

Expected from the dry run: three roles to add, `template: null`, `type_default: null`.

### Task 19: Rebundle and swap the plugin in every home (ASK THE USER FIRST)

Follow art Task 18 exactly. Bundle from `~/.hermes/factory-dashboard` with `scripts/bundle_factory_plugin.py`, then replace `~/.hermes/plugins/factory-models` and every `~/.hermes/profiles/*/plugins/factory-models` copy, checking each with `diff -r`.

### Task 20: Profiles and roster (ASK THE USER FIRST)

```sh
hermes profile create audio-director --clone-from architect --no-alias --description "Audio Director: plans game sound effects and music cues against the repo sound bible."
hermes profile create sound-designer --clone-from developer --no-alias --description "Sound Designer: synthesizes sound effects and processes Suno music into game-ready OGG."
hermes profile create audio-reviewer --clone-from art-reviewer --no-alias --description "Independent audio reviewer: measures sound effects and music against the repo sound bible."
P=~/.hermes/factory-skills/worker
cp $P/audio-production/souls/audio-director.SOUL.md ~/.hermes/profiles/audio-director/SOUL.md
cp $P/audio-production/souls/sound-designer.SOUL.md ~/.hermes/profiles/sound-designer/SOUL.md
cp $P/audio-review/SOUL.md ~/.hermes/profiles/audio-reviewer/SOUL.md
```

Then edit each new profile's `config.yaml` the way art Task 19 did, by line edits on the `model:` block. Never read `.env` or `auth.json`.
- `audio-director`: `provider: anthropic`, `default: claude-opus-5-5`.
- `sound-designer`: `provider: openai-codex`, `default: gpt-6-luna`.
- `audio-reviewer`: keep its Sonnet model.
- Remove the vision toolset if the clone source had one. audio-reviewer keeps vision for the waveform pictures.
- Check `plugins.enabled` includes `hermes_otel` and `factory-models`, and `dispatch_in_gateway: false`.
- `audio-reviewer` was cloned from `art-reviewer`: delete any `auth.json.copilot-unused` and `config.yaml.pre-model` that got copied into its home, after confirming by name only.

Add the three names under `kanban.dispatch_profiles` in `~/.hermes/config.yaml`, after `art-reviewer`.

### Task 21: Restart and release (ASK THE USER FIRST)

```sh
hermes gateway run   # detached as before; then hermes gateway status
nohup sh /Users/example/orca/projects/hermes/artifacts/game-art-2026-10-26/start_dashboard.sh >> ~/.hermes/logs/factory-dashboard.log 2>&1 &
hermes resume
```

### Task 22: Verify without launching workers (read-only)

```sh
python3 scripts/check_game_audio_install.py
python3 scripts/check_game_art_install.py
curl -s http://127.0.0.1:4610/ -o /dev/null -w '%{http_code}\n'
```

Expected: both checkers report `"ok": true, "problems": []`, and the dashboard returns 200.

### Task 23: End-to-end runs (ASK THE USER FIRST; uses model time only)

1. `python3 scripts/make_audio_sample.py ~/orca/projects/audio-sample`.
2. Submit an Audio task on it: "Make UI click, coin pickup and jump sound effects." Expect `audio_task: sfx`, three WAVs, a clean lint and a delivery.
3. Submit an Audio task: "Write music cues for the title screen and the first level, looping, chiptune." Expect two cue sheets and a delivery that tells the user the incoming file names.
4. After the user saves one Suno file into `audio/incoming/`, submit an Audio task: "Import the Suno music." Expect one OGG, the other cue under `missing`, and a clean lint.

### Task 24: Results and rollback documentation

Write `docs/game-audio-factory-results.md` with:
- the test counts;
- the backup path and the migration receipt;
- what each end-to-end run produced;
- any deviations.

Include the rollback:
1. `migrate_game_audio.py --rollback --receipt …`, plus `--purge-template` only if no Audio task ran.
2. Restore `hermes-parts.tgz` from the backup.
3. Restart the gateway and the dashboard.

---

## Self-review against the spec

- **Bible:** Task 2. The stereo-OGG constraint comes from decision 1.
- **Profiles:** Task 20. Models: Task 13 roles. Capabilities: Task 11.
- **Task kinds:**
  - style, sfx, music-cues and music-import are defined in the audio-director soul and the Game Audio prepare instructions (Tasks 8 and 11);
  - production steps are in the sound-designer skill (Task 8);
  - `missing` is not a failure (verify instructions, Task 11).
- **Synthesizer:** Task 6, every listed recipe key. Music processing (trim, loop at a zero crossing on a bar boundary, crossfade, loudnorm, OGG): Task 7.
- **Lint:**
  - format, duration, peak, clipping, loudness (MEDIUM/HIGH), silence, loop seam, DC offset, unclassified and stale cue: Task 5;
  - pictures: Task 4;
  - `--fail-on-blocking`, `--check-bible`, `--style-hash`, `--expect-style-hash`: Task 5.
- **Reviewer:** judges measures and recipes, finding caps, `audio_surface: none` (Task 8 skill).
- **Type and template:** `audio` in every enumeration (Task 12), preset and capability (Task 11), any template may use `audio-reviewer` (review capability), migration and rollback (Tasks 9 and 13).
- **Rollout and safety:** Tasks 15–22. Rollback: Task 24.
- **Validation:** unit tests across Tasks 1–14, install checker (Task 14), end-to-end runs (Task 23).
- **Out of scope:** nothing in the plan generates Suno audio automatically, handles voice, or judges sound by listening.
