"""From detections to activity events and a heat map, behind a switch that is off by default.

Events (`armor.vision.activity/v1`): `zone_enter`, `zone_exit`, `dwell`
(inside a zone for dwell_seconds), `loiter` (inside for loiter_seconds without
leaving a small box) and `line_cross` (the feet crossed a counting line).
They only report: `authorizes_action` is always false. Nothing but positions,
labels and counts is kept: no picture of anybody is stored or exported.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .activity_config import ActivityConfig, CountLine
from .config import VisionConfig, Zone
from .geometry import centre, foot_point, point_in_polygon, segments_cross, valid_box
from .heatmap import Heatmap
from .sources import DetectionSource
from .tracker import Detection, Track, Tracker

ACTIVITY_SCHEMA = "armor.vision.activity/v1"


class ActivityDisabled(RuntimeError):
    """The activity pipeline is switched off in the configuration."""


@dataclass
class _Presence:
    entered_at: float
    label: str
    min_x: float
    max_x: float
    min_y: float
    max_y: float
    dwell_fired: bool = False
    loiter_fired: bool = False


def _event(kind: str, camera_id: str, timestamp: float, track: Track, **extra: object) -> dict:
    event: dict = {"schema": ACTIVITY_SCHEMA, "type": kind, "camera_id": camera_id, "track_id": track.track_id,
                   "label": track.label, "timestamp": timestamp, "timestamp_ms": int(round(timestamp * 1000)),
                   "authorizes_action": False}
    event.update(extra)
    return event


def _side(line: CountLine, point: tuple[float, float]) -> float:
    return (line.b[0] - line.a[0]) * (point[1] - line.a[1]) - (line.b[1] - line.a[1]) * (point[0] - line.a[0])


class ActivityEngine:
    def __init__(self, vision: VisionConfig, activity: ActivityConfig) -> None:
        if not activity.enabled:
            raise ActivityDisabled("the activity pipeline is off (enabled is false)")
        self._vision, self._activity = vision, activity
        self._trackers: dict[str, Tracker] = {}
        self._presence: dict[tuple[str, int, str], _Presence] = {}
        self._last_foot: dict[tuple[str, int], tuple[float, float]] = {}
        self._maps = {camera_id: Heatmap(activity.heatmap) for camera_id in vision.cameras}
        self.dropped_detections = 0
        self.events = 0

    @property
    def camera_ids(self) -> list[str]:
        return sorted(self._maps)

    def heatmap(self, camera_id: str) -> Heatmap:
        if camera_id not in self._maps:
            raise KeyError(f"camera {camera_id!r} is not in the configuration")
        return self._maps[camera_id]

    def run(self, source: DetectionSource) -> list[dict]:
        events: list[dict] = []
        for observation in source.observations():
            events.extend(self.process(observation.camera_id, observation.timestamp, list(observation.detections)))
        return events

    def process(self, camera_id: str, timestamp: float, detections: list[Detection]) -> list[dict]:
        camera = self._vision.cameras.get(camera_id)
        if camera is None:
            raise KeyError(f"camera {camera_id!r} is not in the configuration")
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise ValueError("timestamp must be a finite number")
        heat = self._maps[camera_id]
        use_foot = self._activity.heatmap.position == "foot"
        heat_labels = self._activity.heatmap.labels
        kept = []
        for d in detections:
            c = d.confidence
            if (not valid_box(d.box) or isinstance(c, bool) or not isinstance(c, (int, float)) or not 0.0 <= c <= 1.0
                    or any(point_in_polygon(centre(d.box), m) for m in camera.masks)):
                self.dropped_detections += 1
                continue
            kept.append(d)
            if not heat_labels or d.label in heat_labels:
                heat.add(timestamp, foot_point(d.box) if use_foot else centre(d.box))
        tracker = self._trackers.setdefault(camera_id, Tracker())
        seen = tracker.update(timestamp, kept)
        alive = {t.track_id: t for t in tracker.tracks}
        events: list[dict] = []
        events.extend(self._zone_events(camera_id, camera.zones, timestamp, seen, alive))
        events.extend(self._line_events(camera_id, timestamp, seen, alive))
        self.events += len(events)
        return events

    def _zone_events(self, camera_id: str, zones: tuple[Zone, ...], timestamp: float, seen: list[Track],
                     alive: dict[int, Track]) -> list[dict]:
        cfg = self._activity.events
        events: list[dict] = []
        for key in sorted(k for k in self._presence if k[0] == camera_id and (k[1] not in alive or timestamp - alive[k[1]].last_seen > cfg.lost_seconds)):
            events.append(self._exit(camera_id, key, self._presence.pop(key), timestamp))
        for track in seen:
            if cfg.labels and track.label not in cfg.labels:
                continue
            foot = foot_point(track.box)
            for zone in zones:
                key = (camera_id, track.track_id, zone.zone_id)
                inside = (not zone.labels or track.label in zone.labels) and point_in_polygon(foot, zone.points)
                presence = self._presence.get(key)
                if not inside:
                    if presence is not None:
                        del self._presence[key]
                        events.append(self._exit(camera_id, key, presence, timestamp))
                    continue
                if presence is None:
                    self._presence[key] = _Presence(timestamp, track.label, foot[0], foot[0], foot[1], foot[1])
                    events.append(_event("zone_enter", camera_id, timestamp, track, zone_id=zone.zone_id, zone_name=zone.name))
                    continue
                presence.min_x, presence.max_x = min(presence.min_x, foot[0]), max(presence.max_x, foot[0])
                presence.min_y, presence.max_y = min(presence.min_y, foot[1]), max(presence.max_y, foot[1])
                stay = timestamp - presence.entered_at
                if not presence.dwell_fired and stay >= cfg.dwell_seconds:
                    presence.dwell_fired = True
                    events.append(_event("dwell", camera_id, timestamp, track, zone_id=zone.zone_id, zone_name=zone.name,
                                         seconds=round(stay, 3)))
                spread = max(presence.max_x - presence.min_x, presence.max_y - presence.min_y)
                if not presence.loiter_fired and stay >= cfg.loiter_seconds and spread <= cfg.loiter_radius:
                    presence.loiter_fired = True
                    events.append(_event("loiter", camera_id, timestamp, track, zone_id=zone.zone_id, zone_name=zone.name,
                                         seconds=round(stay, 3)))
        return events

    @staticmethod
    def _exit(camera_id: str, key: tuple[str, int, str], presence: _Presence, timestamp: float) -> dict:
        event = {"schema": ACTIVITY_SCHEMA, "type": "zone_exit", "camera_id": camera_id, "track_id": key[1],
                 "label": presence.label, "timestamp": timestamp, "timestamp_ms": int(round(timestamp * 1000)),
                 "authorizes_action": False, "zone_id": key[2], "seconds": round(timestamp - presence.entered_at, 3)}
        return event

    def _line_events(self, camera_id: str, timestamp: float, seen: list[Track], alive: dict[int, Track]) -> list[dict]:
        events: list[dict] = []
        for key in [k for k in self._last_foot if k[0] == camera_id and k[1] not in alive]:
            del self._last_foot[key]
        lines = self._activity.events.lines
        for track in seen:
            foot = foot_point(track.box)
            previous = self._last_foot.get((camera_id, track.track_id))
            self._last_foot[(camera_id, track.track_id)] = foot
            if previous is None:
                continue
            for line in lines:
                if line.labels and track.label not in line.labels:
                    continue
                if segments_cross(previous, foot, line.a, line.b):
                    direction = "to_left" if _side(line, foot) > 0 else "to_right"
                    events.append(_event("line_cross", camera_id, timestamp, track, line_id=line.line_id, direction=direction))
        return events


def heatmap_route(engine: ActivityEngine | None, query: dict[str, str]) -> tuple[int, str, bytes]:
    """The handler for `GET /heatmap?camera=ID&format=json|png|svg&scale=N`, for the service that will
    mount it. Returns (status, content type, body). Off (no engine): 404, as if the route did not exist."""
    def text(status: int, message: str) -> tuple[int, str, bytes]:
        return status, "text/plain; charset=utf-8", (message + "\n").encode()
    if engine is None:
        return text(404, "not found")
    unknown = sorted(set(query) - {"camera", "format", "scale"})
    if unknown:
        return text(400, f"unknown parameter(s): {', '.join(unknown)}")
    camera_id = query.get("camera")
    if camera_id is None:
        ids = engine.camera_ids
        if len(ids) != 1:
            return text(400, "camera is required")
        camera_id = ids[0]
    if camera_id not in engine.camera_ids:
        return text(404, "unknown camera")
    fmt = query.get("format", "json")
    scale_text = query.get("scale", "16")
    if not scale_text.isdecimal() or not 1 <= int(scale_text) <= 64:
        return text(400, "scale must be a whole number from 1 to 64")
    snapshot = engine.heatmap(camera_id).snapshot()
    if fmt == "json":
        return 200, "application/json", snapshot.to_json(camera_id).encode()
    if fmt == "png":
        return 200, "image/png", snapshot.to_png(int(scale_text))
    if fmt == "svg":
        return 200, "image/svg+xml", snapshot.to_svg(int(scale_text)).encode()
    return text(400, "format must be json, png or svg")
