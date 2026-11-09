"""Measurable sprite checks: size, alpha, pixel-art edges and scale, palette."""
from .findings import finding

TRANSPARENT = (0, 0, 0, 0)


def check_sprite(rel, image, cls):
    found = []
    size = cls.get('size', {})
    for axis, value in (('width', image.width), ('height', image.height)):
        limits = size.get(axis)
        if limits and not limits[0] <= value <= limits[1]:
            found.append(finding('HIGH', 'size', rel, f'{axis} {value}px outside {limits[0]}-{limits[1]}px'))
    step = size.get('multiple_of')
    if step and (image.width % step or image.height % step):
        found.append(finding('HIGH', 'size', rel, f'{image.width}x{image.height}px is not a multiple of {step}'))
    alphas = [pixel[3] for pixel in image.pixels]
    if cls.get('alpha') == 'required' and min(alphas) == 255:
        found.append(finding('HIGH', 'alpha', rel, 'no transparent pixels; alpha is required'))
    if cls.get('pixel_art'):
        partial = sum(1 for alpha in alphas if 0 < alpha < 255)
        if partial:
            found.append(finding('MEDIUM', 'pixel_art_edges', rel,
                                 f'{partial} semi-transparent pixels; pixel art needs hard edges'))
        factor = upscale_factor(image)
        if factor > 1:
            found.append(finding('MEDIUM', 'pixel_art_scale', rel, f'appears upscaled {factor}x; export at 1x'))
    if cls.get('_palette'):
        tolerance = cls['palette'].get('tolerance', 0)
        off = off_palette(image, cls['_palette'], tolerance)
        if off:
            examples = ', '.join('#%02x%02x%02x' % colour for colour in off[:3])
            found.append(finding('MEDIUM', 'palette', rel,
                                 f'{len(off)} colours off palette (tolerance {tolerance}), e.g. {examples}'))
    return found


def upscale_factor(image):
    pixels = [pixel if pixel[3] else TRANSPARENT for pixel in image.pixels]
    best = 1
    for factor in range(2, min(16, min(image.width, image.height) // 2) + 1):
        if not image.width % factor and not image.height % factor and _uniform(pixels, image, factor):
            best = factor
    return best


def off_palette(image, palette, tolerance):
    colours = {pixel[:3] for pixel in image.pixels if pixel[3]}
    return sorted(colour for colour in colours
                  if all(max(abs(a - b) for a, b in zip(colour, entry)) > tolerance for entry in palette))


def _uniform(pixels, image, factor):
    width = image.width
    for top in range(0, image.height, factor):
        for left in range(0, width, factor):
            first = pixels[top * width + left]
            for y in range(top, top + factor):
                for x in range(left, left + factor):
                    if pixels[y * width + x] != first:
                        return False
    return True
