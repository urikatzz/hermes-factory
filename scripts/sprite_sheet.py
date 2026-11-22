#!/usr/bin/env python3
"""Slice one generated sheet into a set of named, fitted, cut-out sprites (and optionally write the set's metadata).

  sprite_sheet.py sheet.png OUT_DIR --grid 7x6 --names "A,B,C,...,Z,0,1,...,9,-, ,." --size 128x128 [--prefix stencil-glyph-] [--metadata OUT_DIR/stencil-glyphs.json]

The grid is COLUMNSxROWS, read left to right then top to bottom, with exactly one name per cell (a cell that is meant to be empty may be named `space`). Names may also
come from --names-file (one per line; a line holding a single space is the space glyph). Each cell is cut out and fitted like a single sprite (--margin, --drop-fragments-below),
and the JSON printed per item reports edge contact and detached fragments, so the set can be checked before it is delivered. Exit 0 sliced; 3 the sheet cannot be sliced as asked
(item count, a cell without content, a name that cannot be a file name); 2 bad arguments."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.sheet import SheetError, slice_sheet
from factory_art.png import PngError, read_png, write_png
from factory_art.style_bible import load_palette


def pair(text, separator):
    try:
        a, b = text.lower().split(separator)
        return int(a), int(b)
    except ValueError:
        raise argparse.ArgumentTypeError(f'expected 2 integers separated by "{separator}", for example 7{separator}6')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('sheet'); parser.add_argument('out_dir')
    parser.add_argument('--grid', type=lambda t: pair(t, 'x'), required=True, help='COLUMNSxROWS')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--names', help='comma separated item names in grid order (use "space" for an empty cell)')
    group.add_argument('--names-file', help='one name per line in grid order')
    parser.add_argument('--size', type=lambda t: pair(t, 'x'), required=True, help='WIDTHxHEIGHT of every sprite')
    parser.add_argument('--prefix', default='', help='file name prefix, for example stencil-glyph-')
    parser.add_argument('--margin', type=int, default=2); parser.add_argument('--drop-fragments-below', type=int, default=0, metavar='PX')
    parser.add_argument('--palette'); parser.add_argument('--metadata', help='write a factory-sprite-set/v1 JSON listing every sprite')
    args = parser.parse_args()
    if args.names_file:
        names = [line.rstrip('\n') for line in Path(args.names_file).read_text().split('\n')]
        names = names[:-1] if names and names[-1] == '' else names
    else:
        names = [n if n != 'space' else 'space' for n in args.names.split(',')]
    names = [' ' if n.strip() == '' and n != '' else n for n in names]
    try:
        palette = load_palette(args.palette) if args.palette else None
        done = slice_sheet(read_png(args.sheet), args.grid[0], args.grid[1], names, args.size, args.prefix, max(0, args.margin), max(0, args.drop_fragments_below), palette)
    except SheetError as error:
        print(json.dumps(dict(ok=False, error=str(error)))); print(f'sprite_sheet: {error}', file=sys.stderr)
        return 3
    except (OSError, PngError, ValueError) as error:
        parser.exit(2, f'sprite_sheet: {error}\n')
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)
    items = []
    for name, filename, sprite, report in done:
        write_png(out / filename, sprite)
        items.append(dict(name=name, file=filename, width=sprite.width, height=sprite.height, blank=bool(report.get('blank')),
                          edge_contact=report.get('edge_contact'), fragment_count=report.get('fragment_count', 0)))
    if args.metadata:
        Path(args.metadata).parent.mkdir(parents=True, exist_ok=True)
        Path(args.metadata).write_text(json.dumps(dict(schema='factory-sprite-set/v1', size=dict(width=args.size[0], height=args.size[1]), items=items), indent=2) + '\n')
    problems = [i['file'] for i in items if (i['edge_contact'] and any(i['edge_contact'].values())) or i['fragment_count']]
    print(json.dumps(dict(ok=True, count=len(items), out_dir=str(out), metadata=args.metadata, items=items, needs_attention=problems)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
