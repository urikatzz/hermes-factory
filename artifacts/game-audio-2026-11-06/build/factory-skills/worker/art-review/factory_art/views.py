"""Images prepared for the vision pass: upscaled sprites on fixed backgrounds, model contact sheets."""
from pathlib import Path

from .png import Image, read_png, write_png

BACKGROUNDS = (('transparent', None), ('grey', (128, 128, 128)), ('dark', (32, 32, 32)))
MAX_VIEW_PX = 1024


def upscale(image, factor):
    pixels = []
    for y in range(image.height):
        row = [pixel for pixel in image.pixels[y * image.width:(y + 1) * image.width] for _ in range(factor)]
        pixels.extend(row * factor)
    return Image(image.width * factor, image.height * factor, pixels)


def composite(image, background):
    r, g, b = background
    return Image(image.width, image.height, [
        ((p[0] * p[3] + r * (255 - p[3])) // 255, (p[1] * p[3] + g * (255 - p[3])) // 255,
         (p[2] * p[3] + b * (255 - p[3])) // 255, 255) for p in image.pixels])


def tile(images, columns):
    width, height = images[0].width, images[0].height
    if any((image.width, image.height) != (width, height) for image in images):
        raise ValueError('tiled images differ in size')
    rows, pixels = -(-len(images) // columns), []
    for row in range(rows):
        for y in range(height):
            for column in range(columns):
                index = row * columns + column
                pixels.extend(images[index].pixels[y * width:(y + 1) * width] if index < len(images)
                              else [(0, 0, 0, 0)] * width)
    return Image(width * columns, height * rows, pixels)


def sprite_views(image, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    big = upscale(image, max(1, min(4, MAX_VIEW_PX // max(image.width, image.height))))
    paths = []
    for name, background in BACKGROUNDS:
        path = out_dir / f'{name}.png'
        write_png(path, big if background is None else composite(big, background))
        paths.append(str(path))
    return paths


def contact_sheet(paths, out):
    write_png(out, tile([read_png(path) for path in paths], 2))
    return str(out)
