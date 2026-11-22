import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_production.sheet import SheetError, cell, detect_items, item_filename, slice_by_detection, slice_sheet
from factory_art.png import Image, read_png, write_png

WHITE, RED, BLUE, GREEN = (255, 255, 255, 255), (220, 30, 30, 255), (30, 30, 220, 255), (30, 200, 30, 255)


def sheet(columns=3, rows=2, cell_size=60, items=None, fill=None):
    """A flat white sheet with one coloured block per cell (cells in `items` order: a colour, or None for an empty cell)."""
    width, height = columns * cell_size, rows * cell_size
    pixels = [WHITE] * (width * height)
    for index in range(columns * rows):
        colour = (items or [RED, BLUE, GREEN, RED, BLUE, GREEN])[index]
        if colour is None:
            continue
        row, column = divmod(index, columns)
        for y in range(row * cell_size + 15, row * cell_size + 45):
            for x in range(column * cell_size + 15, column * cell_size + 45):
                pixels[y * width + x] = colour
    return Image(width, height, pixels)


class SheetSlicingTests(unittest.TestCase):
    def test_every_cell_becomes_its_own_named_sprite_in_grid_order(self):
        done = slice_sheet(sheet(), 3, 2, ['A', 'B', 'C', 'D', 'E', 'F'], (32, 32), prefix='g-')
        self.assertEqual([f for _, f, _, _ in done], ['g-A.png', 'g-B.png', 'g-C.png', 'g-D.png', 'g-E.png', 'g-F.png'])
        colours = [next(p for p in sprite.pixels if p[3])[:3] for _, _, sprite, _ in done]
        self.assertEqual(colours, [RED[:3], BLUE[:3], GREEN[:3], RED[:3], BLUE[:3], GREEN[:3]])      # left to right, then top to bottom
        self.assertTrue(all((s.width, s.height) == (32, 32) for _, _, s, _ in done))

    def test_each_sprite_is_a_cutout_with_a_margin_and_no_edge_contact(self):
        for _, _, sprite, report in slice_sheet(sheet(), 3, 2, list('ABCDEF'), (32, 32)):
            self.assertEqual(sprite.pixels[0][3], 0)                                                   # the flat background is gone
            self.assertFalse(any(report['edge_contact'].values()))
            self.assertEqual(report['margin'], 2)

    def test_special_characters_get_safe_file_names_and_unnameable_ones_are_refused(self):
        self.assertEqual([item_filename(c, 'x-') for c in ['A', '7', '-', ' ', '.']], ['x-A.png', 'x-7.png', 'x-hyphen.png', 'x-space.png', 'x-fullstop.png'])
        for bad in ('é', '*', '../a', 'AB CD', ''):
            with self.assertRaises(SheetError):
                item_filename(bad)

    def test_an_intentionally_empty_space_cell_is_a_transparent_sprite_and_any_other_empty_cell_is_an_error(self):
        items = [RED, None, GREEN, RED, BLUE, GREEN]
        done = slice_sheet(sheet(items=items), 3, 2, ['A', ' ', 'C', 'D', 'E', 'F'], (32, 32))
        space = done[1]
        self.assertEqual(space[1], 'space.png'); self.assertTrue(space[3]['blank']); self.assertTrue(all(p[3] == 0 for p in space[2].pixels))
        with self.assertRaises(SheetError) as caught:
            slice_sheet(sheet(items=items), 3, 2, ['A', 'B', 'C', 'D', 'E', 'F'], (32, 32))
        self.assertIn('cell 2,1', str(caught.exception)); self.assertIn('Regenerate the sheet', str(caught.exception))

    def test_the_item_count_must_match_the_grid_exactly(self):
        for names in (list('ABCDE'), list('ABCDEFG')):
            with self.assertRaises(SheetError) as caught:
                slice_sheet(sheet(), 3, 2, names, (32, 32))
            self.assertIn('must match one to one', str(caught.exception))
        with self.assertRaises(SheetError):
            slice_sheet(sheet(), 3, 2, list('AABCDE'), (32, 32))                                       # two names that map to one file

    def test_a_neighbours_edge_never_leaks_into_a_cell(self):
        wide = sheet(items=[RED, BLUE, GREEN, RED, BLUE, GREEN])
        piece = cell(wide, 1, 0, 3, 2)
        self.assertTrue(all(p == WHITE for p in piece.pixels[:5]))                                      # the trimmed cell starts on background

    def test_stray_specks_in_a_cell_can_be_cleared_without_touching_the_glyph(self):
        speck = sheet()
        pixels = list(speck.pixels)
        for y in range(2, 6):
            for x in range(2, 6):
                pixels[y * speck.width + x] = RED                                                       # a speck in the first cell's corner
        marked = Image(speck.width, speck.height, pixels)
        _, _, kept, report = slice_sheet(marked, 3, 2, list('ABCDEF'), (64, 64), inset=0.0)[0]
        self.assertGreaterEqual(report['fragment_count'], 1)
        _, _, cleared, clean_report = slice_sheet(marked, 3, 2, list('ABCDEF'), (64, 64), inset=0.0, drop_fragments_below=400)[0]
        self.assertEqual(clean_report['fragment_count'], 0)
        self.assertGreater(sum(1 for p in cleared.pixels if p[3]), 100)


def scattered_sheet(placements, width=400, height=300):
    """A flat white sheet with coloured blocks at arbitrary places (not on grid lines): placements = [(x, y, w, h, colour)]."""
    pixels = [WHITE] * (width * height)
    for x, y, w, h, colour in placements:
        for j in range(y, y + h):
            for i in range(x, x + w):
                pixels[j * width + i] = colour
    return Image(width, height, pixels)


# Items on two rows with uneven spacing and a slight vertical drift: what an image model really draws.
UNEVEN = [(12, 20, 40, 50, RED), (90, 28, 44, 46, BLUE), (200, 18, 38, 52, GREEN), (310, 24, 42, 48, RED),
          (30, 150, 44, 50, BLUE), (130, 158, 40, 46, GREEN), (260, 146, 46, 54, RED)]


class DetectionTests(unittest.TestCase):
    def test_items_are_found_where_they_are_and_ordered_in_rows_then_left_to_right(self):
        boxes = detect_items(scattered_sheet(UNEVEN), 4, 7)
        self.assertEqual([b[0] for b in boxes], [12, 90, 200, 310, 30, 130, 260])                         # row one left to right, then row two
        self.assertEqual(len(boxes), 7)

    def test_a_grid_cutter_would_cut_these_cells_wrongly_but_detection_does_not(self):
        sheet_image = scattered_sheet(UNEVEN)
        done = slice_by_detection(sheet_image, 4, list('ABCDEFG'), (32, 32))
        colours = [next(p for p in sprite.pixels if p[3])[:3] for _, _, sprite, _ in done]
        self.assertEqual(colours, [RED[:3], BLUE[:3], GREEN[:3], RED[:3], BLUE[:3], GREEN[:3], RED[:3]])
        self.assertTrue(all(not any(r['edge_contact'].values()) for _, _, _, r in done))

    def test_the_parts_of_one_item_are_merged_by_the_gap_and_neighbours_are_not(self):
        parts = [(20, 40, 16, 40, RED), (20, 24, 16, 10, RED), (120, 40, 30, 40, BLUE)]                  # an i-like item: a stem and a dot 6 px above it
        with self.assertRaises(SheetError):
            detect_items(scattered_sheet(parts, 300, 150), 2, 2)                                        # the default gap of a small sheet is 2 px: the dot stays separate
        boxes = detect_items(scattered_sheet(parts, 300, 150), 2, 2, gap=8)
        self.assertEqual(len(boxes), 2); self.assertEqual(boxes[0][1], 24)                              # the dot joined the stem
        self.assertEqual(boxes[1][0], 120)

    def test_a_blank_name_needs_no_item_and_becomes_a_transparent_sprite(self):
        sheet_image = scattered_sheet(UNEVEN[:3], 400, 100)
        done = slice_by_detection(sheet_image, 3, ['A', ' ', 'B', 'C'], (24, 24), prefix='g-')
        self.assertEqual([f for _, f, _, _ in done], ['g-A.png', 'g-space.png', 'g-B.png', 'g-C.png'])
        self.assertTrue(done[1][3]['blank']); self.assertTrue(all(p[3] == 0 for p in done[1][2].pixels))
        self.assertTrue(any(p[3] for p in done[2][2].pixels))

    def test_a_wrong_item_count_lists_what_was_found_so_the_sheet_can_be_fixed(self):
        with self.assertRaises(SheetError) as caught:
            slice_by_detection(scattered_sheet(UNEVEN), 4, list('ABCDEFGH'), (32, 32))
        self.assertIn('found 7 separate items on the sheet but 8 were expected', str(caught.exception)); self.assertIn('(12,20)', str(caught.exception))
        with self.assertRaises(SheetError):
            detect_items(scattered_sheet(UNEVEN), 4, 6)

    def test_touching_neighbours_merge_into_one_item_and_the_error_says_so(self):
        touching = [(20, 20, 40, 40, RED), (60, 20, 40, 40, BLUE), (150, 20, 40, 40, GREEN)]
        with self.assertRaises(SheetError) as caught:
            detect_items(scattered_sheet(touching, 300, 100), 3, 3)
        self.assertIn('found 2 separate items', str(caught.exception))
        self.assertEqual(len(detect_items(scattered_sheet(touching, 300, 100), 3, 2)), 2)


class DetectionCommandLineTests(unittest.TestCase):
    def run_cli(self, placements, *arguments, width=400, height=300):
        folder = Path(tempfile.mkdtemp())
        write_png(folder / 'sheet.png', scattered_sheet(placements, width, height))
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_sheet.py'), str(folder / 'sheet.png'), str(folder / 'out'), *arguments], capture_output=True, text=True)
        return done, folder

    def test_the_cli_slices_an_uneven_sheet_by_default(self):
        done, folder = self.run_cli(UNEVEN, '--grid', '4x2', '--names', 'A,B,C,D,E,F,G', '--size', '32x32')
        report = json.loads(done.stdout)
        self.assertEqual((done.returncode, report['count'], report['needs_attention']), (0, 7, []), done.stderr)
        self.assertEqual(sorted(p.name for p in (folder / 'out').iterdir()), [f'{c}.png' for c in 'ABCDEFG'])

    def test_auto_falls_back_to_the_grid_for_an_even_sheet_and_the_error_names_both_attempts(self):
        done, _ = self.run_cli(UNEVEN, '--grid', '4x2', '--names', 'A,B,C', '--size', '32x32')
        self.assertEqual(done.returncode, 3)
        self.assertIn('detect:', done.stderr); self.assertIn('grid:', done.stderr)
        done, _ = self.run_cli([(15 + 100 * (i % 4), 15 + 150 * (i // 4), 40, 40, RED) for i in range(8)], '--grid', '4x2', '--names', 'A,B,C,D,E,F,G,H', '--size', '32x32', '--align', 'grid')
        self.assertEqual(done.returncode, 0, done.stderr)


class SheetCommandLineTests(unittest.TestCase):
    def run_cli(self, *arguments):
        folder = Path(tempfile.mkdtemp())
        write_png(folder / 'sheet.png', sheet())
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_sheet.py'), str(folder / 'sheet.png'), str(folder / 'out'), *arguments], capture_output=True, text=True)
        return done, folder

    def test_the_cli_writes_the_sprites_and_the_metadata_file(self):
        folder = Path(tempfile.mkdtemp()); meta_path = folder / 'meta' / 'set.json'
        write_png(folder / 'sheet.png', sheet())
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_sheet.py'), str(folder / 'sheet.png'), str(folder / 'out'), '--grid', '3x2', '--names', 'A,B,C,D,E,F', '--size', '32x32',
                               '--prefix', 'glyph-', '--metadata', str(meta_path)], capture_output=True, text=True)
        report = json.loads(done.stdout)
        self.assertEqual((done.returncode, report['ok'], report['count']), (0, True, 6), done.stderr)
        self.assertEqual(sorted(p.name for p in (folder / 'out').iterdir()), [f'glyph-{c}.png' for c in 'ABCDEF'])
        meta = json.loads(meta_path.read_text())
        self.assertEqual((meta['schema'], meta['size'], len(meta['items'])), ('factory-sprite-set/v1', dict(width=32, height=32), 6))
        self.assertEqual(report['needs_attention'], [])
        self.assertEqual(read_png(folder / 'out/glyph-A.png').width, 32)

    def test_a_wrong_item_count_is_exit_3_with_the_reason_and_nothing_is_written(self):
        done, folder = self.run_cli('--grid', '3x2', '--names', 'A,B,C', '--size', '32x32')
        self.assertEqual(done.returncode, 3); self.assertFalse(json.loads(done.stdout)['ok']); self.assertIn('must match one to one', done.stderr)
        self.assertFalse((folder / 'out').exists())

    def test_the_names_file_supports_the_space_glyph(self):
        folder = Path(tempfile.mkdtemp())
        write_png(folder / 'sheet.png', sheet(items=[RED, None, GREEN, RED, BLUE, GREEN]))
        (folder / 'names.txt').write_text('A\n \nC\nD\nE\nF\n')
        done = subprocess.run([sys.executable, str(ROOT / 'scripts/sprite_sheet.py'), str(folder / 'sheet.png'), str(folder / 'out'), '--grid', '3x2', '--names-file', str(folder / 'names.txt'), '--size', '32x32'],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertTrue((folder / 'out/space.png').exists())


if __name__ == '__main__':
    unittest.main()
