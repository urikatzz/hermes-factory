"""Turn a generated concept image into a game asset: nearest-neighbour fit, palette, and (for cut-out sprites) flat background to alpha.

Two coverage modes. `cutout` (isolated sprites: characters, props, doors, platforms, glyphs, effects) turns the flat background that touches the border
transparent, then fits the content inside the target on a transparent canvas. `opaque` (full-bleed art: walls, floors, backdrops, bands, tiles, anything its
criterion requires to cover an area) keeps every pixel and covers the target exactly: it neither removes a background nor pads when the aspect ratios differ.
The fit verifies its own result so a wrong mode is reported as a tool-mode error with the supported fix, never as a failed asset."""
from collections import Counter, deque
import re

from factory_art.png import Image

TRANSPARENT = (0, 0, 0, 0)


def remove_background(image, tolerance=24):
    """Make the flat background that touches the border transparent. Images with transparent corners are kept."""
    width, height, pixels = image.width, image.height, list(image.pixels)
    corners = [pixels[0], pixels[width - 1], pixels[(height - 1) * width], pixels[-1]]
    if any(pixel[3] < 255 for pixel in corners):
        return Image(width, height, [pixel if pixel[3] else TRANSPARENT for pixel in pixels])
    background = Counter(pixel[:3] for pixel in corners).most_common(1)[0][0]

    def near(pixel):
        return max(abs(a - b) for a, b in zip(pixel[:3], background)) <= tolerance

    border = set(range(width)) | {(height - 1) * width + x for x in range(width)}
    border |= {y * width for y in range(height)} | {y * width + width - 1 for y in range(height)}
    seen = bytearray(width * height)
    queue = deque(index for index in sorted(border) if near(pixels[index]))
    for index in queue:
        seen[index] = 1
    while queue:
        index = queue.popleft()
        pixels[index] = TRANSPARENT
        x, y = index % width, index // width
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                neighbour = ny * width + nx
                if not seen[neighbour] and near(pixels[neighbour]):
                    seen[neighbour] = 1
                    queue.append(neighbour)
    return Image(width, height, pixels)


def crop_to_content(image):
    visible = [index for index, pixel in enumerate(image.pixels) if pixel[3]]
    if not visible:
        raise ValueError('image has no visible pixels after background removal')
    xs = [index % image.width for index in visible]
    ys = [index // image.width for index in visible]
    left, right, top, bottom = min(xs), max(xs) + 1, min(ys), max(ys) + 1
    return Image(right - left, bottom - top,
                 [image.pixels[y * image.width + x] for y in range(top, bottom) for x in range(left, right)])


def downscale(image, width, height):
    """Nearest-neighbour resample to exactly width x height, sampling the centre of each target pixel."""
    return Image(width, height, [
        image.pixels[min(image.height - 1, (2 * y + 1) * image.height // (2 * height)) * image.width
                     + min(image.width - 1, (2 * x + 1) * image.width // (2 * width))]
        for y in range(height) for x in range(width)])


def fit(image, width, height, margin=0):
    """Scale the visible content uniformly to fit inside width x height (less `margin` transparent pixels on every side), centred on a transparent canvas."""
    content = crop_to_content(image)
    room_w, room_h = max(1, width - 2 * margin), max(1, height - 2 * margin)
    scale = min(room_w / content.width, room_h / content.height)
    w = min(room_w, max(1, round(content.width * scale)))
    h = min(room_h, max(1, round(content.height * scale)))
    small = downscale(content, w, h)
    left, top = (width - w) // 2, (height - h) // 2
    pixels = [TRANSPARENT] * (width * height)
    for y in range(h):
        start = (top + y) * width + left
        pixels[start:start + w] = small.pixels[y * w:(y + 1) * w]
    return Image(width, height, pixels)


def fit_cover(image, width, height):
    """Scale uniformly until the image covers width x height exactly, then crop the overflow evenly: every output pixel comes from the source, nothing is padded.

    `fit` does the opposite (fit inside, centre on a transparent canvas), which leaves transparent bars whenever the aspect ratios differ."""
    scale = max(width / image.width, height / image.height)
    crop_w, crop_h = width / scale, height / scale
    left, top = (image.width - crop_w) / 2, (image.height - crop_h) / 2
    return Image(width, height, [
        image.pixels[min(image.height - 1, int(top + (y + 0.5) * crop_h / height)) * image.width
                     + min(image.width - 1, int(left + (x + 0.5) * crop_w / width))]
        for y in range(height) for x in range(width)])


def harden_alpha(image, threshold=128):
    return Image(image.width, image.height,
                 [pixel[:3] + (255,) if pixel[3] >= threshold else TRANSPARENT for pixel in image.pixels])


def quantize(image, palette):
    """Map every visible pixel to the nearest palette colour (squared RGB distance)."""
    cache = {}

    def nearest(colour):
        if colour not in cache:
            cache[colour] = min(palette, key=lambda entry: sum((a - b) ** 2 for a, b in zip(colour, entry)))
        return cache[colour]

    return Image(image.width, image.height,
                 [nearest(pixel[:3]) + (pixel[3],) if pixel[3] else TRANSPARENT for pixel in image.pixels])


def make_sprite(image, width, height, palette=None, keep_background=False, tolerance=24, margin=0):
    if not keep_background:
        image = remove_background(image, tolerance)
    sprite = harden_alpha(fit(image, width, height, margin))
    return quantize(sprite, palette) if palette else sprite


COVERAGES = ('cutout', 'opaque')
OPAQUE_REQUIREMENT = re.compile(
    r'full[- ]?bleed|edge[- ]to[- ]edge|\bopaque\b|\bbackdrop\b|background (?:layer|plate|image)|floor band|ground band|\btile[ds]?\b|seamless|tileable'
    r'|\bcovers\b.{0,40}\d|\bcovering\b.{0,40}\d', re.I)
MIN_OPAQUE = 0.99          # an opaque asset must keep at least this share of its pixels
ERASED_BELOW = 0.10        # a cut-out that leaves less than this share of a fully opaque source is almost certainly the wrong mode


class FitError(ValueError):
    """The fit would destroy a property the asset requires. `diagnosis` says which transformation, whose defect it is and the supported fix."""

    def __init__(self, diagnosis):
        super().__init__(diagnosis['message'])
        self.diagnosis = diagnosis


def choose_coverage(requirement_text):
    """`opaque` when the asset's name or criterion asks for full coverage, else `cutout` (the safe default for isolated sprites)."""
    return 'opaque' if OPAQUE_REQUIREMENT.search(str(requirement_text or '')) else 'cutout'


def opaque_fraction(image):
    total = len(image.pixels)
    return sum(1 for pixel in image.pixels if pixel[3] == 255) / total if total else 0.0


def _groups(image):
    """Connected groups (4-neighbour) of visible pixels, largest first: [(px, bbox, [pixel indices])]."""
    w, h, seen, found = image.width, image.height, bytearray(len(image.pixels)), []
    for start, pixel in enumerate(image.pixels):
        if not pixel[3] or seen[start]:
            continue
        stack, members, seen[start] = [start], [], 1
        x0, y0, x1, y1 = w, h, 0, 0
        while stack:
            i = stack.pop(); members.append(i); x, y = i % w, i // w
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
            for j in ((i - 1) if x else -1, (i + 1) if x < w - 1 else -1, (i - w) if y else -1, (i + w) if y < h - 1 else -1):
                if j >= 0 and image.pixels[j][3] and not seen[j]:
                    seen[j] = 1; stack.append(j)
        found.append((len(members), (x0, y0, x1, y1), members))
    return sorted(found, key=lambda g: -g[0])


def components(image):
    """The visible groups of a sprite as [{'px', 'bbox': (x0, y0, x1, y1)}], largest first."""
    return [dict(px=px, bbox=bbox) for px, bbox, _ in _groups(image)]


def drop_fragments(image, min_px):
    """Clear every visible group smaller than min_px pixels except the largest one. Returns (image, [removed groups])."""
    groups = _groups(image)
    if len(groups) < 2 or min_px <= 0:
        return image, []
    doomed = [g for g in groups[1:] if g[0] < min_px]
    if not doomed:
        return image, []
    pixels = list(image.pixels)
    for _, _, members in doomed:
        for index in members:
            pixels[index] = (0, 0, 0, 0)
    return type(image)(image.width, image.height, pixels), [dict(px=px, bbox=bbox) for px, bbox, _ in doomed]


def edge_contact(image):
    """Which canvas edges carry visible pixels: a sprite that touches an edge reads as cropped there."""
    w, h = image.width, image.height
    return dict(left=any(image.pixels[y * w][3] for y in range(h)), right=any(image.pixels[y * w + w - 1][3] for y in range(h)),
                top=any(image.pixels[x][3] for x in range(w)), bottom=any(image.pixels[(h - 1) * w + x][3] for x in range(w)))


def fit_asset(image, width, height, palette=None, coverage='cutout', tolerance=24, allow_mostly_transparent=False, margin=0, drop_fragments_below=0):
    """Fit `image` to width x height in the given coverage mode; returns (sprite, report). Raises FitError when a required property is destroyed."""
    if coverage not in COVERAGES:
        raise ValueError('coverage must be one of: ' + ', '.join(COVERAGES))
    source_opaque = opaque_fraction(image)
    if coverage == 'opaque':
        sprite = fit_cover(image, width, height)   # never remove the background and never pad: both destroy a full-bleed asset
        if palette:
            sprite = quantize(sprite, palette)
    else:
        sprite = make_sprite(image, width, height, palette, keep_background=False, tolerance=tolerance, margin=margin)
    dropped = []
    if coverage == 'cutout' and drop_fragments_below > 0:
        sprite, dropped = drop_fragments(sprite, drop_fragments_below)
    result_opaque = opaque_fraction(sprite)
    report = dict(coverage=coverage, source_opaque=round(source_opaque, 4), opaque=round(result_opaque, 4), width=sprite.width, height=sprite.height)
    if coverage == 'cutout':
        # What the technical check will see: detached groups and canvas edges that carry pixels. Reported so the artist can fix them (--drop-fragments-below, --margin) or regenerate.
        groups = components(sprite)
        report.update(edge_contact=edge_contact(sprite), margin=margin, fragments=[dict(px=g['px'], bbox=list(g['bbox'])) for g in groups[1:9]], fragment_count=max(0, len(groups) - 1),
                      dropped_fragments=len(dropped), dropped_px=sum(g['px'] for g in dropped))
    if coverage == 'opaque' and result_opaque < MIN_OPAQUE:
        raise FitError(dict(code='source_not_opaque', defect='generation', transformation='none (the opaque fit keeps and covers every pixel)', **report,
            message=f'the generated image itself is only {source_opaque:.1%} opaque, so the asset cannot be opaque',
            fix='Regenerate the image with a continuous painted fill to every edge; the fit cannot add pixels that were not generated.'))
    if (coverage == 'cutout' and source_opaque >= 0.999 and result_opaque < ERASED_BELOW and not allow_mostly_transparent):
        raise FitError(dict(code='background_removal_erased_most_of_the_image', defect='tool_mode', transformation='remove_background (flat background touching the border to alpha)', **report,
            message=f'background removal erased {1 - result_opaque:.1%} of a fully opaque image',
            fix='If this asset must be opaque (wall, floor, backdrop, band, tile, or its criterion requires it to cover an area) re-run with --coverage opaque (the supported mode of this tool). '
                'If it really is a small sprite on a large flat background, re-run with --allow-mostly-transparent. This is a tool-mode choice, not a failed generation.'))
    return sprite, report
