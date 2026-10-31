"""A heat map of where things were: counts per cell of a grid laid over the scene.

Privacy: the map holds ONLY aggregated positions (a count per cell). No picture,
no box, no track and no identity is kept or exported; a cell says "this much
activity here", never "who".

Memory: at most `slices` time slices, each a sparse table of at most
cols x rows cells, and cols x rows is capped by `max_cells` (never above 65536).

Window: with `window_seconds` the map remembers the last window, cut in
`slices` slices of window/slices seconds; the window is therefore exact to one
slice. With `half_life_seconds` each slice weighs 0.5 ** (age / half_life),
where the age is counted from the middle of the slice to the moment of the
snapshot. Without a window everything is kept in one slice and nothing is
forgotten.

Normalisation: `normalized = weight / max_weight` (0 for every cell when the
maximum is 0), so the busiest cell is always 1.0. The raw weights are exported
too, and the sum of the raw weights equals the number of accepted positions
when there is no decay and nothing has left the window.
"""
from __future__ import annotations

import json
import math
import struct
import zlib
from dataclasses import dataclass

from .activity_config import CELLS_HARD_MAX, HeatmapSettings

HEATMAP_SCHEMA = "armor.vision.heatmap/v1"
NORMALIZATION = "weight / max_weight; all zero when the maximum is zero"
MAX_IMAGE_SIDE = 4096


class Heatmap:
    def __init__(self, settings: HeatmapSettings) -> None:
        if settings.cols < 1 or settings.rows < 1 or settings.cols * settings.rows > min(settings.max_cells, CELLS_HARD_MAX):
            raise ValueError("the grid is empty or bigger than max_cells")
        if settings.half_life_seconds is not None and settings.window_seconds is None:
            raise ValueError("a half life needs a window")
        self.settings = settings
        self._slice_seconds = None if settings.window_seconds is None else settings.window_seconds / settings.slices
        self._slices: dict[int, dict[int, int]] = {}
        self._newest: int | None = None
        self._last_time: float | None = None
        self.accepted = 0
        self.rejected = 0

    def cell_of(self, point: tuple[float, float]) -> tuple[int, int] | None:
        """(col, row) of a normalised point, or None when it is not on the scene."""
        x, y = point
        if isinstance(x, bool) or isinstance(y, bool) or not (math.isfinite(x) and math.isfinite(y)):
            return None
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return None
        return min(int(x * self.settings.cols), self.settings.cols - 1), min(int(y * self.settings.rows), self.settings.rows - 1)

    def _slice_of(self, timestamp: float) -> int:
        return 0 if self._slice_seconds is None else math.floor(timestamp / self._slice_seconds)

    def add(self, timestamp: float, point: tuple[float, float]) -> bool:
        """Counts one position. Returns False (and counts it as rejected) when the time is not a
        finite number, the point is off the scene, or the time is older than the window."""
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            self.rejected += 1
            return False
        cell = self.cell_of(point)
        if cell is None:
            self.rejected += 1
            return False
        index = self._slice_of(timestamp)
        if self._newest is not None and self._slice_seconds is not None and index <= self._newest - self.settings.slices:
            self.rejected += 1
            return False
        if self._newest is None or index > self._newest:
            self._newest = index
            if self._slice_seconds is not None:
                for old in [i for i in self._slices if i <= index - self.settings.slices]:
                    del self._slices[old]
        table = self._slices.setdefault(index, {})
        key = cell[1] * self.settings.cols + cell[0]
        table[key] = table.get(key, 0) + 1
        if self._last_time is None or timestamp > self._last_time:
            self._last_time = timestamp
        self.accepted += 1
        return True

    def snapshot(self, now: float | None = None) -> "HeatmapSnapshot":
        """The weights as of `now` (default: the latest time seen)."""
        s = self.settings
        weights = [[0.0] * s.cols for _ in range(s.rows)]
        if now is None:
            now = self._last_time if self._last_time is not None else 0.0
        if math.isfinite(now):
            top = self._slice_of(now)
            for index in sorted(self._slices):
                if self._slice_seconds is not None and not top - s.slices < index <= top:
                    continue
                factor = 1.0
                if s.half_life_seconds is not None and self._slice_seconds is not None:
                    age = max(0.0, now - (index + 0.5) * self._slice_seconds)
                    factor = 0.5 ** (age / s.half_life_seconds)
                for key, count in self._slices[index].items():
                    weights[key // s.cols][key % s.cols] += count * factor
        return HeatmapSnapshot(s.cols, s.rows, weights, s.window_seconds, s.half_life_seconds, now if math.isfinite(now) else 0.0,
                               self.accepted, self.rejected)

    def cell_count(self) -> int:
        """How many cells hold something right now (the memory in use is bounded by slices x this)."""
        return sum(len(t) for t in self._slices.values())


@dataclass(frozen=True)
class HeatmapSnapshot:
    cols: int
    rows: int
    weights: list[list[float]]
    window_seconds: float | None
    half_life_seconds: float | None
    at: float
    accepted: int
    rejected: int

    @property
    def total(self) -> float:
        return sum(sum(row) for row in self.weights)

    @property
    def maximum(self) -> float:
        return max((max(row) for row in self.weights), default=0.0)

    def normalized(self) -> list[list[float]]:
        top = self.maximum
        if top <= 0.0:
            return [[0.0] * self.cols for _ in range(self.rows)]
        return [[w / top for w in row] for row in self.weights]

    def to_dict(self, camera_id: str | None = None) -> dict:
        return {
            "schema": HEATMAP_SCHEMA,
            "camera_id": camera_id,
            "cols": self.cols,
            "rows": self.rows,
            "window_seconds": self.window_seconds,
            "half_life_seconds": self.half_life_seconds,
            "at": self.at,
            "accepted_positions": self.accepted,
            "rejected_positions": self.rejected,
            "total": round(self.total, 6),
            "max": round(self.maximum, 6),
            "normalization": NORMALIZATION,
            "weights": [[round(w, 6) for w in row] for row in self.weights],
            "normalized": [[round(w, 6) for w in row] for row in self.normalized()],
            "contains_images": False,
        }

    def to_json(self, camera_id: str | None = None) -> str:
        return json.dumps(self.to_dict(camera_id), sort_keys=True)

    def _scale(self, scale: int) -> int:
        return max(1, min(int(scale), MAX_IMAGE_SIDE // max(self.cols, self.rows)))

    def to_png(self, scale: int = 16) -> bytes:
        """A PNG (8-bit RGB) of the normalised map, one block of scale x scale pixels per cell. Standard library only."""
        scale = self._scale(scale)
        width, height = self.cols * scale, self.rows * scale
        norm = self.normalized()
        raw = bytearray()
        for row in norm:
            line = bytearray([0])
            for value in row:
                line += bytes(colour(value)) * scale
            raw += bytes(line) * scale
        def chunk(kind: bytes, data: bytes) -> bytes:
            body = kind + data
            return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))

    def to_svg(self, scale: int = 16) -> str:
        """The same map as an SVG: one rectangle per cell that has activity."""
        scale = self._scale(scale)
        norm = self.normalized()
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.cols * scale}" height="{self.rows * scale}" '
                 f'viewBox="0 0 {self.cols} {self.rows}" shape-rendering="crispEdges">',
                 f'<rect width="{self.cols}" height="{self.rows}" fill="#101020"/>']
        for r, row in enumerate(norm):
            for c, value in enumerate(row):
                if value > 0.0:
                    red, green, blue = colour(value)
                    parts.append(f'<rect x="{c}" y="{r}" width="1" height="1" fill="#{red:02x}{green:02x}{blue:02x}"/>')
        parts.append("</svg>")
        return "\n".join(parts) + "\n"


def colour(value: float) -> tuple[int, int, int]:
    """Blue (little) to cyan, green, yellow and red (the most); 0 is the dark background."""
    if not value > 0.0:
        return 16, 16, 32
    value = min(1.0, value)
    stops = ((0.0, (0, 0, 255)), (0.25, (0, 255, 255)), (0.5, (0, 255, 0)), (0.75, (255, 255, 0)), (1.0, (255, 0, 0)))
    for index in range(1, len(stops)):
        v0, c0 = stops[index - 1]
        v1, c1 = stops[index]
        if value <= v1:
            t = (value - v0) / (v1 - v0)
            return (int(round(c0[0] + (c1[0] - c0[0]) * t)), int(round(c0[1] + (c1[1] - c0[1]) * t)),
                    int(round(c0[2] + (c1[2] - c0[2]) * t)))
    return 255, 0, 0
