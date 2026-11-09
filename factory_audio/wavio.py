"""16-bit PCM WAV with the standard library. Samples are floats in [-1, 1], one list per channel."""
from dataclasses import dataclass
import array
import sys
import wave


class WavError(ValueError):
    pass


@dataclass
class Wav:
    rate: int
    channels: int
    bits: int
    data: list  # per-channel lists of floats

    @property
    def frames(self):
        return len(self.data[0]) if self.data else 0

    @property
    def seconds(self):
        return self.frames / self.rate if self.rate else 0.0


MAX_SECONDS = 600  # longer audio is refused before its samples are loaded as floats


def wav_seconds(path):
    """Duration from the WAV header alone (no samples are read)."""
    try:
        with wave.open(str(path), 'rb') as wav:
            return wav.getnframes() / wav.getframerate() if wav.getframerate() else 0.0
    except (wave.Error, EOFError, OSError) as error:
        raise WavError(f'unreadable WAV: {error}') from error


def read_wav(path):
    try:
        with wave.open(str(path), 'rb') as wav:
            channels, width, rate, frames = wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()
            raw = wav.readframes(frames)
    except (wave.Error, EOFError, OSError) as error:
        raise WavError(f'unreadable WAV: {error}') from error
    if width != 2:
        raise WavError(f'{width * 8}-bit WAV; only 16-bit PCM is supported')
    samples = array.array('h')
    samples.frombytes(raw[:len(raw) - len(raw) % (2 * channels)])
    if sys.byteorder == 'big':
        samples.byteswap()
    data = [[value / 32768 for value in samples[c::channels]] for c in range(channels)]
    return Wav(rate, channels, 16, data)


def write_wav(path, data, rate):
    channels = len(data)
    frames = len(data[0]) if channels else 0
    if any(len(channel) != frames for channel in data):
        raise ValueError('channels differ in length')
    out = array.array('h', bytes(2 * channels * frames))
    for c, channel in enumerate(data):
        for i, value in enumerate(channel):
            out[i * channels + c] = max(-32768, min(32767, int(round(value * 32768))))
    if sys.byteorder == 'big':
        out.byteswap()
    with wave.open(str(path), 'wb') as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(out.tobytes())
