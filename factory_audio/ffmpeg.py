"""Thin wrappers over the ffmpeg and ffprobe binaries. Each call has a timeout and never uses a shell."""
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

from .wavio import read_wav

TIMEOUT = 120


class FFmpegUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Tools:
    ffmpeg: str
    ffprobe: str


def find_ffmpeg(explicit=None):
    candidates = [explicit] if explicit else [os.environ.get('FFMPEG'), shutil.which('ffmpeg'), '/opt/homebrew/bin/ffmpeg']
    for path in filter(None, candidates):
        probe_path = str(Path(path).with_name('ffprobe'))
        if os.access(path, os.X_OK) and os.access(probe_path, os.X_OK):
            return Tools(path, probe_path)
    return None


def require(tools):
    if tools is None:
        raise FFmpegUnavailable('ffmpeg/ffprobe not found (set $FFMPEG)')
    return tools


def _run(args, timeout=TIMEOUT):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise FFmpegUnavailable(f'{Path(args[0]).name} timed out after {timeout}s') from error


def probe(tools, path):
    done = _run([tools.ffprobe, '-v', 'error', '-show_entries', 'stream=codec_name,channels,sample_rate,duration:format=duration,format_name',
                 '-select_streams', 'a:0', '-of', 'json', str(path)])
    try:
        data = json.loads(done.stdout or '{}')
        stream = data['streams'][0]
        return {'codec': stream['codec_name'], 'channels': int(stream['channels']),
                'sample_rate': int(stream['sample_rate']), 'container': data['format']['format_name'],
                'duration': float(stream.get('duration') or data['format']['duration'])}
    except (KeyError, IndexError, ValueError, json.JSONDecodeError):
        raise ValueError(f'ffprobe could not read {path}: {done.stderr.strip()[:200]}') from None


def decode_wav(tools, path, out):
    done = _run([tools.ffmpeg, '-v', 'error', '-y', '-i', str(path), '-c:a', 'pcm_s16le', str(out)])
    if done.returncode:
        raise ValueError(f'ffmpeg could not decode {path}: {done.stderr.strip()[:200]}')
    return read_wav(out)


SHORT_S = 1.0  # integrated loudness gates on 400 ms blocks; shorter clips are looped up to this length


def loudness(tools, path, seconds=None):
    """Integrated LUFS and sample peak. A clip shorter than SHORT_S (pass its length) is measured looped."""
    loop = ['-stream_loop', str(math.ceil(SHORT_S / seconds))] if seconds and seconds < SHORT_S else []
    done = _run([tools.ffmpeg, '-hide_banner', '-nostats', *loop, '-i', str(path), '-af', 'ebur128=peak=sample',
                 '-f', 'null', '-'])
    summary = done.stderr.rsplit('Summary:', 1)[-1]
    lufs = re.search(r'I:\s+(-?[\d.]+|-inf) LUFS', summary)
    peak = re.search(r'Peak:\s+(-?[\d.]+|-inf) dBFS', summary)
    if done.returncode or not lufs or not peak:
        raise ValueError(f'ffmpeg ebur128 failed on {path}')
    return {'lufs': float(lufs.group(1)), 'peak_dbfs': float(peak.group(1))}


def pictures(tools, path, out_dir, stem):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wave_png, spec_png = out_dir / f'{stem}.wave.png', out_dir / f'{stem}.spectrum.png'
    for target, graph in ((wave_png, 'showwavespic=s=1200x240:split_channels=1'), (spec_png, 'showspectrumpic=s=1200x400:legend=1')):
        done = _run([tools.ffmpeg, '-v', 'error', '-y', '-i', str(path), '-filter_complex', graph, '-frames:v', '1', str(target)])
        if done.returncode:
            raise ValueError(f'ffmpeg picture failed on {path}: {done.stderr.strip()[:200]}')
    return [str(wave_png), str(spec_png)]
