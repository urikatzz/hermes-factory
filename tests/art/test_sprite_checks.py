import unittest

from art_fixtures import PALETTE, sprite, upscale_pixels
from factory_art.png import Image
from factory_art.sprite_checks import check_sprite, upscale_factor

CLASS = {'size': {'width': [16, 64], 'height': [16, 64], 'multiple_of': 16}, 'alpha': 'required',
         'pixel_art': True, 'palette': {'file': 'p.gpl', 'tolerance': 4}, '_palette': PALETTE}


def checks(image, cls=CLASS):
    return [(f['severity'], f['check']) for f in check_sprite('a.png', image, cls)]


class SpriteTests(unittest.TestCase):
    def test_good_sprite_has_no_findings(self):
        self.assertEqual(checks(sprite()), [])

    def test_size_range_and_multiple(self):
        self.assertEqual(checks(sprite(96)), [('HIGH', 'size'), ('HIGH', 'size')])
        self.assertEqual(checks(sprite(24)), [('HIGH', 'size')])

    def test_alpha_required(self):
        self.assertEqual(checks(sprite(opaque=True)), [('HIGH', 'alpha')])

    def test_semi_transparent_edges(self):
        image = sprite()
        pixels = list(image.pixels)
        pixels[16 * 32 + 16] = pixels[16 * 32 + 16][:3] + (128,)
        self.assertEqual(checks(Image(32, 32, pixels)), [('MEDIUM', 'pixel_art_edges')])

    def test_upscaled_pixel_art(self):
        self.assertEqual(upscale_factor(upscale_pixels(sprite(16), 4)), 4)
        self.assertEqual(upscale_factor(sprite()), 1)
        self.assertEqual(checks(upscale_pixels(sprite(16), 2)), [('MEDIUM', 'pixel_art_scale')])

    def test_off_palette_within_and_beyond_tolerance(self):
        image = sprite()
        pixels = list(image.pixels)
        pixels[16 * 32 + 16] = (203, 57, 63, 255)   # within 4 of (200, 60, 60)
        self.assertEqual(checks(Image(32, 32, pixels)), [])
        pixels[16 * 32 + 17] = (255, 0, 255, 255)
        found = check_sprite('a.png', Image(32, 32, pixels), CLASS)
        self.assertEqual([(f['check'], f['problem']) for f in found],
                         [('palette', '1 colours off palette (tolerance 4), e.g. #ff00ff')])

    def test_unconfigured_checks_are_skipped(self):
        self.assertEqual(checks(sprite(opaque=True), {}), [])
