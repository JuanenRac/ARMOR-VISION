"""Different motion masks and sensitivity by hour of the day, and profiles for day, night and away.

A camera that sees a tree move in the wind by day needs another mask at night, and a house with nobody in it can afford a more
sensitive movement check than one with people. A schedule is a list of windows per camera: from-to (local time, a window may cross
midnight), optional weekdays, optional arming mode, and what it changes - extra masks, the grey difference that counts as movement
and the changed cells needed to run the detector. The first window that matches wins; with none the camera keeps its own values.
Times are read from the timestamp of the frame in the local time of the machine, or in a fixed offset when the schedule gives one.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .config import CameraConfig
from .geometry import rect_polygon, valid_polygon

CLOCK = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
WINDOW_FIELDS = {"name", "from", "to", "days", "mode", "masks", "motion_threshold", "motion_min_cells"}
DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Window:
    name: str
    start: int                          # minutes since midnight
    end: int
    days: tuple[int, ...]               # 0 = Monday; empty = every day
    mode: str | None
    masks: tuple[tuple[tuple[float, float], ...], ...]
    motion_threshold: int | None
    motion_min_cells: int | None

    def covers(self, minute: int, weekday: int, mode: str | None) -> bool:
        if self.mode is not None and self.mode != mode:
            return False
        if self.start == self.end:
            inside, day = True, weekday
        elif self.start < self.end:
            inside, day = self.start <= minute < self.end, weekday
        else:                           # crosses midnight: the part after midnight belongs to the day that started the window
            inside = minute >= self.start or minute < self.end
            day = weekday if minute >= self.start else (weekday - 1) % 7
        return inside and (not self.days or day in self.days)


@dataclass(frozen=True)
class Effective:
    name: str | None
    masks: tuple[tuple[tuple[float, float], ...], ...]
    motion_threshold: int
    motion_min_cells: int


@dataclass(frozen=True)
class Schedule:
    windows: dict[str, tuple[Window, ...]]
    utc_offset_minutes: int | None = None     # None: the local time of the machine

    def effective(self, camera: CameraConfig, timestamp: float, mode: str | None = None) -> Effective:
        minute, weekday = self._clock(timestamp)
        for window in self.windows.get(camera.camera_id, ()):
            if window.covers(minute, weekday, mode):
                return Effective(window.name, camera.masks + window.masks,
                                 camera.motion_threshold if window.motion_threshold is None else window.motion_threshold,
                                 camera.motion_min_cells if window.motion_min_cells is None else window.motion_min_cells)
        return Effective(None, camera.masks, camera.motion_threshold, camera.motion_min_cells)

    def _clock(self, timestamp: float) -> tuple[int, int]:
        if self.utc_offset_minutes is None:
            moment = time.localtime(timestamp)
            return moment.tm_hour * 60 + moment.tm_min, moment.tm_wday
        moment = datetime.fromtimestamp(timestamp, timezone.utc) + timedelta(minutes=self.utc_offset_minutes)
        return moment.hour * 60 + moment.minute, moment.weekday()


def parse_schedule(raw: Any, known_cameras: set[str] | None = None) -> tuple[Schedule | None, list[str]]:
    """`{"utc_offset_minutes": 60, "cameras": {"garage": [{"name": "night", "from": "22:00", "to": "06:00", "motion_threshold": 18}, ...]}}`."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["the schedule must be an object"]
    unknown = sorted(set(raw) - {"utc_offset_minutes", "cameras"})
    if unknown:
        errors.append(f"unknown field(s): {', '.join(unknown)}")
    offset = raw.get("utc_offset_minutes")
    if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int) or not -720 <= offset <= 840):
        errors.append("utc_offset_minutes must be a whole number of minutes from -720 to 840 (or left out for the local time)")
        offset = None
    cameras = raw.get("cameras", {})
    if not isinstance(cameras, dict):
        return None, errors + ["cameras must be an object keyed by camera id"]
    result: dict[str, tuple[Window, ...]] = {}
    for camera_id, entries in cameras.items():
        where = f"camera {camera_id!r}"
        if known_cameras is not None and camera_id not in known_cameras:
            errors.append(f"{where}: is not in the configuration")
        if not isinstance(entries, list):
            errors.append(f"{where}: must be a list of windows")
            continue
        windows = []
        for index, entry in enumerate(entries):
            window = _window(entry, f"{where} window #{index + 1}", errors)
            if window is not None:
                windows.append(window)
        result[str(camera_id)] = tuple(windows)
    if errors:
        return None, errors
    return Schedule(result, offset), []


def _window(entry: Any, where: str, errors: list[str]) -> Window | None:
    if not isinstance(entry, dict):
        errors.append(f"{where}: must be an object")
        return None
    before = len(errors)
    if set(entry) - WINDOW_FIELDS:
        errors.append(f"{where}: unknown field(s): {', '.join(sorted(set(entry) - WINDOW_FIELDS))}")
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        errors.append(f"{where}: name is required (day, night, away or your own)")
    minutes = []
    for key in ("from", "to"):
        match = CLOCK.match(entry.get(key)) if isinstance(entry.get(key), str) else None
        if not match:
            errors.append(f"{where}: {key} is a time HH:MM")
            minutes.append(0)
        else:
            minutes.append(int(match.group(1)) * 60 + int(match.group(2)))
    days = entry.get("days", [])
    day_numbers = []
    if not isinstance(days, list) or not all(d in DAYS for d in days):
        errors.append(f"{where}: days is a list of {', '.join(DAYS)}")
    else:
        day_numbers = sorted({DAYS.index(d) for d in days})
    mode = entry.get("mode")
    if mode is not None and (not isinstance(mode, str) or not mode):
        errors.append(f"{where}: mode is the name of an arming mode")
    masks = []
    raw_masks = entry.get("masks", [])
    if not isinstance(raw_masks, list):
        errors.append(f"{where}: masks must be a list")
        raw_masks = []
    for number, mask in enumerate(raw_masks):
        if isinstance(mask, dict):
            points, problem = rect_polygon(mask)
        else:
            points, problem = mask, valid_polygon(mask)
        if problem or points is None:
            errors.append(f"{where} mask #{number + 1}: {problem}")
            continue
        masks.append(tuple((float(x), float(y)) for x, y in points))
    threshold = entry.get("motion_threshold")
    if threshold is not None and (isinstance(threshold, bool) or not isinstance(threshold, int) or not 1 <= threshold <= 255):
        errors.append(f"{where}: motion_threshold must be a whole number from 1 to 255")
    cells = entry.get("motion_min_cells")
    if cells is not None and (isinstance(cells, bool) or not isinstance(cells, int) or cells < 1):
        errors.append(f"{where}: motion_min_cells must be a whole number of at least 1")
    if len(errors) > before:
        return None
    return Window(str(name), minutes[0], minutes[1], tuple(day_numbers), mode, tuple(masks), threshold, cells)
