"""Minimal standard-library PNG codec: 8-bit grey/RGB/RGBA, 1-8 bit indexed, non-interlaced."""
from dataclasses import dataclass
from pathlib import Path
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
MAX_PIXELS = 16_777_216


class PngError(ValueError):
    pass


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    pixels: list  # row-major (r, g, b, a) tuples


def read_png(path):
    return decode_png(Path(path).read_bytes())


def write_png(path, image):
    Path(path).write_bytes(encode_png(image))


def decode_png(data):
    if not data.startswith(SIGNATURE):
        raise PngError('not a PNG file')
    header, palette, trns, idat = None, [], b'', []
    position = len(SIGNATURE)
    while position + 8 <= len(data):
        length, kind = struct.unpack('>I4s', data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        crc = data[position + 8 + length:position + 12 + length]
        if len(body) != length or len(crc) != 4:
            raise PngError('truncated chunk')
        if zlib.crc32(kind + body) != struct.unpack('>I', crc)[0]:
            raise PngError(f'bad CRC in {kind.decode("latin-1")} chunk')
        position += 12 + length
        if kind == b'IHDR':
            if length != 13:
                raise PngError('bad IHDR length')
            header = struct.unpack('>IIBBBBB', body)
        elif kind == b'PLTE':
            palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif kind == b'tRNS':
            trns = body
        elif kind == b'IDAT':
            idat.append(body)
        elif kind == b'IEND':
            break
    if header is None:
        raise PngError('missing IHDR chunk')
    width, height, depth, ctype, _, _, interlace = header
    if not width or not height:
        raise PngError('image has zero width or height')
    if width * height > MAX_PIXELS:
        raise PngError('image too large')
    if interlace:
        raise PngError('interlaced PNG is not supported')
    if ctype not in CHANNELS:
        raise PngError(f'unknown colour type {ctype}')
    if depth != 8 and not (ctype == 3 and depth in (1, 2, 4)):
        raise PngError(f'bit depth {depth} with colour type {ctype} is not supported')
    if ctype == 3 and not palette:
        raise PngError('indexed PNG without a palette')
    try:
        raw = zlib.decompress(b''.join(idat))
    except zlib.error as error:
        raise PngError(f'corrupt image data: {error}') from error
    bits = CHANNELS[ctype] * depth
    stride = (width * bits + 7) // 8
    if len(raw) != height * (stride + 1):
        raise PngError('image data size does not match the header')
    pixels = []
    for row in _unfilter(raw, stride, height, max(1, bits // 8)):
        pixels.extend(_row_pixels(row, width, depth, ctype, palette, trns))
    return Image(width, height, pixels)


def encode_png(image):
    raw = bytearray()
    for y in range(image.height):
        raw.append(0)
        for pixel in image.pixels[y * image.width:(y + 1) * image.width]:
            raw.extend(pixel)
    header = struct.pack('>IIBBBBB', image.width, image.height, 8, 6, 0, 0, 0)
    return SIGNATURE + _chunk(b'IHDR', header) + _chunk(b'IDAT', zlib.compress(bytes(raw))) + _chunk(b'IEND', b'')


def _chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _unfilter(raw, stride, height, bpp):
    rows, previous = [], bytearray(stride)
    for y in range(height):
        start = y * (stride + 1)
        kind, row = raw[start], bytearray(raw[start + 1:start + 1 + stride])
        if kind > 4:
            raise PngError(f'bad filter type {kind}')
        if kind:
            for i in range(stride):
                left = row[i - bpp] if i >= bpp else 0
                up = previous[i]
                if kind == 1:
                    row[i] = (row[i] + left) & 255
                elif kind == 2:
                    row[i] = (row[i] + up) & 255
                elif kind == 3:
                    row[i] = (row[i] + (left + up) // 2) & 255
                else:
                    row[i] = (row[i] + _paeth(left, up, previous[i - bpp] if i >= bpp else 0)) & 255
        rows.append(row)
        previous = row
    return rows


def _row_pixels(row, width, depth, ctype, palette, trns):
    if ctype == 3:
        if depth == 8:
            indices = row[:width]
        else:
            mask = (1 << depth) - 1
            indices = [(byte >> shift) & mask for byte in row for shift in range(8 - depth, -1, -depth)][:width]
        pixels = []
        for index in indices:
            if index >= len(palette):
                raise PngError('palette index out of range')
            pixels.append(palette[index] + (trns[index] if index < len(trns) else 255,))
        return pixels
    channels = CHANNELS[ctype]
    groups = [tuple(row[i:i + channels]) for i in range(0, width * channels, channels)]
    if ctype == 6:
        return groups
    if ctype == 4:
        return [(v, v, v, a) for v, a in groups]
    if ctype == 2:
        key = struct.unpack('>HHH', trns) if len(trns) == 6 else None
        return [group + (0 if group == key else 255,) for group in groups]
    key = struct.unpack('>H', trns)[0] if len(trns) == 2 else None
    return [(v, v, v, 0 if v == key else 255) for (v,) in groups]
