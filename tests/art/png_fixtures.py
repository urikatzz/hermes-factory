"""Build raw PNG bytes with chosen colour type, bit depth and per-row filters."""
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


def _chunk(kind, body):
    return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body))


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def _filter(row, previous, bpp, kind):
    out = bytearray([kind])
    for i, value in enumerate(row):
        left = row[i - bpp] if i >= bpp else 0
        upleft = previous[i - bpp] if i >= bpp else 0
        up = previous[i]
        predictor = [0, left, up, (left + up) // 2, _paeth(left, up, upleft)][kind]
        out.append((value - predictor) & 255)
    return out


def raw_png(width, height, ctype, depth, rows, filters=None, palette=None, trns=None, interlace=0):
    """rows: unfiltered scanline bytes, one per image row."""
    bpp = max(1, CHANNELS[ctype] * depth // 8)
    data = bytearray()
    previous = bytes(len(rows[0]))
    for index, row in enumerate(rows):
        data += _filter(bytes(row), previous, bpp, (filters or [0] * height)[index])
        previous = bytes(row)
    chunks = [_chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, depth, ctype, 0, 0, interlace))]
    if palette:
        chunks.append(_chunk(b'PLTE', bytes(c for rgb in palette for c in rgb)))
    if trns is not None:
        chunks.append(_chunk(b'tRNS', trns))
    chunks += [_chunk(b'IDAT', zlib.compress(bytes(data))), _chunk(b'IEND', b'')]
    return SIGNATURE + b''.join(chunks)
