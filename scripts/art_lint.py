#!/usr/bin/env python3
"""Lint game art against the repo's art/style bible and prepare images for the vision review."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.blender_runner import find_blender
from factory_art.lint import run_lint
from factory_art.style_bible import BibleError, load_bible, style_hash


def check_bible(repo):
    try:
        bible = load_bible(repo)
    except BibleError as error:
        print(json.dumps({'bible': 'invalid', 'error': str(error)}))
        return 1
    print(json.dumps({'bible': 'ok', 'classes': [cls['name'] for cls in bible['classes']],
                      'rules': sorted(bible['rules'])}))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo')
    parser.add_argument('paths', nargs='*', help='files or directories relative to repo (default: all)')
    parser.add_argument('--out', help='directory for lint.json and review images (required unless --check-bible)')
    parser.add_argument('--first', action='append', default=[], help='review this file first (repeatable)')
    parser.add_argument('--max-images', type=int, default=40)
    parser.add_argument('--blender', help='Blender executable (default: $BLENDER, PATH, /Applications)')
    parser.add_argument('--timeout', type=int, default=120, help='seconds per model')
    parser.add_argument('--fail-on-blocking', action='store_true',
                        help='gate mode: exit 1 when any BLOCKER or HIGH finding exists')
    parser.add_argument('--check-bible', action='store_true',
                        help='only validate art/style: exit 0 when it loads, 1 when it does not')
    parser.add_argument('--style-hash', action='store_true',
                        help='only print {"style_sha256": ...} for art/style (recorded in PLAN.md for asset tasks)')
    parser.add_argument('--expect-style-hash', metavar='HEX',
                        help='add a BLOCKER finding "style" when art/style no longer has this style_sha256')
    args = parser.parse_args()
    if args.style_hash:
        print(json.dumps({'style_sha256': style_hash(args.repo)}))
        return 0
    if args.check_bible:
        return check_bible(args.repo)
    if not args.out:
        parser.error('--out is required unless --check-bible is given')
    try:
        result = run_lint(args.repo, args.out, args.paths, find_blender(args.blender), args.first,
                          args.max_images, args.timeout, args.expect_style_hash)
    except ValueError as error:
        parser.exit(2, f'art_lint: {error}\n')
    summary = {key: result[key] for key in ('art_files', 'images', 'lint_blocking')}
    summary.update(findings=len(result['findings']), not_reviewed=len(result['not_reviewed']),
                   unverified=len(result['unverified']), lint=str(Path(args.out) / 'lint.json'))
    print(json.dumps(summary))
    return 1 if args.fail_on_blocking and result['lint_blocking'] else 0


if __name__ == '__main__':
    sys.exit(main())
