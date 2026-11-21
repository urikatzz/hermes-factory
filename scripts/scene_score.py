#!/usr/bin/env python3
"""Score the complete rendered scene against the complete human-approved reference (gate: 80).

Never pass a single asset as the screenshot: only a real engine capture of the assembled scene, with its render record, is admissible.
Exit 0: pass. Exit 2: a real score below the threshold (the report lists the ranked differences and a diagnosis). Exit 3: blocked, no score was obtained."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.scene_score import MODEL, THRESHOLD, run_scene_similarity
from factory_art.similarity import KEY_VARS, api_key, openrouter_post


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--reference', required=True, help='the original human-approved reference image (never a copy you made)')
    parser.add_argument('--screenshot', required=True, help='PNG captured from the running game engine of the assembled scene')
    parser.add_argument('--render-record', required=True, help='scene-render.json written by the capture (factory-scene-render/v1)')
    parser.add_argument('--out', required=True, help='path for scene-similarity.json')
    parser.add_argument('--assets', default='', help='comma separated asset files that make up the scene (named in the diagnosis)')
    parser.add_argument('--threshold', type=int, default=THRESHOLD, help='minimum passing score; never below 80')
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.threshold < THRESHOLD:
        parser.exit(2, f'scene_score: the threshold cannot be below {THRESHOLD}\n')
    key = api_key(os.environ)
    if not key:
        print('scene_score: no credential in ' + ' or '.join(KEY_VARS) + '; the scene cannot be scored and no score is invented', file=sys.stderr)
    assets = [a for a in args.assets.split(',') if a]
    result = run_scene_similarity(args.reference, args.screenshot, args.render_record, args.out, openrouter_post(key, args.timeout) if key else None,
                                  args.threshold, args.model, assets)
    print(json.dumps({'status': result['status'], 'score': result['score'], 'threshold': result['threshold'], 'problems': result['problems'],
                      'top_differences': [d['description'] for d in result['differences'][:3]], 'scene_similarity': args.out}))
    return {'pass': 0, 'fail': 2}.get(result['status'], 3)


if __name__ == '__main__':
    sys.exit(main())
