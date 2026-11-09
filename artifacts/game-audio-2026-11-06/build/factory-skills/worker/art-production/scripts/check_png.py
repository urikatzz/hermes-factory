#!/usr/bin/env python3
"""Exit 0 and print the size when a file is a PNG that factory_art.png decodes; exit 1 otherwise."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.png import PngError, read_png


def main():
    if len(sys.argv) != 2:
        print('usage: check_png.py <file.png>', file=sys.stderr)
        return 2
    try:
        image = read_png(sys.argv[1])
    except (OSError, PngError) as error:
        print(f'check_png: {sys.argv[1]}: {error}', file=sys.stderr)
        return 1
    print(json.dumps({'width': image.width, 'height': image.height}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
