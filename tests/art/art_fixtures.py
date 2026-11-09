"""Build style bibles, sprites, models and a sample game repo for art tests."""
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from factory_art.png import Image, write_png

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
