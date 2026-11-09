"""Deterministic art lint: match files to style classes, measure them, prepare images for review."""
import json
import os
from pathlib import Path

from .blender_runner import BlenderUnavailable, render_model
from .findings import BLOCKING, finding, lines, ordered, override
from .model_checks import MODEL_EXTENSIONS, check_model
from .png import PngError, read_png
from .sprite_checks import check_sprite
from .style_bible import ART_EXTENSIONS, STYLE_DIR, BibleError, classify, is_art_file, load_bible, style_hash
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


def run_lint(repo, out, paths=(), blender=None, first=(), max_images=40, timeout=120, expect_style_hash=None):
    repo, out = Path(repo).resolve(), Path(out)
    files = collect(repo, paths)
    result = {'schema': 'factory-art-lint/v1', 'repo': str(repo), 'art_files': 0, 'images': 0, 'findings': [],
              'assets': [], 'not_reviewed': [], 'unverified': [], 'blocked_tools': [], 'warnings': []}
    if expect_style_hash and style_hash(repo) != expect_style_hash.lower():
        result['findings'].append(finding('BLOCKER', 'style', STYLE_DIR, f'{STYLE_DIR} changed during an asset task'))
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
    return rel.replace('_', '_u').replace('/', '__')


def _budget(result, first, max_images):
    priority = {path: index for index, path in enumerate(first)}
    assets = sorted(result['assets'], key=lambda asset: priority.get(asset['file'], len(priority)))
    used = 0
    for asset in assets:
        cost = len(asset['images']) + len(asset['references']) if asset['images'] else 0
        asset['vision'] = used + cost <= max_images
        if asset['vision']:
            used += cost
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
