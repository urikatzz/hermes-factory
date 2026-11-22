"""Slice one generated sheet (an evenly spaced grid of items on a flat background) into a set of named sprites.

Generating dozens of consistent items one image at a time cannot keep a style together; one sheet can. Each cell is cut out and fitted exactly like a single sprite
(`fit_asset`, cutout mode, edge margin, fragment report), so a sliced set obeys the same technical checks as any other cutout sprite.
"""
import re

from art_production.sprite_fit import FitError, _groups, fit_asset, remove_background
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


def detect_items(image, columns, count, gap=None, tolerance=24):
    """Find the items of a sheet without assuming even cell boundaries: cut the flat background out, merge parts that sit within `gap` pixels of each other (the dot of an i, a
    broken stroke), then order the groups into rows of `columns` (top to bottom by centre, each row left to right). Returns [bbox] or raises SheetError naming what was found."""
    visible = remove_background(image, tolerance)
    gap = gap if gap is not None else max(2, int(min(image.width, image.height) * 0.012))
    boxes = [list(g[1]) for g in _groups(visible) if g[0] >= 4]
    merged = True
    while merged:                       # merge boxes that touch or sit within the gap
        merged = False
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                if a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]:
                    boxes[i] = [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]
                    del boxes[j]; merged = True; break
            if merged:
                break
    if len(boxes) != count:
        raise SheetError(f'found {len(boxes)} separate items on the sheet but {count} were expected (a smaller gap or a plainer background may help): '
                         + ', '.join(f'({b[0]},{b[1]})-({b[2]},{b[3]})' for b in sorted(boxes, key=lambda b: (b[1], b[0]))[:12]))
    centres = sorted(boxes, key=lambda b: (b[1] + b[3]) / 2)
    ordered = []
    for start in range(0, count, columns):
        ordered.extend(sorted(centres[start:start + columns], key=lambda b: b[0]))
    return [tuple(b) for b in ordered]


def crop_box(image, box, pad):
    x0, y0, x1, y1 = max(0, box[0] - pad), max(0, box[1] - pad), min(image.width - 1, box[2] + pad), min(image.height - 1, box[3] + pad)
    return Image(x1 - x0 + 1, y1 - y0 + 1, [image.pixels[y * image.width + x] for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)])


def slice_by_detection(image, columns, names, size, prefix='', margin=2, drop_fragments_below=0, palette=None, blank_ok=('space',), gap=None):
    """Slice a sheet whose items are not on exact grid lines. `names` lists every item in reading order; names that may be blank (`space`) do not appear on the sheet and become transparent sprites.
    The sheet holds only the visible items, `columns` per row (the last row may be shorter)."""
    names = list(names)
    if len(set(item_filename(n) for n in names)) != len(names):
        raise SheetError('two names map to the same file name')
    visible = [n for n in names if SPECIAL_NAMES.get(n, n) not in blank_ok]
    boxes = dict(zip(visible, detect_items(image, columns, len(visible), gap)))
    width, height = size
    out = []
    pad = max(2, int(min(image.width, image.height) * 0.01))
    for name in names:
        filename = item_filename(name, prefix)
        if name not in boxes:
            out.append((name, filename, Image(width, height, [(0, 0, 0, 0)] * (width * height)), dict(coverage='cutout', blank=True, width=width, height=height, opaque=0.0)))
            continue
        try:
            sprite, report = fit_asset(crop_box(image, boxes[name], pad), width, height, palette, 'cutout', margin=margin, drop_fragments_below=drop_fragments_below)
        except (FitError, ValueError) as error:
            detail = error.diagnosis['message'] if isinstance(error, FitError) else str(error)
            raise SheetError(f'item {name!r} at {boxes[name]} could not be cut out: {detail}') from error
        out.append((name, filename, sprite, report))
    return out


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
