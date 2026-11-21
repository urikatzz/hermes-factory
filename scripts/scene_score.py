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
from factory_art.scene_score import MODEL, THRESHOLD, codex_post, run_scene_similarity
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
    parser.add_argument('--backend', choices=('auto', 'openrouter', 'codex'), default='auto', help='auto: OpenRouter when a key is forwarded, else the Codex login')
    parser.add_argument('--allow-unattested', action='store_true', help='accept a render record without the engine attestation (never accepted for final acceptance)')
    parser.add_argument('--timeout', type=int, default=180)
    args = parser.parse_args()
    if args.threshold < THRESHOLD:
        parser.exit(2, f'scene_score: the threshold cannot be below {THRESHOLD}\n')
    import shutil
    key = api_key(os.environ)
    backend = args.backend if args.backend != 'auto' else ('openrouter' if key else ('codex' if shutil.which('codex') else 'none'))
    if backend == 'none' or (backend == 'openrouter' and not key):
        print('scene_score: no credential in ' + ' or '.join(KEY_VARS) + ' and no codex login; the scene cannot be scored and no score is invented', file=sys.stderr)
        post, model = None, args.model
    elif backend == 'codex':
        post, model = codex_post(args.timeout), 'codex-cli'
    else:
        post, model = openrouter_post(key, args.timeout), args.model
    assets = [a for a in args.assets.split(',') if a]
    result = run_scene_similarity(args.reference, args.screenshot, args.render_record, args.out, post, args.threshold, model, assets, require_engine=not args.allow_unattested)
    print(json.dumps({'status': result['status'], 'score': result['score'], 'threshold': result['threshold'], 'final_acceptance': result['final_acceptance'], 'preliminary': result['preliminary'],
                      'missing': (result['completeness'] or {}).get('missing'), 'model': result['model'], 'problems': result['problems'],
                      'top_differences': [d['description'] for d in result['differences'][:3]], 'scene_similarity': args.out}))
    return {'pass': 0, 'fail': 2}.get(result['status'], 3)


if __name__ == '__main__':
    sys.exit(main())
