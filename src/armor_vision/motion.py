"""A cheap motion detector that decides WHERE the expensive detector looks.

Frames are 8-bit grey images (width x height bytes, row by row). The picture
is cut into a grid; a cell has moved when its mean absolute difference from
the previous frame is over the threshold. Cells under a mask never count.
Neighbouring moved cells are joined into regions, returned as normalised boxes.
"""
from __future__ import annotations

from dataclasses import dataclass

from .geometry import Box, point_in_polygon

GRID_COLUMNS = 16
GRID_ROWS = 9


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


def moved_cells(previous: Frame, current: Frame, threshold: int, masks: tuple = ()) -> set[tuple[int, int]]:
    """The (column, row) cells that changed between two frames of the same size."""
    if (previous.width, previous.height) != (current.width, current.height):
        raise ValueError("the two frames must have the same size")
    cells: set[tuple[int, int]] = set()
    for row in range(GRID_ROWS):
        y0, y1 = row * current.height // GRID_ROWS, (row + 1) * current.height // GRID_ROWS
        for column in range(GRID_COLUMNS):
            centre = ((column + 0.5) / GRID_COLUMNS, (row + 0.5) / GRID_ROWS)
            if any(point_in_polygon(centre, mask) for mask in masks):
                continue
            x0, x1 = column * current.width // GRID_COLUMNS, (column + 1) * current.width // GRID_COLUMNS
            total = count = 0
            for y in range(y0, y1):
                base = y * current.width
                for x in range(x0, x1):
                    total += abs(current.pixels[base + x] - previous.pixels[base + x])
                    count += 1
            if count and total / count > threshold:
                cells.add((column, row))
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
