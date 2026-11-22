"""The scene layout contract (factory-scene-layout/v1) and the completeness check that keeps a preliminary composition from passing as the finished scene.

A layout is project data (an agent writes it from the plan); this module knows nothing about any game. `covers` on an object names the approved-reference
requirement ids that object supplies. Required ids that no object covers are `missing`: a scene with missing required elements can be scored, but only as a
preliminary composition test, never accepted."""
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'factory-scene-layout/v1'
ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')
REQUIREMENT = re.compile(r'[A-Z]{1,3}[0-9]{1,3}')
MAX_OBJECTS = 200


class LayoutError(ValueError):
    pass


def _numbers(value, count, what, minimum=None):
    if not isinstance(value, list) or len(value) not in (count, count + 1) or any(type(v) not in (int, float) or v != v or abs(v) > 1e6 for v in value):
        raise LayoutError(f'{what} must be a list of {count} finite numbers')
    return value


def validate_layout(layout, project_dir=None):
    """Returns the layout when it is usable, else raises LayoutError naming the problem. Asset paths must stay inside the project and exist when project_dir is given."""
    if not isinstance(layout, dict) or layout.get('schema') != SCHEMA:
        raise LayoutError('layout.schema must be ' + SCHEMA)
    scene = layout.get('scene')
    if not isinstance(scene, str) or not re.fullmatch(r'Assets/[A-Za-z0-9_./ -]+\.unity', scene) or '..' in scene.split('/'):
        raise LayoutError('layout.scene must be an Assets/*.unity path')
    camera = layout.get('camera')
    if not isinstance(camera, dict):
        raise LayoutError('layout.camera is required')
    for key in ('width', 'height'):
        if type(camera.get(key)) is not int or not 64 <= camera[key] <= 8192:
            raise LayoutError(f'camera.{key} must be an integer between 64 and 8192')
    if type(camera.get('size')) not in (int, float) or not 0 < camera['size'] <= 1e4:
        raise LayoutError('camera.size must be a positive number')
    if 'position' in camera:
        _numbers(camera['position'], 2, 'camera.position')
    if layout.get('lighting', 'unlit') not in ('unlit', 'project'):
        raise LayoutError('layout.lighting must be unlit (assets as authored) or project')
    objects = layout.get('objects')
    if not isinstance(objects, list) or not objects or len(objects) > MAX_OBJECTS:
        raise LayoutError('layout.objects must list 1..%d objects' % MAX_OBJECTS)
    seen = set()
    for item in objects:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not ID.fullmatch(item['id']) or item['id'] in seen:
            raise LayoutError('every object needs a unique id')
        seen.add(item['id'])
        asset = item.get('asset')
        if not isinstance(asset, str) or not asset.startswith('Assets/') or '..' in asset.split('/') or '\\' in asset:
            raise LayoutError(f'object {item["id"]}: asset must be an Assets/ path inside the project')
        if project_dir is not None and not (Path(project_dir) / asset).is_file():
            raise LayoutError(f'object {item["id"]}: asset does not exist: {asset}')
        _numbers(item.get('position', [0, 0, 0]), 2, f'object {item["id"]} position')
        if 'size_units' in item:
            _numbers(item['size_units'], 1, f'object {item["id"]} size_units')
        if 'pivot' in item:
            _numbers(item['pivot'], 2, f'object {item["id"]} pivot')
            if any(not 0 <= v <= 1 for v in item['pivot'][:2]):
                raise LayoutError(f'object {item["id"]}: pivot must be fractions of the sprite between 0 and 1 (for example [0.5, 0] for the feet)')
        covers = item.get('covers', [])
        if not isinstance(covers, list) or any(not isinstance(c, str) or not REQUIREMENT.fullmatch(c) for c in covers):
            raise LayoutError(f'object {item["id"]}: covers must list requirement ids such as V3')
    return layout


def completeness(layout, required, deferred=()):
    """{required, present, missing, deferred, final_acceptance_possible}. `required` is the approved reference's requirement ids that are not deferred by a human."""
    wanted = sorted(set(required) - set(deferred))
    present = sorted({c for o in layout['objects'] for c in o.get('covers', [])} & set(wanted))
    missing = [r for r in wanted if r not in present]
    return dict(required=wanted, present=present, missing=missing, deferred=sorted(set(deferred)), complete=not missing)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def load_layout(path, project_dir=None):
    try:
        data = Path(path).read_bytes()
        return validate_layout(json.loads(data), project_dir), sha256_bytes(data)
    except (OSError, ValueError) as error:
        raise LayoutError(f'cannot read layout: {error}') from error
