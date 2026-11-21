#!/usr/bin/env python3
"""Fit a generated image to an asset class: nearest-neighbour fit, palette quantize, and for cut-out sprites flat background to alpha.

--coverage opaque keeps every pixel (walls, floors, backdrops, bands, tiles: anything required to cover an area); --coverage cutout (default) makes the flat
background transparent (isolated sprites); --coverage auto --hint TEXT chooses from the asset's name or criterion. The result is verified; exit 3 prints the diagnosis."""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.sprite_fit import COVERAGES, FitError, choose_coverage, fit_asset, make_sprite
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
    parser.add_argument('--coverage', choices=('auto',) + COVERAGES, default='cutout', help='opaque: keep every pixel; cutout: flat background to alpha; auto: choose from --hint')
    parser.add_argument('--hint', default='', help='the asset name or its acceptance criterion text, used by --coverage auto')
    parser.add_argument('--margin', type=int, default=None, help='transparent pixels kept on every side of a cutout (default 2) so the sprite never reads as cropped at the canvas edge; 0 fills the canvas')
    parser.add_argument('--drop-fragments-below', type=int, default=0, metavar='PX', help='cutout: clear detached visible groups smaller than PX pixels (never the largest); the JSON always reports the fragments it sees')
    parser.add_argument('--allow-mostly-transparent', action='store_true', help='accept a cut-out that erases almost the whole image (a small sprite on a large flat background)')
    parser.add_argument('--tolerance', type=int, default=24, help='background colour tolerance per channel')
    args = parser.parse_args()
    coverage = 'opaque' if args.keep_background else (choose_coverage(args.hint) if args.coverage == 'auto' else args.coverage)
    try:
        palette = load_palette(args.palette) if args.palette else None
        if args.palette and not palette:
            raise ValueError(f'{args.palette} has no colours')
        sprite, report = fit_asset(read_png(args.source), *args.size, palette, coverage, args.tolerance, args.allow_mostly_transparent,
                                  2 if args.margin is None else max(0, args.margin), max(0, args.drop_fragments_below))
    except FitError as error:
        print(json.dumps(dict(ok=False, **error.diagnosis)))
        print(f'sprite_fit: {error.diagnosis["defect"]} defect: {error}. {error.diagnosis["fix"]}', file=sys.stderr)
        return 3
    except (OSError, ValueError) as error:
        parser.exit(1, f'sprite_fit: {error}\n')
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_png(out, sprite)
    print(json.dumps({'ok': True, 'out': str(out), 'width': sprite.width, 'height': sprite.height,
                      'transparent': sum(1 for pixel in sprite.pixels if not pixel[3]),
                      'coverage': report['coverage'], 'opaque': report['opaque'], 'palette': len(palette or []),
                      **{k: report[k] for k in ('edge_contact', 'margin', 'fragment_count', 'fragments', 'dropped_fragments', 'dropped_px') if k in report}}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
