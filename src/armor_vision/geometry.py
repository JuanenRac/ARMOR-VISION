"""Plane geometry on normalised image coordinates (0..1 on both axes)."""
from __future__ import annotations

from typing import Sequence

Point = tuple[float, float]
Box = tuple[float, float, float, float]  # x_min, y_min, x_max, y_max


def valid_polygon(points: Sequence[Sequence[float]]) -> str | None:
    """Why a polygon cannot be used, or None when it can."""
    if not isinstance(points, (list, tuple)) or len(points) < 3:
        return "a polygon needs at least 3 points"
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            return "every point must be [x, y]"
        for value in point:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return "coordinates must be numbers"
            if not 0.0 <= float(value) <= 1.0:
                return "coordinates must be between 0 and 1"
    if _area(points) == 0.0:
        return "the polygon has no area"
    return None


def _area(points: Sequence[Sequence[float]]) -> float:
    total = 0.0
    for index, (x1, y1) in enumerate(points):
        x2, y2 = points[(index + 1) % len(points)]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def point_in_polygon(point: Point, polygon: Sequence[Sequence[float]]) -> bool:
    """Ray casting; a point exactly on an edge counts as inside."""
    x, y = point
    inside = False
    count = len(polygon)
    for index in range(count):
        x1, y1 = polygon[index]
        x2, y2 = polygon[(index + 1) % count]
        if _on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            crossing = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < crossing:
                inside = not inside
    return inside


def _on_segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-12:
        return False
    return min(x1, x2) - 1e-12 <= x <= max(x1, x2) + 1e-12 and min(y1, y2) - 1e-12 <= y <= max(y1, y2) + 1e-12


def foot_point(box: Box) -> Point:
    """Bottom centre of a box: where the object touches the ground."""
    return ((box[0] + box[2]) / 2.0, box[3])


def centre(box: Box) -> Point:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def iou(a: Box, b: Box) -> float:
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    if right <= left or bottom <= top:
        return 0.0
    inter = (right - left) * (bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def valid_box(box: Sequence[float]) -> bool:
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        return False
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box):
        return False
    return 0.0 <= box[0] < box[2] <= 1.0 and 0.0 <= box[1] < box[3] <= 1.0
