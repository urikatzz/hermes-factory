"""Turn a generated concept image into a game sprite: flat background to alpha, nearest-neighbour fit, palette."""
from collections import Counter, deque

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
