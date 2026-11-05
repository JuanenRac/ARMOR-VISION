"""The one movement model of the observation services: pixels, the change of the whole picture taken away, a grid to say where, regions as rectangles.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

THIS FILE IS KEPT IN ARMOR-COMMON AND COPIED, BYTE FOR BYTE, INTO ARMOR-SERVER-AI AND ARMOR-VISION (`src/<package>/motion_core.py`). Change it here and run
`python tools/sync_motion_core.py sync`; `check` (run by the tests of the three repositories) fails when a copy differs.

The model: frames are 8-bit grey images (width x height bytes, row by row). A pixel has changed when it differs from the previous frame by more than a threshold
after the typical change of the whole picture - its median, which a moving person barely shifts - is taken away, so the automatic exposure of a camera, a cloud
or the switch to infrared is never movement. The decision is per pixel; the picture is cut into a grid only to tell WHERE it moved: a cell has moved when a tenth of
its pixels changed, and neighbouring moved cells are joined into regions, given as rectangles `{x, y, w, h}` in fractions of the picture. A mask (one byte per pixel,
0 for a pixel that must not count) takes pixels out of everything: the changes, the median and the count the shares are of.

Pure functions with no dependency, so they are tested without a camera.
"""

from __future__ import annotations

from dataclasses import dataclass, field

GRID_COLUMNS = 16
GRID_ROWS = 9
#: The share of the pixels of a cell that must have changed for the cell to count as moved.
CELL_CHANGED_RATIO = 0.10
#: How much a pixel has to change (of 255) to count as moved; below this is the noise of the sensor and of the compression.
PIXEL_THRESHOLD = 18
#: Fewest pixels that must be left to look at once the mask is applied (a handful of pixels must not decide).
MIN_COUNTED_PIXELS = 64
#: Most regions reported at once (the contract allows this many).
MAX_REGIONS = 16

Rect = dict  # {"x": float, "y": float, "w": float, "h": float}, each from 0 to 1


@dataclass(frozen=True)
class Motion:
    #: The share (0 to 1) of the counted pixels that changed.
    ratio: float
    #: The (column, row) cells that moved.
    cells: frozenset = field(default_factory=frozenset)
    #: The extents (first column, first row, last column, last row) of each group of joined cells, in order.
    extents: tuple = ()


def check_frame(frame: bytes, width: int, height: int) -> None:
    if width < 1 or height < 1:
        raise ValueError("a frame needs a positive size")
    if not isinstance(frame, (bytes, bytearray)) or len(frame) != width * height:
        raise ValueError(f"a grey frame of {width} x {height} is {width * height} bytes")


def rect_mask(rects, width: int, height: int) -> bytes | None:
    """The mask of ignore rectangles, each `(x, y, w, h)` or a dict with those keys, in fractions of the picture: 1 for a pixel that counts, 0 for one inside a rectangle.
    One that is not a rectangle inside the picture is left out; at most 16 are read. None when there is nothing to ignore."""
    mask = bytearray(b"\x01" * (width * height))
    ignored = False
    for rect in list(rects or [])[:16]:
        try:
            x, y, w, h = (rect["x"], rect["y"], rect["w"], rect["h"]) if isinstance(rect, dict) else rect
            x, y, w, h = float(x), float(y), float(w), float(h)
        except (KeyError, TypeError, ValueError):
            continue
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0 and 0.0 < w <= 1.0 and 0.0 < h <= 1.0):
            continue
        left, right = int(x * width), min(width, int((x + w) * width + 0.999))
        top, bottom = int(y * height), min(height, int((y + h) * height + 0.999))
        for row in range(top, bottom):
            for column in range(left, right):
                mask[row * width + column] = 0
                ignored = True
    return bytes(mask) if ignored else None


def _median_shift(differences: list[int]) -> int:
    return sorted(differences)[len(differences) // 2]


def analyze(previous: bytes, current: bytes, width: int, height: int, threshold: int = PIXEL_THRESHOLD, mask: bytes | None = None,
            columns: int = GRID_COLUMNS, rows: int = GRID_ROWS, cell_ratio: float = CELL_CHANGED_RATIO,
            min_counted: int = MIN_COUNTED_PIXELS) -> Motion:
    """Compare two frames of the same size. `ratio` is the share of the counted pixels that changed (0.0 and no cells when fewer than `min_counted` pixels are left under the mask);
    `cells` and `extents` say where, on a grid of `columns` x `rows`."""
    check_frame(previous, width, height)
    check_frame(current, width, height)
    if mask is not None and len(mask) != width * height:
        raise ValueError(f"a mask is {width * height} bytes")
    if mask is None:
        counted = width * height
        differences = [after - before for before, after in zip(previous, current, strict=True)]
        shift = _median_shift(differences)
        changed = bytearray(1 if abs(difference - shift) > threshold else 0 for difference in differences)
    else:
        counted = sum(1 for flag in mask if flag)
        if counted < max(1, min_counted):
            return Motion(0.0)
        differences = [(after - before) if flag else 0 for before, after, flag in zip(previous, current, mask, strict=True)]
        shift = _median_shift([difference for difference, flag in zip(differences, mask, strict=True) if flag])
        changed = bytearray(1 if flag and abs(difference - shift) > threshold else 0 for difference, flag in zip(differences, mask, strict=True))
    ratio = sum(changed) / counted
    cells = set()
    for row in range(rows):
        y0, y1 = row * height // rows, (row + 1) * height // rows
        for column in range(columns):
            x0, x1 = column * width // columns, (column + 1) * width // columns
            total = moved = 0
            for y in range(y0, y1):
                base = y * width
                moved += sum(changed[base + x0:base + x1])
                total += (x1 - x0) if mask is None else sum(1 for flag in mask[base + x0:base + x1] if flag)
            if total and moved / total > cell_ratio:
                cells.add((column, row))
    return Motion(ratio, frozenset(cells), region_extents(cells))


def region_extents(cells) -> tuple:
    """Joins 4-connected cells; one `(first column, first row, last column, last row)` per group, in order."""
    remaining = set(cells)
    out = []
    while remaining:
        stack = [remaining.pop()]
        group = [stack[0]]
        while stack:
            column, row = stack.pop()
            for neighbour in ((column + 1, row), (column - 1, row), (column, row + 1), (column, row - 1)):
                if neighbour in remaining:
                    remaining.discard(neighbour)
                    stack.append(neighbour)
                    group.append(neighbour)
        columns = [c for c, _ in group]
        group_rows = [r for _, r in group]
        out.append((min(columns), min(group_rows), max(columns), max(group_rows)))
    return tuple(sorted(out))


def regions(extents, columns: int = GRID_COLUMNS, rows: int = GRID_ROWS, limit: int = MAX_REGIONS) -> list[Rect]:
    """The extents as rectangles `{x, y, w, h}` in fractions of the picture (rounded to 4 decimals), the largest first and at most `limit`."""
    ordered = sorted(extents, key=lambda e: ((e[2] - e[0] + 1) * (e[3] - e[1] + 1), -e[1], -e[0]), reverse=True)[:limit]
    return [{"x": round(c0 / columns, 4), "y": round(r0 / rows, 4), "w": round((c1 - c0 + 1) / columns, 4), "h": round((r1 - r0 + 1) / rows, 4)}
            for c0, r0, c1, r1 in ordered]
