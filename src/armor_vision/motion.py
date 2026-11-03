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


def moved_cells(previous: Frame, current: Frame, threshold: int, masks: tuple = ()) -> set[tuple[int, int]]:
    """The (column, row) cells that moved between two frames of the same size."""
    if (previous.width, previous.height) != (current.width, current.height):
        raise ValueError("the two frames must have the same size")
    width, height = current.width, current.height
    masked = _masked_cells(tuple(tuple(tuple(p) for p in mask) for mask in masks))
    bounds = {}
    histogram = [0] * 511
    counted = 0
    for row in range(GRID_ROWS):
        y0, y1 = row * height // GRID_ROWS, (row + 1) * height // GRID_ROWS
        for column in range(GRID_COLUMNS):
            if (column, row) in masked:
                continue
            x0, x1 = column * width // GRID_COLUMNS, (column + 1) * width // GRID_COLUMNS
            bounds[(column, row)] = (x0, x1, y0, y1)
            for y in range(y0, y1):
                base = y * width
                for x in range(x0, x1):
                    histogram[current.pixels[base + x] - previous.pixels[base + x] + 255] += 1
            counted += (x1 - x0) * (y1 - y0)
    if not counted:
        return set()
    seen = 0
    shift = 0
    for index, amount in enumerate(histogram):
        seen += amount
        if seen > counted // 2:
            shift = index - 255
            break
    cells: set[tuple[int, int]] = set()
    for cell, (x0, x1, y0, y1) in bounds.items():
        changed = count = 0
        for y in range(y0, y1):
            base = y * width
            for x in range(x0, x1):
                if abs(current.pixels[base + x] - previous.pixels[base + x] - shift) > threshold:
                    changed += 1
                count += 1
        if count and changed / count > CELL_CHANGED_RATIO:
            cells.add(cell)
    return cells


def regions(cells: set[tuple[int, int]]) -> list[Box]:
    """Joins 4-connected cells and returns one normalised box per group."""
    remaining = set(cells)
    boxes: list[Box] = []
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
        rows = [r for _, r in group]
        boxes.append((min(columns) / GRID_COLUMNS, min(rows) / GRID_ROWS,
                      (max(columns) + 1) / GRID_COLUMNS, (max(rows) + 1) / GRID_ROWS))
    return sorted(boxes)
