"""sfxr-style sound effect synthesis from a JSON recipe. Deterministic for a given recipe and seed."""
import math
import random

WAVES = ('square', 'saw', 'sine', 'triangle', 'noise')
DEFAULTS = {'freq_start': 440.0, 'attack': 0.005, 'sustain': 0.1, 'decay': 0.15, 'sustain_punch': 0.0,
            'vibrato_depth': 0.0, 'vibrato_hz': 6.0, 'arp_semitones': 0.0, 'arp_at': 0.5, 'duty': 0.5,
            'lowpass_hz': 0.0, 'highpass_hz': 0.0, 'volume': 0.5, 'seed': 1, 'sample_rate': 44100, 'channels': 1,
            'peak_dbfs_max': -1.0}
MAX_SECONDS = 30.0


class RecipeError(ValueError):
    pass


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse(recipe):
    if not isinstance(recipe, dict) or recipe.get('wave') not in WAVES:
        raise RecipeError(f'recipe needs wave in {WAVES}')
    unknown = set(recipe) - set(DEFAULTS) - {'wave', 'freq_end', 'name', 'notes'}
    if unknown:
        raise RecipeError(f'unknown recipe keys {sorted(unknown)}')
    r = dict(DEFAULTS, **recipe)
    r.setdefault('freq_end', r['freq_start'])
    for key in set(DEFAULTS) | {'freq_end'}:
        if not _number(r[key]):
            raise RecipeError(f'{key} must be a number')
    for key in ('attack', 'sustain', 'decay', 'sustain_punch', 'vibrato_depth', 'lowpass_hz', 'highpass_hz', 'volume'):
        if r[key] < 0:
            raise RecipeError(f'{key} must be >= 0')
    if not 20 <= r['freq_start'] <= 20000 or not 20 <= r['freq_end'] <= 20000:
        raise RecipeError('freq_start and freq_end must be 20-20000 Hz')
    if not 0.05 <= r['duty'] <= 0.95 or not 0 <= r['arp_at'] <= 1 or r['volume'] > 1 or r['sustain_punch'] > 1:
        raise RecipeError('duty 0.05-0.95, arp_at 0-1, volume and sustain_punch 0-1')
    if r['channels'] not in (1, 2) or r['sample_rate'] not in (22050, 32000, 44100, 48000):
        raise RecipeError('channels 1 or 2; sample_rate 22050/32000/44100/48000')
    if not -48 <= r['arp_semitones'] <= 48:
        raise RecipeError('arp_semitones must be -48 to 48')
    if r['vibrato_depth'] > 24 or not 0 <= r['vibrato_hz'] <= 50:
        raise RecipeError('vibrato_depth 0-24 semitones, vibrato_hz 0-50')
    if r['peak_dbfs_max'] > 0:
        raise RecipeError('peak_dbfs_max must be <= 0')
    length = r['attack'] + r['sustain'] + r['decay']
    if not 0 < length <= MAX_SECONDS:
        raise RecipeError(f'attack+sustain+decay must be > 0 and <= {MAX_SECONDS}s')
    return r


def _envelope(t, r):
    a, s = r['attack'], r['sustain']
    if t < a:
        return t / a
    if t < a + s:
        return 1.0 + r['sustain_punch'] * (1 - (t - a) / s) if s else 1.0
    return max(0.0, 1 - (t - a - s) / r['decay']) if r['decay'] else 0.0


def render(recipe):
    r = parse(recipe)
    rate = int(r['sample_rate'])
    frames = int((r['attack'] + r['sustain'] + r['decay']) * rate)
    rng = random.Random(r['seed'])
    phase, noise, low, high_prev_in, high_prev_out, out = 0.0, rng.uniform(-1, 1), 0.0, 0.0, 0.0, []
    lp = 1 - math.exp(-2 * math.pi * r['lowpass_hz'] / rate) if r['lowpass_hz'] else 1.0
    hp = math.exp(-2 * math.pi * r['highpass_hz'] / rate) if r['highpass_hz'] else 0.0
    for i in range(frames):
        t, frac = i / rate, i / max(1, frames - 1)
        freq = r['freq_start'] * (r['freq_end'] / r['freq_start']) ** frac
        if r['arp_semitones'] and frac >= r['arp_at']:
            freq *= 2 ** (r['arp_semitones'] / 12)
        if r['vibrato_depth']:
            freq *= 2 ** (r['vibrato_depth'] * math.sin(2 * math.pi * r['vibrato_hz'] * t) / 12)
        step = min(freq, rate / 2) / rate
        phase += step
        if phase >= 1:
            phase -= int(phase)
            noise = rng.uniform(-1, 1)
        wave = r['wave']
        if wave == 'square':
            v = 1.0 if phase < r['duty'] else -1.0
        elif wave == 'saw':
            v = 2 * phase - 1
        elif wave == 'sine':
            v = math.sin(2 * math.pi * phase)
        elif wave == 'triangle':
            v = 4 * abs(phase - 0.5) - 1
        else:
            v = noise
        low += lp * (v - low)
        v = low
        if hp:
            high = hp * (high_prev_out + v - high_prev_in)
            high_prev_in, high_prev_out = v, high
            v = high
        out.append(v * _envelope(t, r) * r['volume'])
    limit = 10 ** (r['peak_dbfs_max'] / 20)
    peak = max((abs(v) for v in out), default=0.0)
    if peak > limit:
        out = [v * limit / peak for v in out]
    return [list(out) for _ in range(int(r['channels']))], rate
