"""Pixel size for a produced asset when the task does not give one: explicit sizes win, otherwise derive from the reference's aspect and the plan's world size.

A missing pixel size is never a blocker. The size an asset is painted at is a production decision, made inside the asset class's allowed range, with the longest side capped
(1024 px by default) and the derived aspect ratio kept. Only genuinely impossible or contradictory input is refused, because only that cannot be resolved by choosing.
"""
import math

CLASS_MIN, CLASS_MAX, CAP = 32, 2048, 1024
PPU = 128.0               # pixels per world unit when only a world size is known: the density of this project's delivered sprites is about 70-150
DEFAULT_LONG_SIDE = 512   # when only the reference aspect is known and nothing says how big the asset is in the world
ASPECT_TOLERANCE = 0.15       # a reference region's aspect and the plan's world proportions must agree this closely, or they contradict each other


class SizingError(ValueError):
    """The constraints cannot all be met (contradictory or impossible); choosing a size cannot fix that, so the artist may block on it."""


def _positive(value, what):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
        raise SizingError(f'{what} must be a positive number, got {value!r}')
    return float(value)


def derive_size(aspect=None, world=None, explicit=None, class_min=CLASS_MIN, class_max=CLASS_MAX, cap=CAP, ppu=PPU):
    """Returns dict(width, height, source, world, aspect, reasoning).

    explicit: (w, h) pixels given by the task. It is used as stated and only validated against the class range (an out-of-range explicit size contradicts the class).
    aspect:   width / height of the asset's region of the approved reference.
    world:    (width, height) in world units from the plan; the pixel size follows from it at `ppu` pixels per unit, clamped into the class range and under the cap.
    ppu:      pixels per world unit used with a world size (default 128).
    """
    if not 1 <= class_min < class_max:
        raise SizingError('the class range is invalid')
    cap = min(_positive(cap, 'cap'), class_max)
    if explicit is not None:
        w, h = (int(_positive(explicit[0], 'explicit width')), int(_positive(explicit[1], 'explicit height')))
        if not (class_min <= w <= class_max and class_min <= h <= class_max):
            raise SizingError(f'the explicit size {w}x{h} is outside the class range {class_min}-{class_max} px per side: the requirement and the class contradict each other')
        return dict(width=w, height=h, source='explicit', world=world, aspect=round(w / h, 4), reasoning=f'the task states {w}x{h}; used as written')
    ratio = None
    reasoning = []
    if aspect is not None:
        ratio = _positive(aspect, 'aspect')
        reasoning.append(f'aspect {ratio:.3f} taken from the approved reference region')
    world_ratio = None
    if world is not None and world[0] is not None and world[1] is not None:
        world_ratio = _positive(world[0], 'world width') / _positive(world[1], 'world height')
        reasoning.append(f'world size {world[0]} x {world[1]} units from the plan (ratio {world_ratio:.3f})')
    if ratio is not None and world_ratio is not None:
        if abs(ratio - world_ratio) / world_ratio > ASPECT_TOLERANCE:
            raise SizingError(f'the reference region ({ratio:.3f}) and the plan\'s world proportions ({world_ratio:.3f}) disagree by more than {int(ASPECT_TOLERANCE * 100)}%: contradictory')
        ratio = world_ratio       # the plan's stated world proportions are the stricter statement
    elif ratio is None:
        ratio = world_ratio
    if ratio is None:
        raise SizingError('neither an aspect from the reference nor world proportions are known: nothing to derive a size from (look the asset up in the approved reference first)')
    if world_ratio is not None:
        long_world = max(world[0], world[1])
        wanted = long_world * _positive(ppu, 'ppu')
        longest = min(max(wanted, class_min / min(1.0, ratio) if ratio < 1 else class_min), cap)
        reasoning.append(f'{ppu:g} px per world unit gives a long side of {wanted:.0f} px' + ('' if longest == wanted else f', adjusted to {longest:.0f} (class range and the {int(cap)} px cap)'))
    else:
        longest = float(min(DEFAULT_LONG_SIDE, cap))
        reasoning.append(f'no world size is known, so the long side is the {int(longest)} px default')
    w, h = (longest, longest / ratio) if ratio >= 1 else (longest * ratio, longest)
    w, h = int(round(w)), int(round(h))
    if min(w, h) < class_min:
        raise SizingError(f'an aspect of {ratio:.2f} cannot fit the class range: the short side would be {min(w, h)} px (< {class_min}) with the long side at {int(longest)}')
    reasoning.append(f'result {w}x{h}, inside {class_min}-{class_max}, long side at most {int(cap)}')
    return dict(width=w, height=h, source='derived', world=list(world) if world else None, aspect=round(w / h, 4), reasoning='; '.join(reasoning))
