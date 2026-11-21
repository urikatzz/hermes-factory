import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_fixtures import PALETTE, gpl, sprite, upscale_pixels
from art_production.sprite_fit import FitError, choose_coverage, components, downscale, drop_fragments, edge_contact, fit, fit_asset, fit_cover, make_sprite, opaque_fraction, quantize, remove_background
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


def dark_wall(width=512, height=256):
    """Near-flat charcoal full-bleed art with seams and slightly lighter panel faces: what a wall backdrop or floor band looks like."""
    pixels = []
    for y in range(height):
        for x in range(width):
            seam, face = (x % 128 < 3) or (y % 64 < 3), (x // 128 + y // 64) % 2 == 0
            colour = (30, 32, 36) if not seam else (14, 15, 17)
            if face:
                colour = (36, 38, 43)
            pixels.append(colour + (255,))
    return Image(width, height, pixels)


def isolated_sprite(width=128, height=128):
    """A red figure on a flat white background: a cut-out sprite."""
    return canvas(width, height, [(40, 24, 48, 80, RED), (56, 8, 16, 16, RED)])


# The asset names and criteria this project's plan gave its environment tasks; the mode must follow what each requires.
REQUIREMENTS = {
    'room01-wall-backdrop.png (painted riveted near-black and charcoal steel panels with seams and wear) covers at least +-14.7 units horizontally and +-9.0 units vertically': 'opaque',
    'room01-floor-band.png covers y -4.1 down to -9.0 across +-14.7': 'opaque',
    'full-bleed sky backdrop': 'opaque', 'seamless tileable floor tile': 'opaque', 'an opaque panorama': 'opaque',
    'room01-door-open.png (grey steel door swung open, small mesh window, hazard trim, visual height 6.7 units)': 'cutout',
    'room01-door.png (closed, source only)': 'cutout',
    'room01-platform.png (black and amber hazard face, cross-braced steel legs, amber guardrail)': 'cutout',
    'room01-wall-emblem.png (a small round emblem hung on the wall)': 'cutout',
    'dummy-idle.png crash-test dummy, tan, ball joints': 'cutout', 'hud-glyph-0.png amber stencil digit': 'cutout', 'fx-spark.png white spark burst': 'cutout',
    '': 'cutout', None: 'cutout',
}


class CoverageModeTests(unittest.TestCase):
    """A tool must not destroy a property an asset requires: full-bleed art stays opaque, isolated sprites keep their transparent background."""

    def test_dark_full_bleed_art_stays_opaque_and_keeps_its_dimensions_in_opaque_mode(self):
        sprite, report = fit_asset(dark_wall(), 256, 128, coverage='opaque')
        self.assertEqual((sprite.width, sprite.height), (256, 128))
        self.assertEqual(opaque_fraction(sprite), 1.0)
        self.assertEqual((report['coverage'], report['opaque']), ('opaque', 1.0))

    def test_the_default_cutout_mode_refuses_to_erase_full_bleed_art_and_names_the_supported_fix(self):
        with self.assertRaises(FitError) as caught:
            fit_asset(dark_wall(), 256, 128, coverage='cutout')
        diagnosis = caught.exception.diagnosis
        self.assertEqual(diagnosis['code'], 'background_removal_erased_most_of_the_image')
        self.assertEqual(diagnosis['defect'], 'tool_mode')  # a tooling defect, never an artist or generation failure
        self.assertIn('remove_background', diagnosis['transformation'])
        self.assertIn('--coverage opaque', diagnosis['fix'])
        self.assertLess(diagnosis['opaque'], 0.1)

    def test_an_isolated_sprite_keeps_its_transparent_background_in_cutout_mode(self):
        sprite, report = fit_asset(isolated_sprite(), 64, 64, coverage='cutout')
        self.assertEqual((sprite.width, sprite.height), (64, 64))
        self.assertEqual(sprite.pixels[0], CLEAR)                       # the flat background is gone
        self.assertTrue(any(p[3] == 255 and p[0] > 200 and p[1] < 60 for p in sprite.pixels))  # the figure survives
        self.assertTrue(0.05 < report['opaque'] < 0.6)

    def test_a_sparse_sprite_that_is_mostly_background_is_accepted_only_when_the_caller_says_so(self):
        sparse = canvas(128, 128, [(4, 4, 3, 3, RED), (121, 4, 3, 3, RED), (4, 121, 3, 3, RED), (121, 121, 3, 3, RED)])  # four specks far apart on a flat white field
        with self.assertRaises(FitError):
            fit_asset(sparse, 64, 64, coverage='cutout')
        sprite, _ = fit_asset(sparse, 64, 64, coverage='cutout', allow_mostly_transparent=True)
        self.assertEqual(sprite.pixels[32 * 64 + 32], CLEAR)

    def test_a_small_sprite_on_a_large_flat_background_is_not_mistaken_for_full_bleed_art(self):
        tiny = canvas(128, 128, [(60, 60, 6, 6, RED)])
        sprite, report = fit_asset(tiny, 64, 64, coverage='cutout')   # the content is cropped and scaled up: no erase diagnosis
        self.assertEqual(report['coverage'], 'cutout')

    def test_opaque_mode_never_pads_when_the_aspect_ratios_differ(self):
        # The floor band was opaque only in its middle: a 3:1 source "fitted" into a 6:1 target left transparent bars at both ends.
        wide = Image(300, 100, [(30 + x % 40, 32, 36, 255) for y in range(100) for x in range(300)])
        old = fit(wide, 600, 100)
        self.assertGreater(sum(1 for p in old.pixels if not p[3]), 0)  # the contain-fit does pad: that is the second way a full-bleed asset is destroyed
        for width, height in ((600, 100), (100, 100), (64, 128), (2048, 342)):
            with self.subTest(target=(width, height)):
                sprite, report = fit_asset(wide, width, height, coverage='opaque')
                self.assertEqual((sprite.width, sprite.height, opaque_fraction(sprite)), (width, height, 1.0))

    def test_cover_scaling_keeps_the_centre_of_the_art_and_crops_evenly(self):
        stripes = Image(8, 2, [(x * 30, 0, 0, 255) for y in range(2) for x in range(8)])    # red value encodes the source column
        square = fit_cover(stripes, 2, 2)
        self.assertEqual([p[0] for p in square.pixels[:2]], [3 * 30, 4 * 30])   # only the central two columns survive a 4:1 crop into 1:1
        same = fit_cover(stripes, 8, 2)
        self.assertEqual(same.pixels, stripes.pixels)

    def test_an_opaque_request_on_art_that_was_generated_with_holes_is_a_generation_defect_not_a_tool_defect(self):
        holes = Image(64, 64, [(0, 0, 0, 0) if y < 40 else (40, 40, 40, 255) for y in range(64) for x in range(64)])
        with self.assertRaises(FitError) as caught:
            fit_asset(holes, 32, 32, coverage='opaque')
        self.assertEqual((caught.exception.diagnosis['code'], caught.exception.diagnosis['defect']), ('source_not_opaque', 'generation'))
        self.assertIn('Regenerate', caught.exception.diagnosis['fix'])

    def test_the_fitting_mode_follows_the_asset_requirement(self):
        for text, expected in REQUIREMENTS.items():
            with self.subTest(text=str(text)[:60]):
                self.assertEqual(choose_coverage(text), expected)

    def test_the_chosen_mode_keeps_each_requirement_satisfied(self):
        for text, expected in REQUIREMENTS.items():
            if not text:
                continue
            art = dark_wall() if expected == 'opaque' else isolated_sprite()
            sprite, report = fit_asset(art, 64, 64, coverage=choose_coverage(text))
            self.assertEqual(report['coverage'], expected)
            if expected == 'opaque':
                self.assertEqual(opaque_fraction(sprite), 1.0, text)
            else:
                self.assertEqual(sprite.pixels[0], CLEAR, text)


def figure_with_specks(width=160, height=160):
    """A big red figure plus a few detached specks, on a flat white background."""
    return canvas(width, height, [(30, 10, 100, 140, RED), (4, 4, 3, 3, RED), (150, 150, 4, 4, RED), (140, 20, 6, 6, RED)])


class EdgeAndFragmentTests(unittest.TestCase):
    """The technical check reads opaque pixels on the canvas border as a crop and detached groups as stray fragments: the tool reports both and can prevent them."""

    def test_a_margin_keeps_the_sprite_off_every_canvas_edge_and_zero_fills_the_canvas(self):
        sprite, report = fit_asset(figure_with_specks(), 64, 64, coverage='cutout', margin=2)
        self.assertEqual(edge_contact(sprite), dict(left=False, right=False, top=False, bottom=False))
        self.assertEqual((sprite.width, sprite.height), (64, 64))
        flush, flush_report = fit_asset(figure_with_specks(), 64, 64, coverage='cutout', margin=0)
        self.assertTrue(any(edge_contact(flush).values()))                              # the old behaviour: content fills the canvas and touches its edges
        self.assertTrue(any(flush_report['edge_contact'].values()))

    def test_detached_fragments_are_reported_with_their_size_and_place(self):
        _, report = fit_asset(figure_with_specks(), 64, 64, coverage='cutout', margin=2)
        self.assertGreaterEqual(report['fragment_count'], 1)
        self.assertTrue(all({'px', 'bbox'} <= set(f) for f in report['fragments']))
        clean, clean_report = fit_asset(canvas(160, 160, [(30, 10, 100, 140, RED)]), 64, 64, coverage='cutout', margin=2)
        self.assertEqual((clean_report['fragment_count'], clean_report['fragments']), (0, []))

    def test_dropping_fragments_clears_the_small_groups_and_never_the_largest(self):
        sprite, _ = fit_asset(figure_with_specks(), 64, 64, coverage='cutout', margin=2)
        before = components(sprite)
        cleared, removed = drop_fragments(sprite, before[0]['px'] + 1)                   # even a threshold above the largest group never removes the largest
        self.assertEqual(len(components(cleared)), 1)
        self.assertEqual(components(cleared)[0]['px'], before[0]['px'])
        self.assertEqual(len(removed), len(before) - 1)
        kept, none = drop_fragments(sprite, 1)                                           # nothing is below one pixel
        self.assertEqual((kept.pixels, none), (sprite.pixels, []))
        self.assertEqual(drop_fragments(sprite, 0)[1], [])                               # 0 disables

    def test_dropping_only_the_tiny_groups_keeps_a_larger_separate_part(self):
        art = canvas(160, 160, [(20, 10, 90, 140, RED), (120, 60, 30, 30, RED), (2, 2, 2, 2, RED)])
        sprite, _ = fit_asset(art, 80, 80, coverage='cutout', margin=2)
        groups = components(sprite)
        threshold = (groups[1]['px'] + groups[2]['px']) // 2 if len(groups) > 2 else groups[-1]['px']
        cleared, removed = drop_fragments(sprite, threshold)
        self.assertEqual(len(components(cleared)), len(groups) - len(removed))
        self.assertGreaterEqual(len(components(cleared)), 2 if len(groups) > 2 else 1)

    def test_opaque_mode_is_unaffected_by_margin_and_fragment_options(self):
        sprite, report = fit_asset(dark_wall(), 128, 64, coverage='opaque', margin=2, drop_fragments_below=500)
        self.assertEqual(opaque_fraction(sprite), 1.0)
        self.assertNotIn('fragments', report)


class EdgeAndFragmentCommandLineTests(unittest.TestCase):
    def run_fit(self, image, *arguments):
        folder = tempfile.mkdtemp()
        source, out = Path(folder) / 'in.png', Path(folder) / 'out.png'
        write_png(source, image)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), str(source), str(out), '--size', '64x64', *arguments], capture_output=True, text=True)
        return done, out

    def test_the_cli_keeps_a_two_pixel_margin_by_default_and_reports_edges_and_fragments(self):
        done, out = self.run_fit(figure_with_specks())
        report = json.loads(done.stdout)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(report['margin'], 2); self.assertFalse(any(report['edge_contact'].values()))
        self.assertGreaterEqual(report['fragment_count'], 1)
        self.assertFalse(any(edge_contact(read_png(out)).values()))

    def test_the_cli_can_drop_fragments_and_can_disable_the_margin(self):
        done, out = self.run_fit(figure_with_specks(), '--drop-fragments-below', '10000', '--margin', '0')
        report = json.loads(done.stdout)
        self.assertEqual((report['fragment_count'], report['margin']), (0, 0))
        self.assertGreaterEqual(report['dropped_fragments'], 1)
        self.assertEqual(len(components(read_png(out))), 1)


class CoverageCommandLineTests(unittest.TestCase):
    def run_fit(self, image, *arguments):
        folder = tempfile.mkdtemp()
        source, out = Path(folder) / 'in.png', Path(folder) / 'out.png'
        write_png(source, image)
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_fit.py'), str(source), str(out), '--size', '64x32', *arguments], capture_output=True, text=True)
        return done, out

    def test_opaque_mode_writes_an_opaque_file_of_the_requested_size(self):
        done, out = self.run_fit(dark_wall(), '--coverage', 'opaque')
        self.assertEqual(done.returncode, 0, done.stderr)
        report, written = json.loads(done.stdout), read_png(out)
        self.assertEqual((report['ok'], report['coverage'], report['opaque']), (True, 'opaque', 1.0))
        self.assertEqual((written.width, written.height, opaque_fraction(written)), (64, 32, 1.0))

    def test_the_legacy_keep_background_flag_still_means_opaque(self):
        done, out = self.run_fit(dark_wall(), '--keep-background')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(opaque_fraction(read_png(out)), 1.0)

    def test_default_mode_on_full_bleed_art_exits_3_with_an_actionable_diagnosis_and_writes_nothing(self):
        done, out = self.run_fit(dark_wall())
        self.assertEqual(done.returncode, 3)
        diagnosis = json.loads(done.stdout)
        self.assertEqual((diagnosis['ok'], diagnosis['defect']), (False, 'tool_mode'))
        self.assertIn('--coverage opaque', done.stderr)
        self.assertFalse(out.exists())

    def test_auto_mode_chooses_from_the_hint_for_both_kinds_of_asset(self):
        done, out = self.run_fit(dark_wall(), '--coverage', 'auto', '--hint', 'room01-wall-backdrop.png covers at least +-14.7 units')
        self.assertEqual((done.returncode, json.loads(done.stdout)['coverage']), (0, 'opaque'), done.stderr)
        done, out = self.run_fit(isolated_sprite(), '--coverage', 'auto', '--hint', 'room01-door.png closed door')
        self.assertEqual((done.returncode, json.loads(done.stdout)['coverage']), (0, 'cutout'), done.stderr)
        self.assertEqual(read_png(out).pixels[0], CLEAR)


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
