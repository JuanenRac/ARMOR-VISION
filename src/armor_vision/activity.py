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
from typing import NamedTuple

from .activity_config import ActivityConfig, CountLine
from .config import VisionConfig, Zone
from .context_detection import CameraDetection
from .geometry import centre, foot_point, point_in_polygon, segments_cross, valid_box
from .heatmap import Heatmap, HeatmapSnapshot
from .pipeline import UnknownCameraError
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
        self._camera_lines: dict[str, tuple[CountLine, ...]] = {}
        self._camera_zones: dict[str, tuple[Zone, ...]] = {}
        self._camera_rules: dict[str, tuple[float, bool]] = {}   # per camera with zones of the server: the lowest confidence that counts and whether the people are told
        self._line_counts: dict[tuple[str, str], dict[str, int]] = {}   # (camera, line) -> crossings to the left and to the right since the start; one entry per line, never per crossing
        self.dropped_detections = 0
        self.events = 0

    @property
    def camera_ids(self) -> list[str]:
        return sorted(self._maps)

    def set_camera_lines(self, lines: dict[str, tuple[CountLine, ...]]) -> list[str]:
        """Replace the counting lines of the cameras (those the server drew) and return the ids of the cameras that are not in the configuration, which are ignored. They count together with the global ones of the configuration."""
        known = {camera_id: tuple(found) for camera_id, found in lines.items() if camera_id in self._maps}
        self._camera_lines = known
        alive = {(camera_id, line.line_id) for camera_id in self._maps for line in self._activity.events.lines + known.get(camera_id, ())}
        self._line_counts = {key: value for key, value in self._line_counts.items() if key in alive}   # the count of a line that was taken away goes with it
        return sorted(set(lines) - set(known))

    def set_camera_detection(self, detection: dict[str, CameraDetection], mode: str | None) -> list[str]:
        """Replace the detection zones the server drew (only the ones its profile for `mode` watches; every zone when the mode has no profile) and return the ids of the cameras that are not in the configuration, which are ignored. A zone whose id is already in the configuration of its camera is left out: the configured one stays. They report together with the zones of the configuration."""
        known: dict[str, tuple[Zone, ...]] = {}
        rules: dict[str, tuple[float, bool]] = {}
        floors = dict(zip(("low", "normal", "high"), self._activity.events.sensitivity_floor, strict=True))
        for camera_id, found in detection.items():
            if camera_id not in self._maps:
                continue
            taken = {zone.zone_id for zone in self._vision.cameras[camera_id].zones}
            watched = tuple(zone for zone in found.watched(mode) if zone.zone_id not in taken)
            if watched:
                known[camera_id] = watched
                profile = found.profile(mode)
                rules[camera_id] = (floors[profile.sensitivity] if profile else 0.0, profile.notify if profile else True)
        self._camera_zones = known
        self._camera_rules = rules
        return sorted(set(detection) - set(self._maps))

    def line_counts(self) -> dict[str, dict[str, dict[str, int]]]:
        """The crossings counted so far: camera -> line -> {"to_left", "to_right"}. Every line of every camera is listed, with zeros before anything crossed. Counts only: no track, no label, no picture."""
        out: dict[str, dict[str, dict[str, int]]] = {}
        for camera_id in sorted(self._maps):
            lines = self._activity.events.lines + self._camera_lines.get(camera_id, ())
            if not lines:
                continue
            out[camera_id] = {line.line_id: dict(self._line_counts.get((camera_id, line.line_id), {"to_left": 0, "to_right": 0})) for line in sorted(lines, key=lambda item: item.line_id)}
        return out

    def heatmap(self, camera_id: str) -> Heatmap:
        if camera_id not in self._maps:
            raise UnknownCameraError(f"camera {camera_id!r} is not in the configuration")
        return self._maps[camera_id]

    def run(self, source: DetectionSource) -> list[dict]:
        events: list[dict] = []
        for observation in source.observations():
            events.extend(self.process(observation.camera_id, observation.timestamp, list(observation.detections)))
        return events

    def process(self, camera_id: str, timestamp: float, detections: list[Detection]) -> list[dict]:
        camera = self._vision.cameras.get(camera_id)
        if camera is None:
            raise UnknownCameraError(f"camera {camera_id!r} is not in the configuration")
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
        tracker = self._trackers.setdefault(camera_id, Tracker(self._vision.max_tracks))
        seen = tracker.update(timestamp, kept)
        alive = {t.track_id: t for t in tracker.tracks}
        events: list[dict] = []
        extra = self._camera_zones.get(camera_id, ())
        floor, notify = self._camera_rules.get(camera_id, (0.0, True))
        extra_ids = {z.zone_id for z in extra}
        zone_events = self._zone_events(camera_id, camera.zones + extra, timestamp, seen, alive, extra_ids, floor)
        if not notify:
            for event in zone_events:
                if event.get("zone_id") in extra_ids:
                    event["notify"] = False   # the people the alarms go to are not told of this one; it is still reported
        events.extend(zone_events)
        events.extend(self._line_events(camera_id, timestamp, seen, alive))
        self.events += len(events)
        return events

    def _zone_events(self, camera_id: str, zones: tuple[Zone, ...], timestamp: float, seen: list[Track],
                     alive: dict[int, Track], floor_ids: frozenset[str] | set[str] = frozenset(), floor: float = 0.0) -> list[dict]:
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
                inside = ((not zone.labels or track.label in zone.labels) and point_in_polygon(foot, zone.points)
                          and (zone.zone_id not in floor_ids or track.confidence >= floor))
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
        lines = self._activity.events.lines + self._camera_lines.get(camera_id, ())
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
                    self._line_counts.setdefault((camera_id, line.line_id), {"to_left": 0, "to_right": 0})[direction] += 1
                    events.append(_event("line_cross", camera_id, timestamp, track, line_id=line.line_id, direction=direction))
        return events


class HeatmapPlan(NamedTuple):
    """What is left to draw once a query has been checked: the snapshot of the map, the camera, the format and the scale."""
    snapshot: HeatmapSnapshot
    camera_id: str
    fmt: str
    scale: int


def heatmap_plan(engine: ActivityEngine | None, query: dict[str, str]) -> tuple[int, str, bytes] | HeatmapPlan:
    """The first half of `heatmap_route`: the query is checked and the map is read out of the engine. Returns the finished answer (the 4xx of a bad query, the 404 of an engine that is off)
    or the plan to draw: the snapshot, which no longer depends on the engine, so a service can let go of its lock before it draws."""
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
    if fmt not in ("json", "png", "svg"):
        return text(400, "format must be json, png or svg")
    return HeatmapPlan(engine.heatmap(camera_id).snapshot(), camera_id, fmt, int(scale_text))


def heatmap_draw(plan: HeatmapPlan) -> tuple[int, str, bytes]:
    """The second half: draws the plan. It touches nothing of the engine."""
    snapshot, camera_id, fmt, scale = plan.snapshot, plan.camera_id, plan.fmt, plan.scale
    if fmt == "json":
        return 200, "application/json", snapshot.to_json(camera_id).encode()
    if fmt == "png":
        return 200, "image/png", snapshot.to_png(scale)
    return 200, "image/svg+xml", snapshot.to_svg(scale).encode()


def heatmap_route(engine: ActivityEngine | None, query: dict[str, str]) -> tuple[int, str, bytes]:
    """The handler for `GET /heatmap?camera=ID&format=json|png|svg&scale=N`, for the service that will
    mount it. Returns (status, content type, body). Off (no engine): 404, as if the route did not exist."""
    planned = heatmap_plan(engine, query)
    return heatmap_draw(planned) if isinstance(planned, HeatmapPlan) else planned
