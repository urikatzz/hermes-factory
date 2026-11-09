"""Sample-level measures on per-channel float lists."""
import math

SILENCE = 10 ** (-60 / 20)  # -60 dBFS
FULL_SCALE = 32767 / 32768


def peak_dbfs(data):
    peak = max((abs(v) for channel in data for v in channel), default=0.0)
    return 20 * math.log10(peak) if peak > 0 else float('-inf')


def clip_runs(data, run=3):
    """Number of runs of `run` or more consecutive samples at full scale."""
    count = 0
    for channel in data:
        length = 0
        for value in channel:
            if abs(value) >= FULL_SCALE:
                length += 1
                if length == run:
                    count += 1
            else:
                length = 0
    return count


def dc_offset(data):
    values = [v for channel in data for v in channel]
    return sum(values) / len(values) if values else 0.0


def edge_silence_ms(data, rate):
    frames = len(data[0]) if data else 0
    loud = [i for i in range(frames) if any(abs(channel[i]) > SILENCE for channel in data)]
    if not loud:
        return frames * 1000 / rate, frames * 1000 / rate
    return loud[0] * 1000 / rate, (frames - 1 - loud[-1]) * 1000 / rate


def _rms(values):
    return math.sqrt(sum(v * v for v in values) / len(values)) if values else 0.0


def loop_seam(data, rate, window_ms=20):
    """jump: largest last->first sample step relative to the typical step near the seam; rms_ratio_db: level change."""
    window = max(2, int(rate * window_ms / 1000))
    jump, ratio = 0.0, 0.0
    for channel in data:
        if len(channel) < 2 * window:
            continue
        tail, head = channel[-window:], channel[:window]
        steps = [abs(b - a) for a, b in zip(tail, tail[1:])] + [abs(b - a) for a, b in zip(head, head[1:])]
        typical = max(sorted(steps)[len(steps) // 2], 1e-4)
        jump = max(jump, abs(head[0] - tail[-1]) - typical)
        a, b = _rms(tail), _rms(head)
        if a > SILENCE and b > SILENCE:
            ratio = max(ratio, abs(20 * math.log10(a / b)))
    return {'jump': round(max(jump, 0.0), 4), 'rms_ratio_db': round(ratio, 2)}
