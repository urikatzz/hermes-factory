import tempfile
import unittest
from pathlib import Path

from factory_art.png import Image, read_png, write_png
from factory_art.views import composite, contact_sheet, sprite_views, tile, upscale

RED, CLEAR = (255, 0, 0, 255), (0, 0, 0, 0)


class ViewTests(unittest.TestCase):
    def test_upscale_is_nearest_neighbour(self):
        self.assertEqual(upscale(Image(2, 1, [RED, CLEAR]), 2).pixels, [RED, RED, CLEAR, CLEAR] * 2)

    def test_composite_blends_alpha_over_background(self):
        image = composite(Image(2, 1, [(255, 255, 255, 128), CLEAR]), (0, 0, 0))
        self.assertEqual(image.pixels, [(128, 128, 128, 255), (0, 0, 0, 255)])

    def test_tile_fills_missing_cells(self):
        image = tile([Image(1, 1, [RED])] * 3, 2)
        self.assertEqual((image.width, image.height, image.pixels), (2, 2, [RED, RED, RED, CLEAR]))

    def test_sprite_views_writes_three_backgrounds_capped_at_1024(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = sprite_views(Image(300, 2, [RED] * 600), Path(temp) / 'v')
            self.assertEqual([Path(p).name for p in paths], ['transparent.png', 'grey.png', 'dark.png'])
            self.assertEqual(read_png(paths[0]).width, 900)

    def test_contact_sheet(self):
        with tempfile.TemporaryDirectory() as temp:
            parts = []
            for index in range(4):
                parts.append(Path(temp) / f'{index}.png')
                write_png(parts[-1], Image(2, 2, [RED] * 4))
            sheet = contact_sheet(parts, Path(temp) / 'contact.png')
            self.assertEqual(read_png(sheet).width, 4)
