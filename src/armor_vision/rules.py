"""Decides which tracked objects count as an alert or a detection.

An object counts in a zone when its feet are inside, its label is accepted,
it has been there for min_frames updates AND min_seconds, and the zone is
watched in the current arming mode. Each (object, zone) pair fires once per
visit; leaving the zone and coming back is a new visit. An object that has
stopped moving does not fire again.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CameraConfig, VisionConfig, Zone
from .geometry import foot_point, point_in_polygon
from .tracker import Track

EVENT_SCHEMA = "armor.vision.event/v1"


@dataclass
class _Visit:
    frames: int
    entered_at: float
    fired: bool = False


class Evaluator:
    def __init__(self, config: VisionConfig, mode: str | None = None) -> None:
        self._config = config
        self._visits: dict[tuple[str, int, str], _Visit] = {}
        self.mode = mode

    def set_mode(self, mode: str | None) -> None:
        self.mode = mode

    def watched(self, zone: Zone) -> bool:
        """With no mode, or a mode that has no profile, every zone is watched:
        an unknown mode must never silently watch less."""
        if self.mode is None or self.mode not in self._config.profiles:
            return True
        return zone.zone_id in self._config.profiles[self.mode]

    def evaluate(self, camera: CameraConfig, timestamp: float, tracks: list[Track]) -> list[dict]:
        events: list[dict] = []
        live = {(camera.camera_id, t.track_id) for t in tracks}
        for key in [k for k in self._visits if (k[0], k[1]) not in live and k[0] == camera.camera_id]:
            del self._visits[key]   # the object is gone: its visits end
        for track in tracks:
            foot = foot_point(track.box)
            for zone in camera.zones:
                key = (camera.camera_id, track.track_id, zone.zone_id)
                inside = (self.watched(zone) and (not zone.labels or track.label in zone.labels)
                          and point_in_polygon(foot, zone.points))
                if not inside:
                    self._visits.pop(key, None)
                    continue
                visit = self._visits.get(key)
                if visit is None:
                    visit = self._visits[key] = _Visit(0, timestamp)
                visit.frames += 1
                if visit.fired or track.stationary:
                    continue
                if visit.frames >= zone.min_frames and timestamp - visit.entered_at >= zone.min_seconds:
                    visit.fired = True
                    events.append(make_event(camera.camera_id, zone, track, timestamp))
        return events


def make_event(camera_id: str, zone: Zone, track: Track, timestamp: float) -> dict:
    """The message sent to the server. It reports what was seen; it never asks
    for anything to be done: authorizes_action is always false."""
    return {
        "schema": EVENT_SCHEMA,
        "type": zone.kind,
        "camera_id": camera_id,
        "zone_id": zone.zone_id,
        "zone_name": zone.name,
        "track_id": track.track_id,
        "label": track.label,
        "confidence": round(track.confidence, 3),
        "box": [round(v, 4) for v in track.box],
        "timestamp": timestamp,
        "authorizes_action": False,
    }
