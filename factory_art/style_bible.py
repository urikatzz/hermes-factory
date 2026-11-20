"""Load and validate a repo's art/style bible, and match files to its asset classes."""
import hashlib
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
RULE_LINE = re.compile(r'^[\s#>*-]*\**([SLT]\d+)\b\**\s*(?:\(([^)\n]*)\))?', re.M)
BLOCKING = re.compile(r'\bblocking\b', re.I)


class BibleError(ValueError):
    pass


def parse_rules(text):
    rules = {}
    for match in RULE_LINE.finditer(text):
        if match.group(1) in rules:
            raise BibleError(f'STYLE.md: rule {match.group(1)} is defined twice')
        rules[match.group(1)] = bool(match.group(2) and BLOCKING.search(match.group(2)))  # "(blocking)" and "(blocking, V1)" both block
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
    rules = parse_rules(_read(style_dir / 'STYLE.md'))
    try:
        data = json.loads(_read(style_dir / 'style.json'))
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
        elif 'tolerance' in palette and not (_count(palette['tolerance']) or _zero(palette['tolerance'])):
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


def _read(path):
    try:
        return path.read_text(encoding='utf-8')
    except UnicodeDecodeError as error:
        raise BibleError(f'{STYLE_DIR}/{path.name} is not valid UTF-8: {error}') from error


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _count(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _zero(value):
    return type(value) is int and value == 0


def _range(value):
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value) and value[0] <= value[1])


def _inside(style_dir, ref):
    path = (style_dir / ref).resolve()
    return path.is_file() and path.is_relative_to(style_dir.resolve())


def style_hash(repo):
    """sha256 over the sorted relative paths and bytes of every file under art/style (empty when it is missing)."""
    style_dir = Path(repo) / STYLE_DIR
    digest = hashlib.sha256()
    files = sorted(path for path in style_dir.rglob('*') if path.is_file()) if style_dir.is_dir() else []
    for path in sorted(files, key=lambda path: path.relative_to(style_dir).as_posix()):
        data = path.read_bytes()
        digest.update(path.relative_to(style_dir).as_posix().encode() + b'\0')
        digest.update(len(data).to_bytes(8, 'big') + data)
    return digest.hexdigest()
