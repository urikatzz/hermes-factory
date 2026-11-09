#!/usr/bin/env python3
"""Create a sample game repo with an approved sound bible, for the paid end-to-end Audio tasks. Prints {"repo": ...}."""
import json
from pathlib import Path
import subprocess
import sys

RULES = """# Sample game sound

**A1** (blocking) UI sounds are short (under 150 ms) and never harsh: no energy above 8 kHz dominates.
**A2** (blocking) Music loops without an audible seam.
**A3** Game effects are retro chiptune: square, triangle and noise voices.
**A4** Jump sounds rise in pitch; damage sounds fall.
"""
CLASSES = [
    {'name': 'ui_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/UI/**'], 'format': 'wav', 'sample_rate': 44100,
     'channels': 1, 'duration_s': [0.02, 0.15], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -20, 'tolerance': 4},
     'silence_max_ms': 20, 'loop': False, 'rules': ['A1']},
    {'name': 'game_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/Game/**'], 'format': 'wav', 'sample_rate': 44100,
     'channels': 1, 'duration_s': [0.05, 1.5], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -16, 'tolerance': 4},
     'silence_max_ms': 30, 'loop': False, 'rules': ['A3', 'A4']},
    {'name': 'music', 'kind': 'music', 'match': ['Assets/Audio/Music/**'], 'format': 'ogg', 'sample_rate': 44100,
     'channels': 2, 'duration_s': [20, 240], 'peak_dbfs_max': -1.0, 'loudness_lufs': {'target': -16, 'tolerance': 2},
     'silence_max_ms': 200, 'loop': True, 'rules': ['A2']},
]


def main():
    repo = Path(sys.argv[1]).absolute()
    if repo.exists():
        sys.exit(f'{repo} already exists')
    style = repo / 'audio/style'
    style.mkdir(parents=True)
    (style / 'AUDIO.md').write_text(RULES)
    (style / 'audio.json').write_text(json.dumps({'version': 1, 'classes': CLASSES}, indent=2) + '\n')
    (repo / 'README.md').write_text('# Audio sample game\n\nSample repo for Factory Audio tasks.\n')
    for args in (['init', '-q', '-b', 'main'], ['add', '-A'],
                 ['-c', 'user.name=factory', '-c', 'user.email=factory@localhost', 'commit', '-q', '-m', 'Sound bible']):
        subprocess.run(['git', '-C', str(repo), *args], check=True)
    print(json.dumps({'repo': str(repo)}))


if __name__ == '__main__':
    main()
