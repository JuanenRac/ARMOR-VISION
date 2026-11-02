"""Decides which tracked objects count as an alert or a detection.

An object counts in a zone when its feet are inside, its label is accepted,
it has been there for min_frames updates AND min_seconds, and the zone is
watched in the current arming mode. Each (object, zone) pair fires once per
visit; leaving the zone and coming back is a new visit. An object that was
already standing still when it came into the zone (a parked car) makes no
event; one that comes in and then stops (somebody loitering at a door) does,
once it has been there long enough. A track that the detector misses for a
moment keeps its visit.
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import CameraConfig, VisionConfig, Zone
from .geometry import foot_point, point_in_polygon
from .tracker import Track

EVENT_SCHEMA = "armor.vision.event/v1"
EVENT_SCHEMA_V2 = "armor.vision.event/v2"  # same fields plus radar_tracks


@dataclass
class _Visit:
    frames: int
    entered_at: float
    fired: bool = False
    started_stationary: bool = False


class Evaluator:
    def __init__(self, config: VisionConfig, mode: str | None = None) -> None:
        self._config = config
        self._visits: dict[str, dict[tuple[int, str], _Visit]] = {}   # per camera: a frame only looks at the visits of its own camera
        self.mode = mode

    def set_mode(self, mode: str | None) -> None:
        self.mode = mode

    def watched(self, zone: Zone) -> bool:
        """With no mode, or a mode that has no profile, every zone is watched:
        an unknown mode must never silently watch less. The one exception is the
        server's `disarmed`, which has no profile unless one is written: then the
        alert zones are not watched and only the zones that record detections are."""
        if self.mode is None:
            return True
        if self.mode not in self._config.profiles:
            return zone.kind != "alert" if self.mode == "disarmed" else True
        return zone.zone_id in self._config.profiles[self.mode]

    def evaluate(self, camera: CameraConfig, timestamp: float, tracks: list[Track], alive: list[Track] | None = None) -> list[dict]:
        """`tracks` are the ones seen in this update; `alive` (all the tracker still follows, when given) decides which visits end: an object the detector missed for a frame
        has not left, and coming back must not open a new visit."""
        events: list[dict] = []
        live = {(camera.camera_id, t.track_id) for t in (alive if alive is not None else tracks)}
        visits = self._visits.setdefault(camera.camera_id, {})
        for key in [k for k in visits if (camera.camera_id, k[0]) not in live]:
            del visits[key]   # the object is gone: its visits end
        for track in tracks:
            foot = foot_point(track.box)
            for zone in camera.zones:
                key = (track.track_id, zone.zone_id)
                inside = (self.watched(zone) and (not zone.labels or track.label in zone.labels)
                          and point_in_polygon(foot, zone.points))
                if not inside:
                    visits.pop(key, None)
                    continue
                visit = visits.get(key)
                if visit is None:
                    visit = visits[key] = _Visit(0, timestamp, started_stationary=track.stationary)
                visit.frames += 1
                if visit.fired or visit.started_stationary:
                    continue
                if visit.frames >= zone.min_frames and timestamp - visit.entered_at >= zone.min_seconds:
                    visit.fired = True
                    events.append(make_event(camera.camera_id, zone, track, timestamp))
        return events


def make_event(camera_id: str, zone: Zone, track: Track, timestamp: float, radar_tracks: int | None = None) -> dict:
    """The message sent to the server. It reports what was seen; it never asks
    for anything to be done: authorizes_action is always false. Without
    radar_tracks the event is the first version; with it (a whole number, zero
    or more) it is the second, which carries the radar tracks that agree."""
    if radar_tracks is not None and (isinstance(radar_tracks, bool) or not isinstance(radar_tracks, int) or radar_tracks < 0):
        raise ValueError("radar_tracks must be a whole number, zero or more")
    event = {
        "schema": EVENT_SCHEMA if radar_tracks is None else EVENT_SCHEMA_V2,
        "type": zone.kind,
        "camera_id": camera_id,
        "zone_id": zone.zone_id,
        "zone_name": zone.name,
        "track_id": track.track_id,
        "label": track.label,
        "confidence": round(track.confidence, 3),
        "box": [round(v, 4) for v in track.box],
        "timestamp": timestamp,
        "timestamp_ms": int(round(timestamp * 1000)),
        "authorizes_action": False,
    }
    if radar_tracks is not None:
        event["radar_tracks"] = radar_tracks
    return event
