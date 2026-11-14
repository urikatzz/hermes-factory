#!/usr/bin/env python3
"""Score rendered art against its reference images with the Jev model on OpenRouter (gate: 80%)."""
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.similarity import MODEL, THRESHOLD, openrouter_post, run_similarity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lint', help='lint.json written by art_lint.py')
    parser.add_argument('--out', required=True, help='path for similarity.json')
    parser.add_argument('--threshold', type=int, default=THRESHOLD, help='minimum passing score, 0-100')
    parser.add_argument('--model', default=MODEL, help='OpenRouter model ID')
    parser.add_argument('--timeout', type=int, default=120, help='seconds per asset')
    args = parser.parse_args()
    try:
        lint = json.loads(Path(args.lint).read_text())
    except (OSError, ValueError) as error:
        parser.exit(2, f'art_similarity: {error}\n')
    key = os.environ.get('OPENROUTER_API_KEY')
    result = run_similarity(lint, args.out, openrouter_post(key, args.timeout) if key else None, args.threshold, args.model)
    below = [row['file'] for row in result['assets'] if row['status'] in ('fail', 'no_reference')]
    print(json.dumps({'gate': result['gate'], 'threshold': result['threshold'], 'assets': len(result['assets']),
                      'below_threshold': below, 'blocked_tools': result['blocked_tools'], 'similarity': args.out}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
