#!/usr/bin/env python3
"""Fit a generated image to a sprite class: flat background to alpha, nearest-neighbour fit, palette quantize."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.sprite_fit import make_sprite
from factory_art.png import PngError, read_png, write_png
from factory_art.style_bible import load_palette


def size(text):
    match = re.fullmatch(r'(\d+)x(\d+)', text)
    if not match or not all(int(value) > 0 for value in match.groups()):
        raise argparse.ArgumentTypeError('use WIDTHxHEIGHT, for example 32x32')
    return int(match[1]), int(match[2])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='generated PNG')
    parser.add_argument('out', help='sprite PNG to write')
    parser.add_argument('--size', type=size, required=True, help='class size, WIDTHxHEIGHT')
    parser.add_argument('--palette', help='GIMP .gpl palette from art/style (quantize to it)')
    parser.add_argument('--keep-background', action='store_true', help='do not turn the flat background into alpha')
    parser.add_argument('--tolerance', type=int, default=24, help='background colour tolerance per channel')
    args = parser.parse_args()
    try:
        palette = load_palette(args.palette) if args.palette else None
        if args.palette and not palette:
            raise ValueError(f'{args.palette} has no colours')
        sprite = make_sprite(read_png(args.source), *args.size, palette, args.keep_background, args.tolerance)
    except (OSError, ValueError) as error:
        parser.exit(1, f'sprite_fit: {error}\n')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, sprite)
    print(json.dumps({'out': str(out), 'width': sprite.width, 'height': sprite.height,
                      'transparent': sum(1 for pixel in sprite.pixels if not pixel[3]),
                      'palette': len(palette or [])}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
