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


def fit(image, width, height):
    """Scale the visible content uniformly to fit inside width x height, centred on a transparent canvas."""
    content = crop_to_content(image)
    scale = min(width / content.width, height / content.height)
    w = min(width, max(1, round(content.width * scale)))
    h = min(height, max(1, round(content.height * scale)))
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


def make_sprite(image, width, height, palette=None, keep_background=False, tolerance=24):
    if not keep_background:
        image = remove_background(image, tolerance)
    sprite = harden_alpha(fit(image, width, height))
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


def fit_asset(image, width, height, palette=None, coverage='cutout', tolerance=24, allow_mostly_transparent=False):
    """Fit `image` to width x height in the given coverage mode; returns (sprite, report). Raises FitError when a required property is destroyed."""
    if coverage not in COVERAGES:
        raise ValueError('coverage must be one of: ' + ', '.join(COVERAGES))
    source_opaque = opaque_fraction(image)
    if coverage == 'opaque':
        sprite = fit_cover(image, width, height)   # never remove the background and never pad: both destroy a full-bleed asset
        if palette:
            sprite = quantize(sprite, palette)
    else:
        sprite = make_sprite(image, width, height, palette, keep_background=False, tolerance=tolerance)
    result_opaque = opaque_fraction(sprite)
    report = dict(coverage=coverage, source_opaque=round(source_opaque, 4), opaque=round(result_opaque, 4), width=sprite.width, height=sprite.height)
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
