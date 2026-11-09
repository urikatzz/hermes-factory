#!/usr/bin/env python3
"""Render one sfxr-style recipe JSON to a 16-bit WAV. Exit 2 on a bad recipe."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_production.synth import RecipeError, render
from factory_audio.measure import peak_dbfs
from factory_audio.wavio import write_wav


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipe', type=Path)
    parser.add_argument('out', type=Path)
    args = parser.parse_args()
    try:
        data, rate = render(json.loads(args.recipe.read_text()))
    except (ValueError, OSError) as error:  # RecipeError and JSONDecodeError are ValueErrors
        parser.exit(2, f'sfx_synth: {error}\n')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(args.out, data, rate)
    print(json.dumps({'out': str(args.out), 'seconds': round(len(data[0]) / rate, 3), 'channels': len(data),
                      'peak_dbfs': round(peak_dbfs(data), 2)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
