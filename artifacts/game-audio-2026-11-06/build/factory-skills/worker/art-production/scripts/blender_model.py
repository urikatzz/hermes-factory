"""Run inside Blender through blender_run.sh.

  cleanup <in.glb> <out.glb> --height <m> [--origin bottom_center|center]
  blockout <concept.png> <out.glb> --height <m> --spec <parts.json> [--palette <file.gpl>] [--origin ...]

Both bake every transform into one mesh, scale it to --height (Blender Z), set the origin, triangulate and export
GLB. blockout first builds primitives from a JSON spec: {"parts": [{"shape": "cube|cylinder|sphere|cone",
"location": [x, y, z], "size": [x, y, z], "rotation": [deg, deg, deg], "colour": "#rrggbb" or "sample": [u, v]}]}
where sample reads the concept image at u (left to right) and v (top to bottom), both 0..1, and --palette snaps
every colour to the nearest palette entry. Prints 'BLENDER_MODEL {json}', or 'BLENDER_MODEL_ERROR ...' and exit 1.
"""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import traceback

import bmesh
import bpy
from mathutils import Matrix, Vector

SHAPES = {
    'cube': lambda: bpy.ops.mesh.primitive_cube_add(size=1),
    'cylinder': lambda: bpy.ops.mesh.primitive_cylinder_add(vertices=12, radius=0.5, depth=1),
    'sphere': lambda: bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=6, radius=0.5),
    'cone': lambda: bpy.ops.mesh.primitive_cone_add(vertices=12, radius1=0.5, radius2=0, depth=1),
}
MAX_PARTS = 64


def reset():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj)
    for mesh in list(bpy.data.meshes):
        bpy.data.meshes.remove(mesh)
    for material in list(bpy.data.materials):
        bpy.data.materials.remove(material)


def import_model(path):
    suffix = Path(path).suffix.lower()
    if suffix in ('.glb', '.gltf'):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif suffix == '.fbx':
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif suffix == '.obj':
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        raise ValueError(f'unsupported model format {suffix}')


def select_only(objects):
    for obj in bpy.context.view_layer.objects:
        obj.select_set(obj in objects)
    bpy.context.view_layer.objects.active = objects[0]


def bake_and_join(meshes):
    """Apply every object (and parent) transform into its own mesh data, drop other objects, join into one."""
    for obj in meshes:
        matrix = obj.matrix_world.copy()
        obj.data = obj.data.copy()
        obj.data.transform(matrix)
    for obj in meshes:
        obj.parent = None
        obj.matrix_world = Matrix.Identity(4)
    for obj in [o for o in bpy.context.scene.objects if o.type != 'MESH']:
        bpy.data.objects.remove(obj)
    select_only(meshes)
    if len(meshes) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


def finish(obj, height, origin, out):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    bm.to_mesh(obj.data)
    bm.free()
    coords = [vertex.co.copy() for vertex in obj.data.vertices]
    if not coords:
        raise ValueError('model has no vertices')
    low = Vector([min(c[i] for c in coords) for i in range(3)])
    high = Vector([max(c[i] for c in coords) for i in range(3)])
    if high.z - low.z <= 1e-6:
        raise ValueError('model has no height')
    scale = height / (high.z - low.z)
    anchor = Vector(((low.x + high.x) / 2, (low.y + high.y) / 2,
                     low.z if origin == 'bottom_center' else (low.z + high.z) / 2))
    obj.data.transform(Matrix.Scale(scale, 4) @ Matrix.Translation(-anchor))
    obj.data.update()
    obj.location = (0.0, 0.0, 0.0)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    select_only([obj])
    bpy.ops.export_scene.gltf(filepath=str(out), export_format='GLB', use_selection=True)
    return {'out': str(out), 'triangles': len(obj.data.polygons),
            'materials': len({slot.material.name for slot in obj.material_slots if slot.material}),
            'height_m': round(height, 4), 'origin': origin}


def cleanup(args):
    import_model(args.source)
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not meshes:
        raise ValueError('no mesh objects after import')
    return finish(bake_and_join(meshes), args.height, args.origin, args.out)


def load_palette(path):
    colours = []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and all(part.isdigit() for part in parts[:3]):
            colours.append(tuple(int(part) for part in parts[:3]))
    if not colours:
        raise ValueError(f'{path} has no colours')
    return colours


def sample(image, u, v):
    width, height = image.size
    x = min(width - 1, max(0, int(u * width)))
    y = min(height - 1, max(0, int((1 - v) * height)))  # Blender rows start at the bottom
    index = (y * width + x) * 4
    return tuple(round(channel * 255) for channel in image.pixels[index:index + 3])


def numbers(part, key, default=None, positive=False):
    value = part.get(key, default)
    if (not isinstance(value, list) or len(value) != 3
            or not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)
            or (positive and min(value) <= 0)):
        raise ValueError(f'part {key} must be three {"positive " if positive else ""}numbers')
    return [float(v) for v in value]


def colour_of(part, image, palette):
    if isinstance(part.get('colour'), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', part['colour']):
        colour = tuple(int(part['colour'][i:i + 2], 16) for i in (1, 3, 5))
    elif isinstance(part.get('sample'), list) and len(part['sample']) == 2 and all(
            isinstance(v, (int, float)) and 0 <= v <= 1 for v in part['sample']):
        colour = sample(image, *part['sample'])
    else:
        raise ValueError('each part needs "colour": "#rrggbb" or "sample": [u, v] with values 0..1')
    if palette:
        colour = min(palette, key=lambda entry: sum((a - b) ** 2 for a, b in zip(colour, entry)))
    return colour


def linear(channel):
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def material_for(colour, cache):
    if colour not in cache:
        material = bpy.data.materials.new('c%02x%02x%02x' % colour)
        material.use_nodes = True
        rgba = (*[linear(c) for c in colour], 1.0)
        material.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = rgba
        material.diffuse_color = rgba
        cache[colour] = material
    return cache[colour]


def check_shape(part):
    if not isinstance(part, dict) or part.get('shape') not in SHAPES:
        raise ValueError(f'part shape must be one of {", ".join(SHAPES)}')
    return part


def add_part(part, material):
    location, size = numbers(part, 'location'), numbers(part, 'size', positive=True)
    rotation = [math.radians(a) for a in numbers(part, 'rotation', [0, 0, 0])]
    SHAPES[part['shape']]()
    obj = bpy.context.view_layer.objects.active
    obj.location, obj.rotation_euler, obj.scale = location, rotation, size
    obj.data.materials.append(material)
    return obj


def blockout(args):
    spec = json.loads(Path(args.spec).read_text())
    parts = spec.get('parts') if isinstance(spec, dict) else None
    if not isinstance(parts, list) or not 0 < len(parts) <= MAX_PARTS:
        raise ValueError(f'spec needs "parts": a list of 1 to {MAX_PARTS} primitives')
    image = bpy.data.images.load(str(Path(args.concept).resolve()))
    palette = load_palette(args.palette) if args.palette else None
    cache = {}
    meshes = [add_part(part, material_for(colour_of(check_shape(part), image, palette), cache)) for part in parts]
    result = finish(bake_and_join(meshes), args.height, args.origin, args.out)
    result.update(parts=len(parts), colours=['#%02x%02x%02x' % colour for colour in cache])
    return result


def parse(argv):
    parser = argparse.ArgumentParser(prog='blender_model.py')
    modes = parser.add_subparsers(dest='mode', required=True)
    clean = modes.add_parser('cleanup')
    clean.add_argument('source')
    clean.add_argument('out')
    block = modes.add_parser('blockout')
    block.add_argument('concept')
    block.add_argument('out')
    block.add_argument('--spec', required=True)
    block.add_argument('--palette')
    for mode in (clean, block):
        mode.add_argument('--height', type=float, required=True)
        mode.add_argument('--origin', choices=('bottom_center', 'center'), default='bottom_center')
    args = parser.parse_args(argv)
    if args.height <= 0:
        parser.error('--height must be positive')
    return args


if __name__ == '__main__':
    try:
        arguments = parse(sys.argv[sys.argv.index('--') + 1:])
        reset()
        outcome = cleanup(arguments) if arguments.mode == 'cleanup' else blockout(arguments)
    except Exception as error:
        print(f'BLENDER_MODEL_ERROR {type(error).__name__}: {error}', flush=True)
        traceback.print_exc()
        sys.exit(1)
    print('BLENDER_MODEL ' + json.dumps(outcome), flush=True)
