import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import PALETTE, gpl, sprite, upscale_pixels
from art_production.sprite_fit import downscale, fit, make_sprite, quantize, remove_background
from factory_art.png import Image, read_png, write_png
from factory_art.sprite_checks import check_sprite

WHITE, RED, CLEAR = (255, 255, 255, 255), (250, 10, 10, 255), (0, 0, 0, 0)


def canvas(width, height, rects):
    """White image with (left, top, width, height, colour) rectangles painted on it."""
    pixels = [WHITE] * (width * height)
    for left, top, w, h, colour in rects:
        for y in range(top, top + h):
            for x in range(left, left + w):
                pixels[y * width + x] = colour
    return Image(width, height, pixels)


class SpriteFitTests(unittest.TestCase):
    def test_background_connected_to_the_border_becomes_transparent(self):
        ring = canvas(8, 8, [(2, 2, 4, 4, RED), (3, 3, 2, 2, WHITE)])
        result = remove_background(ring)
        self.assertEqual(result.pixels[0], CLEAR)
        self.assertEqual(result.pixels[2 * 8 + 2], RED)
        self.assertEqual(result.pixels[3 * 8 + 3], WHITE)  # enclosed white is part of the sprite

    def test_images_with_alpha_keep_their_alpha(self):
        image = sprite(16)
        self.assertEqual(remove_background(image).pixels, image.pixels)

    def test_nearest_neighbour_downscale_recovers_an_upscaled_sprite(self):
        original = sprite(16, opaque=True)
        self.assertEqual(downscale(upscale_pixels(original, 4), 16, 16).pixels, original.pixels)

    def test_fit_keeps_aspect_ratio_and_centres_on_transparency(self):
        result = fit(remove_background(canvas(40, 20, [(10, 5, 20, 10, RED)])), 16, 16)
        self.assertEqual((result.width, result.height), (16, 16))
        rows = [result.pixels[y * 16:(y + 1) * 16] for y in range(16)]
        self.assertTrue(all(pixel == CLEAR for row in rows[:4] + rows[12:] for pixel in row))
        self.assertTrue(all(pixel == RED for row in rows[4:12] for pixel in row))

    def test_quantize_maps_visible_pixels_to_the_nearest_palette_colour(self):
        result = quantize(Image(2, 1, [RED, CLEAR]), PALETTE)
        self.assertEqual(result.pixels, [(200, 60, 60, 255), CLEAR])

    def test_fully_transparent_input_is_an_error(self):
        with self.assertRaisesRegex(ValueError, 'no visible pixels'):
            make_sprite(Image(4, 4, [CLEAR] * 16), 4, 4)

    def test_cli_output_passes_the_sprite_checks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_png(root / 'concept.png', canvas(64, 64, [(16, 8, 32, 48, RED), (24, 16, 16, 8, (40, 110, 210, 255))]))
            (root / 'palette.gpl').write_text(gpl(PALETTE))
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), str(root / 'concept.png'),
                                     str(root / 'out/hero.png'), '--size', '32x32', '--palette', str(root / 'palette.gpl')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['palette'], 4)
            image = read_png(root / 'out/hero.png')
            cls = {'size': {'width': [32, 32], 'height': [32, 32]}, 'alpha': 'required', 'pixel_art': True,
                   'palette': {'file': 'palette.gpl', 'tolerance': 0}, '_palette': PALETTE}
            self.assertEqual(check_sprite('hero.png', image, cls), [])

    def test_cli_rejects_a_bad_size(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), 'a.png', 'b.png', '--size', '32'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('WIDTHxHEIGHT', result.stderr)
