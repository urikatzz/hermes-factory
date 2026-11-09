"""Deterministic audio lint: match files to sound classes, measure them, write lint.json and review pictures."""
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from factory_art.findings import BLOCKING, finding, lines, ordered  # noqa: E402

from .bible import STYLE_DIR, BibleError, classify, is_audio_file, load_bible, style_hash
from .ffmpeg import SHORT_S, FFmpegUnavailable, decode_wav, loudness, pictures, probe
from .measure import clip_runs, dc_offset, edge_silence_ms, loop_seam, peak_dbfs
from .wavio import MAX_SECONDS, WavError, read_wav, wav_seconds

SKIP_DIRS = {'node_modules', 'Library', 'Temp', 'Logs'}
CUES_DIR = 'audio/cues'
INCOMING_DIR = 'audio/incoming'
CODECS = {'wav': ('pcm_s16le',), 'ogg': ('vorbis',)}
SEAM_JUMP_MAX = 0.1
SEAM_RMS_DB_MAX = 3.0
DC_MAX = 0.01


def collect(repo, paths=()):
    repo = Path(repo).resolve()
    found = set()
    for path in paths or ['.']:
        target = (repo / path).resolve()
        if not target.is_relative_to(repo) or not target.exists():
            raise ValueError(f'{path} is not an existing path inside {repo}')
        if target.is_file():
            found.add(target.relative_to(repo).as_posix())
            continue
        for directory, dirs, files in os.walk(target):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in SKIP_DIRS]
            for name in files:
                file = Path(directory) / name
                if not name.startswith('.') and not file.is_symlink():
                    found.add(file.relative_to(repo).as_posix())
    return sorted(f for f in found if not f.startswith((STYLE_DIR + '/', INCOMING_DIR + '/')))


def _stem(rel):
    return rel.replace('_', '_u').replace('/', '__')


def _too_long(rel, seconds):
    return finding('HIGH', 'duration', rel, f'{seconds:.1f}s; longer than the {MAX_SECONDS}s limit, not decoded')


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _finite(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_finite(v) for v in value]
    return value


def check_asset(repo, rel, cls, ff, out, result):
    path, found, measures = Path(repo) / rel, [], {}
    if Path(rel).suffix.lower() == '.wav':
        try:
            seconds = wav_seconds(path)
            if seconds > MAX_SECONDS:
                return [_too_long(rel, seconds)], {'duration': round(seconds, 3)}, []
            wav = read_wav(path)
            info = {'codec': 'pcm_s16le', 'channels': wav.channels, 'sample_rate': wav.rate, 'duration': wav.seconds}
        except WavError as error:
            return [finding('BLOCKER', 'unreadable', rel, str(error))], measures, []
    else:
        if ff is None:
            result['unverified'].append({'file': rel, 'reason': 'environment: ffmpeg not found'})
            return [], measures, []
        try:
            info = probe(ff, path)
            if info['duration'] > MAX_SECONDS:
                return [_too_long(rel, info['duration'])], dict(info), []
            with tempfile.TemporaryDirectory() as tmp:
                wav = decode_wav(ff, path, Path(tmp) / 'd.wav')
        except (ValueError, WavError) as error:
            return [finding('BLOCKER', 'unreadable', rel, str(error))], measures, []
    measures.update(info)
    want_ext = '.' + cls['format']
    if Path(rel).suffix.lower() != want_ext or info['codec'] not in CODECS[cls['format']]:
        found.append(finding('HIGH', 'format', rel, f"{info['codec']} file; class {cls['name']} needs {cls['format']}"))
    if info['sample_rate'] != cls['sample_rate'] or info['channels'] != cls['channels']:
        found.append(finding('HIGH', 'format', rel, f"{info['sample_rate']} Hz x{info['channels']}; class needs "
                                                   f"{cls['sample_rate']} Hz x{cls['channels']}"))
    low, high = cls['duration_s']
    if not low <= wav.seconds <= high:
        found.append(finding('HIGH', 'duration', rel, f'{wav.seconds:.2f}s; class allows {low}-{high}s'))
    peak = peak_dbfs(wav.data)
    measures['peak_dbfs'] = round(peak, 2)
    if peak > cls['peak_dbfs_max']:
        found.append(finding('HIGH', 'peak', rel, f"peak {peak:.1f} dBFS above {cls['peak_dbfs_max']}"))
    clips = clip_runs(wav.data)
    if clips:
        found.append(finding('HIGH', 'clipping', rel, f'{clips} clipped runs (3+ full-scale samples)'))
    offset = dc_offset(wav.data)
    if abs(offset) > DC_MAX:
        found.append(finding('MEDIUM', 'dc_offset', rel, f'DC offset {offset:.3f}'))
    lead, tail = edge_silence_ms(wav.data, wav.rate)
    measures.update(lead_silence_ms=round(lead), tail_silence_ms=round(tail))
    limit = cls.get('silence_max_ms')  # absent: check off; 0: no edge silence allowed
    if not cls.get('loop') and limit is not None and max(lead, tail) > limit:
        found.append(finding('MEDIUM', 'silence', rel, f'{lead:.0f} ms lead / {tail:.0f} ms tail silence; max {limit} ms'))
    if cls.get('loop'):
        seam = loop_seam(wav.data, wav.rate)
        measures['loop_seam'] = seam
        if seam['jump'] > SEAM_JUMP_MAX or seam['rms_ratio_db'] > SEAM_RMS_DB_MAX:
            found.append(finding('HIGH', 'loop_seam', rel, f"loop seam click: jump {seam['jump']}, level change {seam['rms_ratio_db']} dB"))
    images = []
    if ff is not None:
        try:
            loud = loudness(ff, path, wav.seconds)
            measures['lufs'] = loud['lufs']
            if wav.seconds < SHORT_S:
                measures['lufs_looped'] = True
            target, tol = cls['loudness_lufs']['target'], cls['loudness_lufs']['tolerance']
            off = abs(loud['lufs'] - target)
            if off > 2 * tol:
                found.append(finding('HIGH', 'loudness', rel, f"{loud['lufs']} LUFS; target {target} +/- {tol}"))
            elif off > tol:
                found.append(finding('MEDIUM', 'loudness', rel, f"{loud['lufs']} LUFS; target {target} +/- {tol}"))
            images = pictures(ff, path, Path(out) / 'pictures', _stem(rel))
        except (ValueError, FFmpegUnavailable) as error:
            result['unverified'].append({'file': rel, 'reason': f'environment: {error}'})
    else:
        result['warnings'].append(f'{rel}: ffmpeg not found; loudness not measured and no pictures')
    return found, measures, images


def stale_cues(repo, files):
    found = []
    cues = Path(repo) / CUES_DIR
    if not cues.is_dir():
        return found
    for cue in sorted(cues.glob('*.md')):
        match = re.search(r'^target:\s*(\S+)', cue.read_text(errors='replace'), re.M)
        if not match:
            continue
        target = (Path(repo) / match.group(1)).resolve()
        if not target.is_relative_to(Path(repo).resolve()):
            found.append(finding('LOW', 'stale_cue', cue.relative_to(repo).as_posix(), f'target outside repo: {match.group(1)}'))
        elif not target.is_file():
            found.append(finding('LOW', 'stale_cue', cue.relative_to(repo).as_posix(), f'no file at {match.group(1)} yet'))
    return found


def run_lint(repo, out, paths=(), ff=None, expect_style_hash=None):
    repo, out = Path(repo).resolve(), Path(out)
    files = collect(repo, paths)
    result = {'schema': 'factory-audio-lint/v1', 'repo': str(repo), 'audio_files': 0, 'findings': [], 'assets': [],
              'unverified': [], 'warnings': []}
    if expect_style_hash and style_hash(repo) != expect_style_hash.lower():
        result['findings'].append(finding('BLOCKER', 'style', STYLE_DIR, f'{STYLE_DIR} changed during an asset task'))
    audio = [f for f in files if is_audio_file(f)]
    result['audio_files'] = len(audio)
    try:
        bible = load_bible(repo)
    except BibleError as error:
        if audio:
            result['findings'].append(finding('BLOCKER', 'bible', STYLE_DIR, str(error)))
        return _finish(result, out)
    for rel in audio:
        cls, overlaps = classify(bible, rel)
        if cls is None:
            result['findings'].append(finding('MEDIUM', 'unclassified', rel, f'matches no class in {STYLE_DIR}/audio.json'))
            continue
        if overlaps:
            result['warnings'].append(f'{rel} also matches {overlaps}; using {cls["name"]}')
        found, measures, images = check_asset(repo, rel, cls, ff, out, result)
        result['findings'].extend(found)
        result['assets'].append({'file': rel, 'class': cls['name'], 'kind': cls['kind'], 'rules': cls.get('rules', []),
                                 'measures': measures, 'images': images})
    if not paths:
        result['findings'].extend(stale_cues(repo, files))
    return _finish(result, out)


def _finish(result, out):
    result['findings'] = ordered(result['findings'])
    result['lines'] = lines(result['findings'])
    result['lint_blocking'] = any(f['severity'] in BLOCKING for f in result['findings'])
    out.mkdir(parents=True, exist_ok=True)
    result = _finite(result)
    (out / 'lint.json').write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    return result
