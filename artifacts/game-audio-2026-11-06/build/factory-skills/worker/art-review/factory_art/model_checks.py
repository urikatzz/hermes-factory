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
