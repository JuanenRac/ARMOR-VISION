"""Which recorded segments make up a clip (with the seconds before and after the event) and which clips may be erased.

The recording of `streams.py` is a row of segment files named by their start time. An event does not start a recording: it picks, from
what is already on disk, the segments from `pre_seconds` before the first trigger to `post_seconds` after the last one, so the clip
shows what led to it and how it ended. A new trigger while a clip is open extends it (up to `max_clip_seconds`). Retention is a plan
by type: each label has its own number of days, the footage with no event another one, and the plan is a list - nothing is erased
unless the caller hands over the function that erases.
"""
from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SEGMENT_PATTERN = re.compile(r"^(\d{8})-(\d{6})\.[a-z0-9]{2,4}$")
DEFAULT_PRE, DEFAULT_POST, DEFAULT_MAX_CLIP = 5.0, 10.0, 300.0
CONTINUOUS = "continuous"       # the key of the retention of footage with no event


@dataclass(frozen=True)
class Segment:
    path: str
    start: float                 # seconds since the epoch
    seconds: float

    @property
    def end(self) -> float:
        return self.start + self.seconds


def segment_from_name(name: str, seconds: float, utc: bool = True) -> Segment | None:
    """The segment a file name stands for (`20260131-101500.mkv`), or None when the name is not one of the recorder's."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    match = SEGMENT_PATTERN.match(base)
    if not match:
        return None
    try:
        moment = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return Segment(name, (moment.replace(tzinfo=timezone.utc) if utc else moment).timestamp(), float(seconds))


@dataclass(frozen=True)
class RecordingSettings:
    pre_seconds: float = DEFAULT_PRE
    post_seconds: float = DEFAULT_POST
    max_clip_seconds: float = DEFAULT_MAX_CLIP


def parse_recording_settings(raw: Any) -> tuple[RecordingSettings | None, list[str]]:
    if not isinstance(raw, dict):
        return None, ["the recording settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - {'pre_seconds', 'post_seconds', 'max_clip_seconds'}))}"] if set(raw) - {"pre_seconds", "post_seconds", "max_clip_seconds"} else []
    values = {}
    for name, default, low in (("pre_seconds", DEFAULT_PRE, 0.0), ("post_seconds", DEFAULT_POST, 0.0), ("max_clip_seconds", DEFAULT_MAX_CLIP, 1.0)):
        value = raw.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= 3600:
            errors.append(f"{name} must be a number from {low:g} to 3600")
        values[name] = value
    if errors:
        return None, errors
    return RecordingSettings(float(values["pre_seconds"]), float(values["post_seconds"]), float(values["max_clip_seconds"])), []


@dataclass(frozen=True)
class Clip:
    clip_id: str
    camera_id: str
    label: str                   # the type of the event that opened it (its retention follows it)
    start: float
    end: float
    triggers: int
    segments: tuple[Segment, ...]


def select_segments(segments: Iterable[Segment], start: float, end: float) -> tuple[Segment, ...]:
    """The segments that overlap [start, end], in time order."""
    return tuple(sorted((s for s in segments if s.end > start and s.start < end), key=lambda s: s.start))


@dataclass
class _Open:
    label: str
    first: float
    last: float
    triggers: int = 1


@dataclass
class ClipPlanner:
    settings: RecordingSettings = field(default_factory=RecordingSettings)
    _open: dict[str, _Open] = field(default_factory=dict)
    _counter: int = 0

    def trigger(self, camera_id: str, label: str, timestamp: float) -> None:
        """An event at `timestamp` on this camera: opens a clip, or keeps the open one going (the label of the first trigger stays)."""
        current = self._open.get(camera_id)
        if current is None:
            self._open[camera_id] = _Open(label, timestamp, timestamp)
        else:
            current.last = max(current.last, timestamp)
            current.triggers += 1

    def due(self, now: float, segments_of: Callable[[str], Iterable[Segment]]) -> list[Clip]:
        """The clips that are complete at `now`: `post_seconds` have passed since the last trigger, or the clip reached its maximum length.
        Those still waiting for footage that has not been written yet stay open."""
        clips: list[Clip] = []
        for camera_id in sorted(self._open):
            item = self._open[camera_id]
            start = item.first - self.settings.pre_seconds
            end = min(item.last + self.settings.post_seconds, start + self.settings.max_clip_seconds)
            if now < end:
                continue
            del self._open[camera_id]
            self._counter += 1
            clips.append(Clip(f"clip-{self._counter:06d}", camera_id, item.label, start, end, item.triggers, select_segments(segments_of(camera_id), start, end)))
        return clips

    @property
    def open_cameras(self) -> list[str]:
        return sorted(self._open)


def parse_retention(raw: Any) -> tuple[dict[str, float] | None, list[str]]:
    """Days to keep per type of event, plus `continuous` for footage with no event and `default` for a type not listed."""
    if not isinstance(raw, dict) or not raw:
        return None, ["retention must be an object of days per type (person, vehicle, ..., continuous, default)"]
    errors = []
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            errors.append("a type of event is a name")
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 3650:
            errors.append(f"{key}: days must be a number from 0 to 3650")
    if errors:
        return None, errors
    return {str(k): float(v) for k, v in raw.items()}, []


@dataclass(frozen=True)
class Erasure:
    path: str
    reason: str                  # the type whose retention ran out
    age_days: float


def days_for(retention: dict[str, float], label: str | None) -> float:
    if label is None:
        return retention.get(CONTINUOUS, retention.get("default", 7.0))
    return retention.get(label, retention.get("default", 7.0))


def plan_retention(retention: dict[str, float], now: float, clips: Iterable[Clip], segments: Iterable[Segment]) -> list[Erasure]:
    """What to erase. A segment that belongs to a clip lives as long as the LONGEST retention among the clips that use it; one that belongs to none follows `continuous`."""
    keep_days: dict[str, float] = {}
    reasons: dict[str, str] = {}
    for clip in clips:
        days = days_for(retention, clip.label)
        for segment in clip.segments:
            if days >= keep_days.get(segment.path, -1.0):
                keep_days[segment.path], reasons[segment.path] = days, clip.label
    plan = []
    for segment in sorted(segments, key=lambda s: s.start):
        label = reasons.get(segment.path)
        days = keep_days[segment.path] if label is not None else days_for(retention, None)
        age = (now - segment.end) / 86400.0
        if age > days:
            plan.append(Erasure(segment.path, label or CONTINUOUS, round(age, 3)))
    return plan


def apply_retention(plan: Iterable[Erasure], erase: Callable[[str], None] | None = None) -> int:
    """Erases the planned files with the function the caller gives; without one nothing is touched (a dry run). Returns how many were erased."""
    if erase is None:
        return 0
    count = 0
    for item in plan:
        erase(item.path)
        count += 1
    return count
