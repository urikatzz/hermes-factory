"""Slice one generated sheet (an evenly spaced grid of items on a flat background) into a set of named sprites.

Generating dozens of consistent items one image at a time cannot keep a style together; one sheet can. Each cell is cut out and fitted exactly like a single sprite
(`fit_asset`, cutout mode, edge margin, fragment report), so a sliced set obeys the same technical checks as any other cutout sprite.
"""
import re

from art_production.sprite_fit import FitError, fit_asset
from factory_art.png import Image

SPECIAL_NAMES = {'-': 'hyphen', ' ': 'space', '.': 'fullstop', ',': 'comma', ':': 'colon', '!': 'exclam', '?': 'question', '/': 'slash', '+': 'plus', '%': 'percent'}


class SheetError(ValueError):
    """The sheet cannot be sliced as asked (wrong item count, unusable names, a cell that fails the fit). The message says which."""


def item_filename(name, prefix=''):
    """`A` -> prefixA.png, `-` -> prefixhyphen.png, ` ` -> prefixspace.png. Unnameable characters are an error, never silently dropped."""
    token = SPECIAL_NAMES.get(name, name)
    if not re.fullmatch(r'[A-Za-z0-9_]{1,40}', token):
        raise SheetError(f'cannot make a file name for {name!r}: use letters, digits, underscore, or one of {sorted(SPECIAL_NAMES)}')
    return f'{prefix}{token}.png'


def cell(image, column, row, columns, rows, inset=0.03):
    """The pixels of one grid cell, trimmed by `inset` (a fraction of the cell) on every side so a neighbour's edge never leaks in."""
    cw, ch = image.width / columns, image.height / rows
    x0, x1 = int(column * cw + cw * inset), int((column + 1) * cw - cw * inset)
    y0, y1 = int(row * ch + ch * inset), int((row + 1) * ch - ch * inset)
    return Image(x1 - x0, y1 - y0, [image.pixels[y * image.width + x] for y in range(y0, y1) for x in range(x0, x1)])


def slice_sheet(image, columns, rows, names, size, prefix='', margin=2, drop_fragments_below=0, palette=None, inset=0.03, blank_ok=('space',)):
    """Returns [(name, filename, sprite, report)] in grid order (left to right, top to bottom). The item count must match the grid exactly."""
    if columns < 1 or rows < 1 or columns * rows > 400:
        raise SheetError('the grid must be between 1x1 and 400 cells')
    names = list(names)
    if len(names) != columns * rows:
        raise SheetError(f'the grid has {columns * rows} cells ({columns}x{rows}) but {len(names)} names were given: the sheet and the list must match one to one')
    if len(set(item_filename(n) for n in names)) != len(names):
        raise SheetError('two names map to the same file name')
    width, height = size
    out = []
    for index, name in enumerate(names):
        row, column = divmod(index, columns)
        piece = cell(image, column, row, columns, rows, inset)
        filename = item_filename(name, prefix)
        try:
            sprite, report = fit_asset(piece, width, height, palette, 'cutout', margin=margin, drop_fragments_below=drop_fragments_below)
        except (FitError, ValueError) as error:
            if SPECIAL_NAMES.get(name, name) in blank_ok:
                sprite = Image(width, height, [(0, 0, 0, 0)] * (width * height))
                report = dict(coverage='cutout', blank=True, width=width, height=height, opaque=0.0)
            else:
                detail = error.diagnosis['message'] if isinstance(error, FitError) else str(error)
                raise SheetError(f'cell {column + 1},{row + 1} ({name!r}) could not be cut out: {detail}. Regenerate the sheet with that item clearly separated on a flat background.') from error
        out.append((name, filename, sprite, report))
    return out
