#!/usr/bin/env python3
"""Assemble a real Unity scene from a layout and capture it with the engine (isolated clone; the project is never modified).

Writes OUT/scene.png, OUT/scene-render.json (factory-scene-render/v1 with the engine's own attestation and the completeness of the scene), OUT/engine-capture.json,
the built scene and unity.log. Exit 0 captured and verified; 3 not captured (no engine, bad layout, Unity failed, or the engine's account did not check out)."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_unity.scene_capture import CaptureError, capture


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', required=True, help='Unity project directory')
    parser.add_argument('--layout', required=True, help='factory-scene-layout/v1 JSON')
    parser.add_argument('--out', required=True, help='output directory')
    parser.add_argument('--required', default='', help='comma separated approved-reference requirement ids the final scene must cover')
    parser.add_argument('--deferred', default='', help='comma separated requirement ids a human deferred')
    parser.add_argument('--editor', help='Unity Editor binary (default: the Hub install matching the project version, or $FACTORY_UNITY_EDITOR)')
    parser.add_argument('--library-from', help='Library cache to clone from (default: the project, or its main git worktree)')
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    split = lambda text: [x for x in text.split(',') if x]
    try:
        record = capture(args.project, args.layout, args.out, split(args.required), split(args.deferred), args.editor, args.timeout, library_from=args.library_from)
    except CaptureError as error:
        print(json.dumps(dict(captured=False, stage=error.stage, error=str(error))))
        print(f'unity_scene_capture: not captured ({error.stage}): {error}', file=sys.stderr)
        return 3
    done = record['completeness']
    print(json.dumps(dict(captured=True, screenshot=str(Path(args.out) / 'scene.png'), scene_render=str(Path(args.out) / 'scene-render.json'), engine=record['engine']['engine_version'],
                          graphics_device=record['engine']['graphics_device'], resolution=[record['width'], record['height']], objects=record['engine']['objects_placed'],
                          complete=done['complete'], missing=done['missing'], preliminary=not done['complete'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
