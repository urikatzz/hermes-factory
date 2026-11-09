#!/usr/bin/env python3
"""Lint game audio against the repo's audio/style bible and prepare waveform/spectrum pictures for review."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_audio.bible import BibleError, load_bible, style_hash
from factory_audio.ffmpeg import find_ffmpeg
from factory_audio.lint import run_lint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repo')
    parser.add_argument('paths', nargs='*', help='files or directories relative to repo (default: all)')
    parser.add_argument('--out', help='directory for lint.json and pictures (required unless --check-bible/--style-hash)')
    parser.add_argument('--ffmpeg', help='ffmpeg executable (default: $FFMPEG, PATH, /opt/homebrew/bin)')
    parser.add_argument('--fail-on-blocking', action='store_true', help='gate mode: exit 1 on any BLOCKER or HIGH')
    parser.add_argument('--check-bible', action='store_true', help='only validate audio/style: exit 0 ok, 1 invalid')
    parser.add_argument('--style-hash', action='store_true', help='only print {"style_sha256": ...} for audio/style')
    parser.add_argument('--expect-style-hash', metavar='HEX', help='BLOCKER "style" when audio/style changed')
    args = parser.parse_args()
    if args.style_hash:
        print(json.dumps({'style_sha256': style_hash(args.repo)}))
        return 0
    if args.check_bible:
        try:
            bible = load_bible(args.repo)
        except BibleError as error:
            print(json.dumps({'bible': 'invalid', 'error': str(error)}))
            return 1
        print(json.dumps({'bible': 'ok', 'classes': [c['name'] for c in bible['classes']], 'rules': sorted(bible['rules'])}))
        return 0
    if not args.out:
        parser.error('--out is required unless --check-bible or --style-hash is given')
    try:
        result = run_lint(args.repo, args.out, args.paths, find_ffmpeg(args.ffmpeg), args.expect_style_hash)
    except ValueError as error:
        parser.exit(2, f'audio_lint: {error}\n')
    print(json.dumps({'audio_files': result['audio_files'], 'findings': len(result['findings']),
                      'unverified': len(result['unverified']), 'lint_blocking': result['lint_blocking'],
                      'lint': str(Path(args.out) / 'lint.json')}))
    return 1 if args.fail_on_blocking and result['lint_blocking'] else 0


if __name__ == '__main__':
    sys.exit(main())
