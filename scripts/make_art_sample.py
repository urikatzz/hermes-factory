#!/usr/bin/env python3
"""Create a plain-folder sample game with an approved style bible for the paid Game Art rollout runs."""
import argparse
import json
from pathlib import Path

PALETTE = [(24, 20, 37), (38, 92, 66), (99, 199, 77), (254, 231, 97), (247, 118, 34), (190, 74, 47),
           (234, 212, 170), (90, 105, 136), (139, 155, 180), (255, 255, 255)]
STYLE = """# Sample game style

Cosy top-down fantasy, chunky readable shapes, limited palette.

**S1** (blocking) Every character and item reads clearly at 1x zoom against grass and stone.
**S2** Light comes from the top left; shadows fall to the bottom right.
**S3** Outlines are one pixel, using the darkest palette colour.
**S4** Props are simple, low-poly shapes with flat colours from the palette and no photographic textures.
"""
CLASSES = [
    {'name': 'item_sprite', 'kind': 'sprite', 'match': ['Assets/Art/Items/**'],
     'size': {'width': [32, 32], 'height': [32, 32]}, 'alpha': 'required', 'pixel_art': True,
     'palette': {'file': 'palette.gpl', 'tolerance': 0}, 'rules': ['S1', 'S2', 'S3']},
    {'name': 'prop_model', 'kind': 'model', 'match': ['Assets/Models/Props/**'], 'triangles_max': 3000,
     'materials_max': 4, 'texture_max_px': 512, 'height_m': [0.3, 1.5], 'origin': 'bottom_center',
     'rules': ['S2', 'S4']},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path, help='new or empty folder')
    folder = parser.parse_args().folder
    if folder.exists() and any(folder.iterdir()):
        parser.exit(1, f'make_art_sample: {folder} is not empty\n')
    style = folder / 'art/style'
    style.mkdir(parents=True)
    (style / 'STYLE.md').write_text(STYLE)
    (style / 'style.json').write_text(json.dumps({'version': 1, 'classes': CLASSES}, indent=2) + '\n')
    (style / 'palette.gpl').write_text('GIMP Palette\nName: sample\nColumns: 5\n#\n'
                                       + ''.join(f'{r} {g} {b}\tc{i}\n' for i, (r, g, b) in enumerate(PALETTE)))
    for path in ('Assets/Art/Items', 'Assets/Models/Props', 'art/concepts'):
        (folder / path).mkdir(parents=True)
        (folder / path / '.keep').write_text('')
    (folder / 'README.md').write_text('# Art sample\n\nSample game for Factory Game Art runs. The bible is in art/style.\n')
    print(folder.resolve())


if __name__ == '__main__':
    main()
