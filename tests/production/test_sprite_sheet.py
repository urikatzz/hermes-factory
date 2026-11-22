import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from production_fixtures import ROOT
from art_production.sheet import SheetError, cell, item_filename, slice_sheet
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
