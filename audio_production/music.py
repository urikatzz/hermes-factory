"""Turn a user-supplied Suno file into a game-ready track: trim, optional seamless loop, loudness, encode."""
import json
from pathlib import Path
import re
import tempfile

from factory_audio.ffmpeg import _run, decode_wav, probe, require
from factory_audio.measure import SILENCE
from factory_audio.wavio import MAX_SECONDS, read_wav, write_wav

KEEP_MS = 10
MATCH_MS = 20
FADE_MS = 10
VORBIS_FRAME = 64  # ffmpeg's native vorbis encoder pads output to a multiple of 64 frames; padding breaks a loop seam


def trim(data, rate):
    frames = len(data[0])
    loud = [i for i in range(frames) if any(abs(c[i]) > SILENCE for c in data)]
    if not loud:
        raise ValueError('the file is silent')
    keep = int(rate * KEEP_MS / 1000)
    start, end = max(0, loud[0] - keep), min(frames, loud[-1] + keep + 1)
    return [c[start:end] for c in data]


def _upward_zero_crossings(mono, lo, hi):
    return [i for i in range(max(1, lo), min(hi, len(mono))) if mono[i - 1] <= 0 < mono[i]]


def find_loop_end(data, rate, bpm=None, loop_end=None):
    mono = [sum(c[i] for c in data) / len(data) for i in range(len(data[0]))]
    n, window = len(mono), int(rate * MATCH_MS / 1000)
    if loop_end is not None:
        lo = int(loop_end * rate)
        if lo < _min_loop(rate):
            raise ValueError(f'loop too short: --loop-end {loop_end}s')
        candidates = _upward_zero_crossings(mono, lo - window, lo + window)
    elif bpm:
        bar = rate * 240 / bpm
        bars = [int(k * bar) for k in range(1, int(n / bar) + 1) if k * bar >= n * 0.75 and k * bar <= n - window]
        candidates = [min(_upward_zero_crossings(mono, b - window, b + window) or [b], key=lambda i, b=b: abs(i - b)) for b in bars]
    else:
        candidates = _upward_zero_crossings(mono, int(n * 0.75), n - window)
    if not candidates:
        raise ValueError('no loop point found; pass --loop-end')
    head = mono[:window]
    def cost(i):
        return sum((a - b) ** 2 for a, b in zip(mono[i:i + window], head))
    return min(candidates, key=cost)


def _min_loop(rate):
    return max(int(rate * FADE_MS / 1000), VORBIS_FRAME)


def make_loop(data, rate, end):
    fade = int(rate * FADE_MS / 1000)
    if end < _min_loop(rate):
        raise ValueError(f'loop too short: {end} frames (minimum {_min_loop(rate)})')
    out = []
    for c in data:
        body = c[:end]
        for k in range(fade):
            w = k / fade
            body[k] = body[k] * w + c[end + k] * (1 - w) if end + k < len(c) else body[k]
        out.append(body)
    return out


def _loudnorm(ff, src, dst, target, peak, codec_args):
    first = _run([ff.ffmpeg, '-hide_banner', '-nostats', '-i', str(src), '-af',
                            f'loudnorm=I={target}:TP={peak}:LRA=11:print_format=json', '-f', 'null', '-'], timeout=300)
    match = re.search(r'\{[^{}]*"input_i"[^{}]*\}', first.stderr, re.S)
    if first.returncode or not match:
        raise ValueError('loudnorm analysis failed')
    m = json.loads(match.group(0))
    graph = (f"loudnorm=I={target}:TP={peak}:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
             f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    done = _run([ff.ffmpeg, '-v', 'error', '-y', '-i', str(src), '-af', graph, *codec_args, str(dst)], timeout=300)
    if done.returncode:
        raise ValueError(f'encode failed: {done.stderr.strip()[:200]}')


def process(ff, src, dst, cls, loop=False, bpm=None, loop_end=None):
    ff = require(ff)
    dst = Path(dst)
    seconds = probe(ff, src)['duration']
    if seconds > MAX_SECONDS:
        raise ValueError(f'{src} is {seconds:.0f}s; longer than the {MAX_SECONDS}s limit')
    with tempfile.TemporaryDirectory() as tmp:
        resampled = Path(tmp) / 'in.wav'
        done = _run([ff.ffmpeg, '-v', 'error', '-y', '-i', str(src), '-ar', str(cls['sample_rate']),
                               '-ac', str(cls['channels']), '-c:a', 'pcm_s16le', str(resampled)], timeout=300)
        if done.returncode:
            raise ValueError(f'cannot decode {src}: {done.stderr.strip()[:200]}')
        wav = decode_wav(ff, resampled, Path(tmp) / 'pcm.wav')
        data = trim(wav.data, wav.rate)
        report = {'source': str(src), 'out': str(dst), 'trimmed_s': round(wav.seconds - len(data[0]) / wav.rate, 3)}
        if loop:
            end = find_loop_end(data, wav.rate, bpm, loop_end)
            if cls['format'] == 'ogg':
                end -= end % VORBIS_FRAME  # the crossfade keeps any end seamless
            data = make_loop(data, wav.rate, end)
            report['loop_end_s'] = round(end / wav.rate, 3)
        staged = Path(tmp) / 'staged.wav'
        write_wav(staged, data, wav.rate)
        # loudnorm resamples internally and can change the frame count, so normalize to a WAV, cut it back to the
        # exact length (which keeps a loop at a multiple of VORBIS_FRAME) and only then encode.
        normed = Path(tmp) / 'normed.wav'
        _loudnorm(ff, staged, normed, cls['loudness_lufs']['target'], cls['peak_dbfs_max'] - 0.5,
                  ['-ar', str(cls['sample_rate']), '-ac', str(cls['channels']), '-c:a', 'pcm_s16le'])
        level = read_wav(normed)
        if level.frames < len(data[0]):
            raise ValueError(f'loudnorm returned {level.frames} frames, expected {len(data[0])}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        if cls['format'] == 'ogg':
            write_wav(normed, [c[:len(data[0])] for c in level.data], level.rate)
            done = _run([ff.ffmpeg, '-v', 'error', '-y', '-i', str(normed), '-c:a', 'vorbis', '-strict', '-2',
                                   '-ac', '2', '-q:a', '5', str(dst)], timeout=300)
            if done.returncode:
                raise ValueError(f'encode failed: {done.stderr.strip()[:200]}')
        else:
            write_wav(dst, [c[:len(data[0])] for c in level.data], level.rate)
    report['seconds'] = round(len(data[0]) / wav.rate, 3)
    return report
