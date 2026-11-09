"""Sound bibles, generated tones and a sample game repo for audio tests."""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from factory_audio.wavio import write_wav

RULES_MD = """# Test game sound

**A1** (blocking) UI sounds are short and never harsh.
**A2** Music loops without an audible seam.
"""
SFX_CLASS = {'name': 'ui_sfx', 'kind': 'sfx', 'match': ['Assets/Audio/SFX/**'], 'format': 'wav',
             'sample_rate': 44100, 'channels': 1, 'duration_s': [0.05, 1.0], 'peak_dbfs_max': -1.0,
             'loudness_lufs': {'target': -18, 'tolerance': 3}, 'silence_max_ms': 30, 'loop': False, 'rules': ['A1']}
MUSIC_CLASS = {'name': 'music', 'kind': 'music', 'match': ['Assets/Audio/Music/**'], 'format': 'ogg',
               'sample_rate': 44100, 'channels': 2, 'duration_s': [4, 300], 'peak_dbfs_max': -1.0,
               'loudness_lufs': {'target': -16, 'tolerance': 2}, 'silence_max_ms': 200, 'loop': True, 'rules': ['A2']}


def write_bible(root, classes=(SFX_CLASS, MUSIC_CLASS), rules_md=RULES_MD):
    style = Path(root) / 'audio' / 'style'
    style.mkdir(parents=True, exist_ok=True)
    (style / 'AUDIO.md').write_text(rules_md)
    (style / 'audio.json').write_text(json.dumps({'version': 1, 'classes': list(classes)}))
    return style


def tone(seconds, freq=440.0, amp=0.5, rate=44100, channels=1, lead=0.0, tail=0.0, fade=0.005):
    """A sine with optional leading/trailing silence and short fades; returns per-channel float lists."""
    body = int(seconds * rate)
    samples = []
    for i in range(body):
        env = min(1.0, i / (fade * rate), (body - 1 - i) / (fade * rate)) if fade else 1.0
        samples.append(amp * env * math.sin(2 * math.pi * freq * i / rate))
    mono = [0.0] * int(lead * rate) + samples + [0.0] * int(tail * rate)
    return [list(mono) for _ in range(channels)]


def loop_tone(seconds, freq=441.0, amp=0.3, rate=44100, channels=2):
    """A sine with a whole number of cycles, so the end joins the start without a click."""
    cycles = round(seconds * freq)
    count = int(round(cycles * rate / freq))
    mono = [amp * math.sin(2 * math.pi * cycles * i / count) for i in range(count)]
    return [list(mono) for _ in range(channels)]


def write_tone(path, channels_data, rate=44100):
    write_wav(path, channels_data, rate)
    return Path(path)


import subprocess

TESTGAME_EXPECTED = sorted([
    ('BLOCKER', 'unreadable', 'Assets/Audio/SFX/broken.wav'),
    ('HIGH', 'clipping', 'Assets/Audio/SFX/loud.wav'),
    ('HIGH', 'duration', 'Assets/Audio/SFX/long.wav'),
    ('HIGH', 'format', 'Assets/Audio/SFX/stereo.wav'),
    ('HIGH', 'loop_seam', 'Assets/Audio/Music/clicky.ogg'),
    ('HIGH', 'loudness', 'Assets/Audio/SFX/loud.wav'),
    ('HIGH', 'peak', 'Assets/Audio/SFX/loud.wav'),
    ('MEDIUM', 'dc_offset', 'Assets/Audio/SFX/offset.wav'),
    ('MEDIUM', 'silence', 'Assets/Audio/SFX/late.wav'),
    ('MEDIUM', 'unclassified', 'Assets/Other/stray.wav'),
    ('LOW', 'stale_cue', 'audio/cues/boss.md'),
])


# The native ffmpeg vorbis encoder pads its output to a multiple of 64 frames, and the padding
# smears the loop seam. Fixture loops are therefore whole multiples of 64 frames: theme is 2624
# cycles of 441 Hz (262400 frames); clicky is 264192 frames, which ends 0.75 into a 437.3 Hz cycle.
CLICKY_FRAMES = 264192


def _ogg(ffmpeg, wav, ogg):
    subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(wav), '-c:a', 'vorbis', '-strict', '-2', str(ogg)], check=True)
    Path(wav).unlink()


def build_testgame(root, ffmpeg):
    """One good and one bad asset per check. Loudness values stay within tolerance except where expected."""
    root = Path(root)
    write_bible(root)
    sfx, music = root / 'Assets/Audio/SFX', root / 'Assets/Audio/Music'
    sfx.mkdir(parents=True); music.mkdir(parents=True)
    write_tone(sfx / 'click.wav', tone(0.12, freq=1200, amp=0.2))
    write_tone(sfx / 'loud.wav', [[max(-1.0, min(1.0, 3 * v)) for v in tone(0.3, amp=0.9)[0]]])
    write_tone(sfx / 'long.wav', tone(2.0, amp=0.25))
    write_tone(sfx / 'stereo.wav', tone(0.2, amp=0.18, channels=2))
    write_tone(sfx / 'offset.wav', [[v + 0.05 for v in tone(0.3, amp=0.2)[0]]])
    write_tone(sfx / 'late.wav', tone(0.2, amp=0.25, lead=0.2))
    (sfx / 'broken.wav').write_bytes(b'RIFF0000WAVEjunk')
    write_tone(music / 'theme.wav', loop_tone(5.95, amp=0.17))
    _ogg(ffmpeg, music / 'theme.wav', music / 'theme.ogg')
    write_tone(music / 'clicky.wav', [c[:CLICKY_FRAMES] for c in tone(6.0, freq=437.3, amp=0.17, channels=2, fade=0)])
    _ogg(ffmpeg, music / 'clicky.wav', music / 'clicky.ogg')
    (root / 'Assets/Other').mkdir(parents=True)
    write_tone(root / 'Assets/Other/stray.wav', tone(0.1))
    cues = root / 'audio/cues'
    cues.mkdir(parents=True)
    (cues / 'theme.md').write_text('# theme\ntarget: Assets/Audio/Music/theme.ogg\n')
    (cues / 'boss.md').write_text('# boss\ntarget: Assets/Audio/Music/boss.ogg\n')
    return root
