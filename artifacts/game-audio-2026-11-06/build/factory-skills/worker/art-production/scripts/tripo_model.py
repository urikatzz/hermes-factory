#!/usr/bin/env python3
"""Image to GLB through the Tripo API. Exit 0 done, 1 failed, 2 usage, 3 fallback (no key, no credits, API down).

The key comes from TRIPO_API_KEY (the artist profile's .env). TRIPO_BASE_URL overrides the API root for tests.
"""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from art_production.tripo import BASE_URL, FallbackError, TaskError, TripoClient, image_to_model
from factory_art.png import PngError, read_png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', nargs='?', help='concept PNG')
    parser.add_argument('out', nargs='?', help='GLB to write')
    parser.add_argument('--balance', action='store_true', help='print the account balance (free) and exit')
    args = parser.parse_args()
    if not args.balance and not (args.image and args.out):
        parser.error('image and out are required')
    client = None
    try:
        client = TripoClient(os.environ.get('TRIPO_API_KEY', '').strip(), os.environ.get('TRIPO_BASE_URL', BASE_URL))
        if args.balance:
            print(json.dumps({'balance': client.balance()}))
            return 0
        read_png(args.image)  # never pay for an image that does not decode
        task_id = image_to_model(client, args.image, args.out)
    except FallbackError as error:
        print(json.dumps({'fallback': str(error), 'tripo_tasks': client.task_ids if client else []}))
        return 3
    except (TaskError, OSError, PngError) as error:
        print(json.dumps({'error': str(error), 'tripo_tasks': client.task_ids if client else []}))
        return 1
    print(json.dumps({'model': args.out, 'task_id': task_id, 'tripo_tasks': client.task_ids}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
