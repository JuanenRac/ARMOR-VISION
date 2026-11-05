"""A cheap motion detector that decides WHERE the expensive detector looks.

Frames are 8-bit grey images (width x height bytes, row by row). The decision
is made per pixel, the same model as the movement check of ARMOR-SERVER-AI: a
pixel has changed when it differs from the previous frame by more than the
threshold, after the typical change of the whole picture (its median, which a
moving person barely shifts) is taken away, so the camera's automatic exposure,
a cloud or the switch to infrared is never movement. The picture is cut into a
grid only to tell WHERE it moved: a cell has moved when a tenth of its pixels
changed. Cells under a mask never count and are left out of the median.
Neighbouring moved cells are joined into regions, returned as normalised
rectangles.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import motion_core as core
from .geometry import Box, point_in_polygon

GRID_COLUMNS = 16
GRID_ROWS = 9
#: The share of the pixels of a cell that must have changed for the cell to count as moved (the same tenth that means full movement in the server).
CELL_CHANGED_RATIO = 0.10


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    pixels: bytes

    def __post_init__(self) -> None:
        if self.width < 1 or self.height < 1:
            raise ValueError("a frame needs a positive size")
        if len(self.pixels) != self.width * self.height:
            raise ValueError("a grey frame has width x height bytes")


_MASKED: dict[tuple, frozenset] = {}
_PIXEL_MASKS: dict[tuple, bytes | None] = {}


def _masked_cells(masks: tuple) -> frozenset:
    """The cells whose centre is under a mask; a mask does not change from frame to frame, so this is worked out once per set of masks."""
    if not masks:
        return frozenset()
    found = _MASKED.get(masks)
    if found is None:
        found = frozenset((column, row) for row in range(GRID_ROWS) for column in range(GRID_COLUMNS)
                          if any(point_in_polygon(((column + 0.5) / GRID_COLUMNS, (row + 0.5) / GRID_ROWS), mask) for mask in masks))
        if len(_MASKED) > 64:
            _MASKED.clear()
        _MASKED[masks] = found
    return found


def _pixel_mask(masks: tuple, width: int, height: int) -> bytes | None:
    """The cells under a mask as a mask of pixels (0 for a pixel that must not count), the form the shared movement model takes; None when nothing is masked."""
    masked = _masked_cells(masks)
    if not masked:
        return None
    key = (masks, width, height)
    found = _PIXEL_MASKS.get(key, False)
    if found is False:
        pixels = bytearray(b"" * (width * height))
        for column, row in masked:
            for y in range(row * height // GRID_ROWS, (row + 1) * height // GRID_ROWS):
                start = y * width
                x0, x1 = column * width // GRID_COLUMNS, (column + 1) * width // GRID_COLUMNS
                pixels[start + x0:start + x1] = bytes(x1 - x0)
        found = bytes(pixels)
        if len(_PIXEL_MASKS) > 64:
            _PIXEL_MASKS.clear()
        _PIXEL_MASKS[key] = found
    return found


def analyze(previous: Frame, current: Frame, threshold: int, masks: tuple = ()) -> core.Motion:
    """The movement between two frames of the same size by the model every observation service shares (motion_core.py): the share of the pixels that changed, and the cells."""
    if (previous.width, previous.height) != (current.width, current.height):
        raise ValueError("the two frames must have the same size")
    mask = _pixel_mask(tuple(tuple(tuple(p) for p in mask) for mask in masks), current.width, current.height)
    return core.analyze(previous.pixels, current.pixels, current.width, current.height, threshold, mask, GRID_COLUMNS, GRID_ROWS, CELL_CHANGED_RATIO, min_counted=1)


def moved_cells(previous: Frame, current: Frame, threshold: int, masks: tuple = ()) -> set[tuple[int, int]]:
    """The (column, row) cells that moved between two frames of the same size."""
    return set(analyze(previous, current, threshold, masks).cells)


def regions(cells: set[tuple[int, int]]) -> list[Box]:
    """Joins 4-connected cells and returns one normalised box per group."""
    return [(c0 / GRID_COLUMNS, r0 / GRID_ROWS, (c1 + 1) / GRID_COLUMNS, (r1 + 1) / GRID_ROWS) for c0, r0, c1, r1 in core.region_extents(cells)]


def region_rects(cells: set[tuple[int, int]]) -> list[dict]:
    """The same groups as rectangles `{x, y, w, h}`, the largest first, the form the observation contract takes."""
    return core.regions(core.region_extents(cells), GRID_COLUMNS, GRID_ROWS)
