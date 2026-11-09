#!/usr/bin/env python3
"""Process one Suno file into a game track for a bible class. Exit 1 on processing failure, 2 on bad arguments."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_production.music import process
from factory_audio.bible import STYLE_DIR, BibleError, load_bible
from factory_audio.ffmpeg import FFmpegUnavailable, find_ffmpeg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('src', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--class', dest='cls', required=True, help='class name in audio.json')
    parser.add_argument('--bible', required=True, type=Path, help='audio/style/audio.json')
    parser.add_argument('--loop', action='store_true')
    parser.add_argument('--bpm', type=float)
    parser.add_argument('--loop-end', type=float, help='seconds; search around this point')
    parser.add_argument('--ffmpeg')
    args = parser.parse_args()
    bible_path = args.bible.resolve()
    repo = bible_path.parents[2] if len(bible_path.parents) > 2 else bible_path.parent
    if bible_path != repo / STYLE_DIR / 'audio.json':
        parser.exit(2, f'music_process: --bible must be <repo>/{STYLE_DIR}/audio.json\n')
    try:
        classes = {c['name']: c for c in load_bible(repo)['classes']}
    except BibleError as error:
        parser.exit(2, f'music_process: invalid bible: {error}\n')
    if args.cls not in classes or classes[args.cls].get('kind') != 'music':
        parser.exit(2, f'music_process: no music class {args.cls!r} in {args.bible}\n')
    try:
        report = process(find_ffmpeg(args.ffmpeg), args.src, args.out, classes[args.cls], args.loop, args.bpm, args.loop_end)
    except (ValueError, FFmpegUnavailable, OSError) as error:
        print(f'music_process: {error}', file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    sys.exit(main())
