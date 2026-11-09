"""Load a repo's audio/style bible: AUDIO.md numbered rules and audio.json asset classes."""
import fnmatch
import hashlib
import json
import os
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


def _in(value, allowed):
    return isinstance(value, (str, int)) and not isinstance(value, bool) and value in allowed


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
    if not _in(cls.get('kind'), KINDS):
        raise BibleError(f'class {name!r}: kind must be one of {sorted(KINDS)}')
    if not _in(cls.get('format'), FORMATS):
        raise BibleError(f'class {name!r}: format must be one of {sorted(FORMATS)}')
    if not (isinstance(cls.get('match'), list) and cls['match'] and all(isinstance(m, str) for m in cls['match'])):
        raise BibleError(f'class {name!r}: match must be a non-empty list of globs')
    if not _in(cls.get('sample_rate'), RATES):
        raise BibleError(f'class {name!r}: sample_rate must be one of {sorted(RATES)}')
    if not _in(cls.get('channels'), (1, 2)):
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
    if not (isinstance(cls.get('rules', []), list) and all(isinstance(r, str) for r in cls.get('rules', []))):
        raise BibleError(f'class {name!r}: rules must be a list of rule IDs')
    for rule in cls.get('rules', []):
        if rule not in rules:
            raise BibleError(f'class {name!r}: rule {rule} is not in AUDIO.md')


def load_bible(repo):
    style = Path(repo) / STYLE_DIR
    if style.is_symlink() or (style.is_dir() and any(p.is_symlink() for p in style.rglob('*'))):
        raise BibleError(f'{STYLE_DIR} must not contain a symlink')
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
        try:
            _check_class(cls, rules)
        except TypeError as error:  # any malformed value we did not anticipate
            raise BibleError(f"class {cls.get('name')!r}: malformed value: {error}") from None
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
        for file in sorted(style.rglob('*')):
            rel = file.relative_to(style).as_posix().encode()
            if file.is_symlink():
                digest.update(rel + b'\0->' + os.readlink(file).encode() + b'\0')
            elif file.is_file():
                digest.update(rel + b'\0' + file.read_bytes() + b'\0')
    return digest.hexdigest()
