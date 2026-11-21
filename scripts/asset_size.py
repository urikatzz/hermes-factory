#!/usr/bin/env python3
"""Choose an asset's pixel size when the task does not state one (never a reason to block).

  asset_size.py --aspect 1.5 [--world 1.7x1.7 [--ppu 128]] [--explicit WxH] [--class-min 32 --class-max 2048 --cap 1024]

--explicit wins and is only validated against the class range. Otherwise the size is derived from the aspect of the asset's region of the approved reference (and the plan's world
proportions when given), with the longest side at the cap. Prints JSON: width, height, source (explicit or derived), world, aspect and the reasoning to copy into the task report.
Exit 0 sized; 3 the constraints contradict each other or cannot be met (a genuine blocker); 2 bad arguments."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.sizing import CAP, CLASS_MAX, CLASS_MIN, PPU, SizingError, derive_size


def pair(text):
    try:
        a, b = text.lower().split('x')
        return float(a), float(b)
    except ValueError:
        raise argparse.ArgumentTypeError('expected WxH, for example 1.7x1.7')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--aspect', type=float, help='width / height of the asset in the approved reference')
    parser.add_argument('--world', type=pair, help='world size WxH in units from the plan')
    parser.add_argument('--explicit', type=pair, help='pixel size WxH the task states (takes precedence)')
    parser.add_argument('--class-min', type=int, default=CLASS_MIN)
    parser.add_argument('--class-max', type=int, default=CLASS_MAX)
    parser.add_argument('--cap', type=int, default=CAP, help='longest side in pixels unless a higher resolution is explicitly required')
    parser.add_argument('--ppu', type=float, default=PPU, help='pixels per world unit used with --world')
    args = parser.parse_args()
    try:
        result = derive_size(args.aspect, args.world, args.explicit, args.class_min, args.class_max, args.cap, args.ppu)
    except SizingError as error:
        print(json.dumps(dict(ok=False, error=str(error))))
        print(f'asset_size: {error}', file=sys.stderr)
        return 3
    print(json.dumps(dict(ok=True, **result)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
