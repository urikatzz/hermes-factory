import struct
import tempfile
import unittest
from pathlib import Path

from factory_art.png import Image, PngError, decode_png, encode_png, read_png, write_png
from png_fixtures import SIGNATURE, _chunk, raw_png

RGB_ROWS = [bytes([10, 20, 30, 200, 100, 50, 0, 255, 128]),
            bytes([12, 22, 32, 190, 110, 40, 5, 250, 120]),
            bytes([255, 0, 0, 0, 255, 0, 0, 0, 255])]
RGB_PIXELS = [tuple(row[i:i + 3]) + (255,) for row in RGB_ROWS for i in range(0, 9, 3)]


class PngTests(unittest.TestCase):
    def test_round_trip_rgba(self):
        image = Image(2, 2, [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 0), (255, 255, 255, 255)])
        self.assertEqual(decode_png(encode_png(image)), image)

    def test_every_filter_type_decodes(self):
        for kind in range(5):
            with self.subTest(filter=kind):
                data = raw_png(3, 3, 2, 8, RGB_ROWS, filters=[kind, kind, kind])
                self.assertEqual(decode_png(data).pixels, RGB_PIXELS)

    def test_mixed_filters_decode(self):
        data = raw_png(3, 3, 2, 8, RGB_ROWS, filters=[4, 2, 3])
        self.assertEqual(decode_png(data).pixels, RGB_PIXELS)

    def test_indexed_8bit_with_transparency(self):
        palette = [(0, 0, 0), (200, 10, 10)]
        data = raw_png(2, 1, 3, 8, [bytes([0, 1])], palette=palette, trns=bytes([0]))
        self.assertEqual(decode_png(data).pixels, [(0, 0, 0, 0), (200, 10, 10, 255)])

    def test_indexed_4bit_ignores_row_padding(self):
        palette = [(1, 1, 1), (2, 2, 2), (3, 3, 3)]
        data = raw_png(3, 1, 3, 4, [bytes([0x01, 0x20])], palette=palette)
        self.assertEqual(decode_png(data).pixels, [(1, 1, 1, 255), (2, 2, 2, 255), (3, 3, 3, 255)])

    def test_grey_and_grey_alpha(self):
        self.assertEqual(decode_png(raw_png(1, 1, 0, 8, [bytes([7])])).pixels, [(7, 7, 7, 255)])
        self.assertEqual(decode_png(raw_png(1, 1, 4, 8, [bytes([7, 9])])).pixels, [(7, 7, 7, 9)])

    def test_rgb_transparency_key(self):
        data = raw_png(2, 1, 2, 8, [bytes([1, 2, 3, 4, 5, 6])], trns=struct.pack('>HHH', 1, 2, 3))
        self.assertEqual(decode_png(data).pixels, [(1, 2, 3, 0), (4, 5, 6, 255)])

    def test_rejects_unsupported_and_corrupt_files(self):
        cases = {
            '16-bit': raw_png(1, 1, 2, 16, [bytes(6)]),
            'interlaced': raw_png(1, 1, 2, 8, [bytes(3)], interlace=1),
            'not png': b'GIF89a',
            'bad crc': raw_png(1, 1, 2, 8, [bytes(3)])[:-1] + b'\x00',
            'short ihdr': SIGNATURE + _chunk(b'IHDR', b'\x00' * 12),
            'zero width': raw_png(0, 1, 2, 8, [b'']),
        }
        for name, data in cases.items():
            with self.subTest(case=name), self.assertRaises(PngError):
                decode_png(data)
        huge = SIGNATURE + _chunk(b'IHDR', struct.pack('>IIBBBBB', 5000, 5000, 8, 6, 0, 0, 0))
        with self.assertRaisesRegex(PngError, 'image too large'):
            decode_png(huge)

    def test_read_and_write_files(self):
        image = Image(1, 1, [(9, 8, 7, 6)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'a.png'
            write_png(path, image)
            self.assertEqual(read_png(path), image)
