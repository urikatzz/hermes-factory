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
                for image in bpy.data.images if image.type == 'IMAGE' and image.size[0] > 0]
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
