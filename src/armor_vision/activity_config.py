"""The configuration of the activity pipeline (events and heat map).

Everything that can be tuned lives in this file and not in the code. The whole
pipeline is OFF unless `enabled` is true: with the default the library and the
command line behave exactly as before. Unknown fields and values out of range
are errors and any error means no configuration at all (fail closed).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

CELLS_HARD_MAX = 65536          # no heat map may hold more cells than this, whatever the file says
SLICES_HARD_MAX = 240           # time slices kept by a windowed heat map
LINES_HARD_MAX = 64
POSITIONS = ("foot", "centre")


@dataclass(frozen=True)
class HeatmapSettings:
    cols: int = 32
    rows: int = 18
    window_seconds: float | None = 300.0     # None = everything since the start, no forgetting
    half_life_seconds: float | None = None   # None = no decay; needs a window
    slices: int = 60                         # the window is cut in this many slices (its accuracy)
    max_cells: int = 4096
    position: str = "foot"
    labels: tuple[str, ...] = ()             # empty = every label counts


@dataclass(frozen=True)
class CountLine:
    line_id: str
    a: tuple[float, float]
    b: tuple[float, float]
    labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventSettings:
    dwell_seconds: float = 5.0               # inside a zone this long: one `dwell` event
    loiter_seconds: float = 20.0             # inside this long and hardly moving: one `loiter` event
    loiter_radius: float = 0.05              # normalised size of the box the feet may move in while loitering
    lost_seconds: float = 2.0                # not seen this long: the visit to a zone is over (a `zone_exit`)
    labels: tuple[str, ...] = ()
    lines: tuple[CountLine, ...] = ()


@dataclass(frozen=True)
class ActivityConfig:
    enabled: bool = False
    heatmap: HeatmapSettings = field(default_factory=HeatmapSettings)
    events: EventSettings = field(default_factory=EventSettings)


def _num(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _int(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, int)


def _labels(value: Any, where: str, errors: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) and v for v in value):
        errors.append(f"{where}: labels must be a list of names")
        return ()
    return tuple(value)


def _section(raw: Any, name: str, allowed: set[str], errors: list[str]) -> dict[str, Any]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        errors.append(f"{name} must be an object")
        return {}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        errors.append(f"{name}: unknown field(s): {', '.join(unknown)}")
    return raw


def parse_heatmap(raw: Any, errors: list[str]) -> HeatmapSettings:
    section = _section(raw, "heatmap", {"cols", "rows", "window_seconds", "half_life_seconds", "slices",
                                        "max_cells", "position", "labels"}, errors)
    d = HeatmapSettings()
    cols, rows = section.get("cols", d.cols), section.get("rows", d.rows)
    max_cells = section.get("max_cells", d.max_cells)
    window = section.get("window_seconds", d.window_seconds)
    half_life = section.get("half_life_seconds", d.half_life_seconds)
    slices = section.get("slices", d.slices)
    position = section.get("position", d.position)
    if not _int(max_cells) or not 1 <= max_cells <= CELLS_HARD_MAX:
        errors.append(f"heatmap: max_cells must be a whole number from 1 to {CELLS_HARD_MAX}")
        max_cells = d.max_cells
    if not _int(cols) or not _int(rows) or cols < 1 or rows < 1:
        errors.append("heatmap: cols and rows must be whole numbers of at least 1")
        cols, rows = d.cols, d.rows
    elif cols * rows > max_cells:
        errors.append(f"heatmap: cols x rows ({cols * rows}) is over max_cells ({max_cells})")
    if window is not None and (not _num(window) or not 1 <= window <= 7 * 86400):
        errors.append("heatmap: window_seconds must be null or a number from 1 to 604800")
        window = d.window_seconds
    if half_life is not None and (not _num(half_life) or half_life <= 0):
        errors.append("heatmap: half_life_seconds must be null or a number above 0")
        half_life = None
    if half_life is not None and window is None:
        errors.append("heatmap: half_life_seconds needs a window_seconds (the memory of a map without a window is not bounded by time)")
    if not _int(slices) or not 1 <= slices <= SLICES_HARD_MAX:
        errors.append(f"heatmap: slices must be a whole number from 1 to {SLICES_HARD_MAX}")
        slices = d.slices
    if position not in POSITIONS:
        errors.append(f"heatmap: position must be one of {', '.join(POSITIONS)}")
        position = d.position
    labels = _labels(section["labels"], "heatmap", errors) if "labels" in section else ()
    return HeatmapSettings(int(cols), int(rows), None if window is None else float(window),
                           None if half_life is None else float(half_life), int(slices), int(max_cells),
                           str(position), labels)


def parse_events(raw: Any, errors: list[str]) -> EventSettings:
    section = _section(raw, "events", {"dwell_seconds", "loiter_seconds", "loiter_radius", "lost_seconds", "labels", "lines"}, errors)
    d = EventSettings()
    values: dict[str, float] = {}
    for key, default, low, high in (("dwell_seconds", d.dwell_seconds, 0.0, 86400.0),
                                    ("loiter_seconds", d.loiter_seconds, 0.0, 86400.0),
                                    ("loiter_radius", d.loiter_radius, 0.0, 1.0),
                                    ("lost_seconds", d.lost_seconds, 0.0, 3600.0)):
        value = section.get(key, default)
        if not _num(value) or not low <= value <= high:
            errors.append(f"events: {key} must be a number from {low:g} to {high:g}")
            value = default
        values[key] = float(value)
    labels = _labels(section["labels"], "events", errors) if "labels" in section else ()
    lines: list[CountLine] = []
    raw_lines = section.get("lines", [])
    if not isinstance(raw_lines, list) or len(raw_lines) > LINES_HARD_MAX:
        errors.append(f"events: lines must be a list of at most {LINES_HARD_MAX}")
        raw_lines = []
    seen: set[str] = set()
    for index, line in enumerate(raw_lines):
        where = f"events line #{index + 1}"
        if not isinstance(line, dict):
            errors.append(f"{where}: must be an object")
            continue
        unknown = sorted(set(line) - {"id", "a", "b", "labels"})
        if unknown:
            errors.append(f"{where}: unknown field(s): {', '.join(unknown)}")
        line_id = line.get("id")
        if not isinstance(line_id, str) or not line_id:
            errors.append(f"{where}: id is required")
            continue
        if line_id in seen:
            errors.append(f"{where}: id {line_id!r} is used twice")
        seen.add(line_id)
        ends = []
        for end in ("a", "b"):
            point = line.get(end)
            if (not isinstance(point, list) or len(point) != 2 or not all(_num(v) and 0.0 <= v <= 1.0 for v in point)):
                errors.append(f"{where} ({line_id}): {end} must be [x, y] with both between 0 and 1")
                break
            ends.append((float(point[0]), float(point[1])))
        else:
            if ends[0] == ends[1]:
                errors.append(f"{where} ({line_id}): a and b are the same point")
                continue
            line_labels = _labels(line["labels"], where, errors) if "labels" in line else ()
            lines.append(CountLine(line_id, ends[0], ends[1], line_labels))
    return EventSettings(values["dwell_seconds"], values["loiter_seconds"], values["loiter_radius"], values["lost_seconds"], labels, tuple(lines))


def parse_activity_config(raw: Any) -> tuple[ActivityConfig | None, list[str]]:
    """Returns (config, errors); with any error the config is None."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["the activity configuration must be an object"]
    unknown = sorted(set(raw) - {"enabled", "heatmap", "events"})
    if unknown:
        errors.append(f"unknown top-level field(s): {', '.join(unknown)}")
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        errors.append("enabled must be true or false")
        enabled = False
    heatmap = parse_heatmap(raw.get("heatmap"), errors)
    events = parse_events(raw.get("events"), errors)
    if errors:
        return None, errors
    return ActivityConfig(enabled, heatmap, events), []


ACTIVITY_EXAMPLE: dict[str, Any] = {
    "enabled": True,
    "heatmap": {"cols": 32, "rows": 18, "window_seconds": 300, "half_life_seconds": None,
                "slices": 60, "max_cells": 4096, "position": "foot", "labels": []},
    "events": {"dwell_seconds": 3.0, "loiter_seconds": 6.0, "loiter_radius": 0.05, "lost_seconds": 2.0, "labels": [],
               "lines": [{"id": "gate", "a": [0.3, 0.7], "b": [0.9, 0.7]}]},
}
