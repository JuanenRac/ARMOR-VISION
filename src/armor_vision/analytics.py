"""Three things the rules of a zone cannot say: how fast something moves, what was left behind and where a camera on a mount should look.

* Speed in a zone: four points of the picture whose place on the ground is known (metres) give a homography; the feet of a track are
  taken to the ground plane and the speed is the distance over the last seconds. Only tracks inside the zone are measured.
* Abandoned objects: a bag-like thing that stands still while no person is near it for long enough.
* Follow with a PTZ camera: the move (pan, tilt, zoom as speeds from -1 to 1) that would bring the followed track to the middle of the
  picture. It only COMPUTES the command; the module never sends one to a camera (a controller object receives it, and `SimulatedPtz`
  is the one that exists), because the control of a camera is not decided here.

Everything reports what was seen and never asks for an action: `authorizes_action` is always false.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from .geometry import Point, centre, foot_point, point_in_polygon, valid_polygon
from .tracker import Track

SPEED_SCHEMA = "armor.vision.speed/v1"
ABANDONED_SCHEMA = "armor.vision.abandoned/v1"


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


# ---------------------------------------------------------------- vectors of an event

def track_vectors(tracks: Sequence[Track], limit: int = 16) -> list[dict]:
    """Where each followed object is heading, as the vision event carries it: the unit direction in the picture (y grows downwards) from the oldest to the newest position
    of its history, and the speed in pictures per second. An object that has not moved, or has no history long enough, is left out; the fastest come first."""
    found = []
    for track in tracks:
        if len(track.history) < 2:
            continue
        (t0, (x0, y0)), (t1, (x1, y1)) = track.history[0], track.history[-1]
        distance, elapsed = math.hypot(x1 - x0, y1 - y0), t1 - t0
        if elapsed <= 0 or distance < 1e-6:
            continue
        found.append({"track_id": track.track_id, "dx": round((x1 - x0) / distance, 3), "dy": round((y1 - y0) / distance, 3), "speed": round(min(distance / elapsed, 100.0), 4)})
    found.sort(key=lambda v: (-v["speed"], v["track_id"]))
    return found[:max(0, limit)]


# ---------------------------------------------------------------- speed

def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """Gaussian elimination with partial pivoting; None when the system has no single solution."""
    n = len(vector)
    rows = [matrix[i][:] + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        if abs(rows[pivot][col]) < 1e-12:
            return None
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(n):
            if r != col:
                factor = rows[r][col] / rows[col][col]
                rows[r] = [a - factor * b for a, b in zip(rows[r], rows[col])]
    return [rows[i][n] / rows[i][i] for i in range(n)]


@dataclass(frozen=True)
class Calibration:
    """image point -> ground point, from four reference points of the picture (normalised) and where they are on the ground (metres)."""
    h: tuple[float, ...]

    @classmethod
    def from_points(cls, image: Sequence[Point], ground: Sequence[Point]) -> tuple["Calibration | None", list[str]]:
        if not isinstance(image, (list, tuple)) or not isinstance(ground, (list, tuple)) or len(image) != 4 or len(ground) != 4:
            return None, ["four reference points are needed, in the picture and on the ground"]
        for name, points in (("image", image), ("ground", ground)):
            if not all(isinstance(p, (list, tuple)) and len(p) == 2 and all(_number(v) for v in p) for p in points):
                return None, [f"the {name} points must be [x, y] pairs of finite numbers"]
        if any(not 0.0 <= v <= 1.0 for p in image for v in p):
            return None, ["the points of the picture are normalised (0 to 1)"]
        if len({(float(p[0]), float(p[1])) for p in image}) < 4 or len({(float(p[0]), float(p[1])) for p in ground}) < 4:
            return None, ["the reference points must all be different"]
        matrix, vector = [], []
        for (x, y), (u, v) in zip(image, ground):
            matrix.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
            vector.append(u)
            matrix.append([0, 0, 0, x, y, 1, -v * x, -v * y])
            vector.append(v)
        solution = _solve(matrix, vector)
        if solution is None:
            return None, ["the reference points are in a line or repeat a direction: they cannot define the ground plane"]
        calibration = cls(tuple(solution))
        # a calibration whose own points do not come back to the ground is a numeric accident: refuse it
        for point, expected in zip(image, ground):
            got = calibration.to_ground((float(point[0]), float(point[1])))
            if got is None or math.dist(got, (float(expected[0]), float(expected[1]))) > 1e-6 * (1.0 + math.hypot(*map(float, expected))):
                return None, ["the reference points do not give a usable ground plane"]
        return calibration, []

    def to_ground(self, point: Point) -> Point | None:
        a, b, c, d, e, f, g, h = self.h
        x, y = point
        w = g * x + h * y + 1.0
        if abs(w) < 1e-12:
            return None
        return ((a * x + b * y + c) / w, (d * x + e * y + f) / w)


@dataclass(frozen=True)
class SpeedSettings:
    zone: tuple[Point, ...]
    calibration: Calibration
    window_seconds: float = 2.0
    min_seconds: float = 0.5
    limit_kmh: float | None = None       # an event only when faster than this; None = every reading of a track inside the zone is reported once per `report_every`
    report_every: float = 5.0
    max_kmh: float = 250.0               # faster than this is a jump of the tracker, not a speed


def parse_speed_settings(raw: Any) -> tuple[SpeedSettings | None, list[str]]:
    fields = {"zone", "reference", "window_seconds", "min_seconds", "limit_kmh", "report_every", "max_kmh"}
    if not isinstance(raw, dict):
        return None, ["the speed settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - fields))}"] if set(raw) - fields else []
    zone = raw.get("zone")
    problem = valid_polygon(zone) if zone is not None else "zone is required (the polygon where speed is measured)"
    if problem:
        errors.append(f"zone: {problem}")
    reference = raw.get("reference")
    calibration = None
    if not isinstance(reference, dict) or set(reference) != {"image", "ground"}:
        errors.append("reference must be an object with image and ground (four points each)")
    else:
        calibration, more = Calibration.from_points(reference["image"], reference["ground"])
        errors += [f"reference: {m}" for m in more]
    values = {}
    for name, default, low, high in (("window_seconds", 2.0, 0.2, 60.0), ("min_seconds", 0.5, 0.1, 60.0), ("report_every", 5.0, 0.1, 3600.0), ("max_kmh", 250.0, 1.0, 1000.0)):
        value = raw.get(name, default)
        if not _number(value) or not low <= value <= high:
            errors.append(f"{name} must be a number from {low:g} to {high:g}")
        values[name] = value
    limit = raw.get("limit_kmh")
    if limit is not None and (not _number(limit) or not 0 < limit <= 1000):
        errors.append("limit_kmh must be a number above 0 (or left out)")
    if errors or calibration is None:
        return None, errors
    return SpeedSettings(tuple((float(x), float(y)) for x, y in zone), calibration, float(values["window_seconds"]), float(values["min_seconds"]),
                         None if limit is None else float(limit), float(values["report_every"]), float(values["max_kmh"])), []


@dataclass(frozen=True)
class SpeedReading:
    track_id: int
    label: str
    metres_per_second: float
    kmh: float
    timestamp: float


class SpeedEstimator:
    def __init__(self, settings: SpeedSettings) -> None:
        self.settings = settings
        self._samples: dict[int, list[tuple[float, Point]]] = {}
        self._reported: dict[int, float] = {}

    def update(self, timestamp: float, tracks: Sequence[Track]) -> list[SpeedReading]:
        """Feeds the tracks seen in this update; returns the readings of the ones inside the zone that have been followed long enough."""
        s = self.settings
        readings = []
        seen = set()
        for track in tracks:
            seen.add(track.track_id)
            foot = foot_point(track.box)
            ground = s.calibration.to_ground(foot) if point_in_polygon(foot, s.zone) else None
            samples = self._samples.setdefault(track.track_id, [])
            if ground is None or not all(math.isfinite(v) for v in ground):
                samples.clear()                      # it left the zone: the measure starts again when it comes back
                continue
            samples.append((timestamp, ground))
            while len(samples) > 2 and timestamp - samples[1][0] >= s.window_seconds:
                samples.pop(0)
            first_time, first = samples[0]
            elapsed = timestamp - first_time
            if elapsed < s.min_seconds:
                continue
            mps = math.dist(first, ground) / elapsed
            kmh = mps * 3.6
            if kmh > s.max_kmh:
                samples[:] = samples[-1:]            # a jump of the tracker, not a speed
                continue
            if s.limit_kmh is not None and kmh <= s.limit_kmh:
                continue
            if timestamp - self._reported.get(track.track_id, -math.inf) < s.report_every:
                continue
            self._reported[track.track_id] = timestamp
            readings.append(SpeedReading(track.track_id, track.label, round(mps, 3), round(kmh, 2), timestamp))
        if len(self._samples) > 1000:                # bounded: the tracks that stopped arriving are forgotten
            for gone in [t for t in self._samples if t not in seen]:
                del self._samples[gone]
                self._reported.pop(gone, None)
        return readings


def speed_event(camera_id: str, reading: SpeedReading, limit_kmh: float | None = None) -> dict:
    return {
        "schema": SPEED_SCHEMA, "type": "speed", "camera_id": camera_id, "track_id": reading.track_id, "label": reading.label,
        "metres_per_second": reading.metres_per_second, "kmh": reading.kmh, "over_limit": limit_kmh is not None and reading.kmh > limit_kmh,
        "timestamp": reading.timestamp, "timestamp_ms": int(round(reading.timestamp * 1000)), "authorizes_action": False,
    }


# ---------------------------------------------------------------- abandoned objects

@dataclass(frozen=True)
class AbandonedSettings:
    labels: tuple[str, ...] = ("backpack", "handbag", "suitcase", "bag", "box")
    owner_labels: tuple[str, ...] = ("person",)
    min_seconds: float = 60.0           # standing still with nobody near for this long
    owner_distance: float = 0.2         # normalised distance within which a person counts as the owner (grows with the size of the object)


def parse_abandoned_settings(raw: Any) -> tuple[AbandonedSettings | None, list[str]]:
    fields = {"labels", "owner_labels", "min_seconds", "owner_distance"}
    if not isinstance(raw, dict):
        return None, ["the settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - fields))}"] if set(raw) - fields else []
    defaults = AbandonedSettings()
    lists = {}
    for name, default in (("labels", defaults.labels), ("owner_labels", defaults.owner_labels)):
        value = raw.get(name, list(default))
        if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
            errors.append(f"{name} must be a list of names")
        lists[name] = value
    values = {}
    for name, default, low, high in (("min_seconds", defaults.min_seconds, 1.0, 86400.0), ("owner_distance", defaults.owner_distance, 0.01, 1.5)):
        value = raw.get(name, default)
        if not _number(value) or not low <= value <= high:
            errors.append(f"{name} must be a number from {low:g} to {high:g}")
        values[name] = value
    if errors:
        return None, errors
    return AbandonedSettings(tuple(lists["labels"]), tuple(lists["owner_labels"]), float(values["min_seconds"]), float(values["owner_distance"])), []


class AbandonedObjectDetector:
    def __init__(self, settings: AbandonedSettings | None = None) -> None:
        self.settings = settings or AbandonedSettings()
        self._alone_since: dict[int, float] = {}
        self._fired: set[int] = set()

    def update(self, camera_id: str, timestamp: float, alive: Sequence[Track]) -> list[dict]:
        """`alive` is every track the tracker still follows (a parked thing is remembered while it is not detected). One event per object."""
        s = self.settings
        owners = [t for t in alive if t.label in s.owner_labels]
        present = {t.track_id for t in alive}
        for gone in [k for k in self._alone_since if k not in present]:
            del self._alone_since[gone]
        self._fired &= present
        events = []
        for track in alive:
            if track.label not in s.labels:
                continue
            if not track.stationary or track.track_id in self._fired:
                self._alone_since.pop(track.track_id, None)
                continue
            (cx, cy) = centre(track.box)
            reach = s.owner_distance + max(track.box[2] - track.box[0], track.box[3] - track.box[1])
            if any(math.dist((cx, cy), centre(o.box)) <= reach for o in owners):
                self._alone_since.pop(track.track_id, None)
                continue
            since = self._alone_since.setdefault(track.track_id, timestamp)
            if timestamp - since >= s.min_seconds:
                self._fired.add(track.track_id)
                events.append({
                    "schema": ABANDONED_SCHEMA, "type": "abandoned", "camera_id": camera_id, "track_id": track.track_id, "label": track.label,
                    "box": [round(v, 4) for v in track.box], "alone_seconds": round(timestamp - since, 1), "timestamp": timestamp,
                    "timestamp_ms": int(round(timestamp * 1000)), "authorizes_action": False,
                })
        return events


# ---------------------------------------------------------------- follow with a PTZ camera

@dataclass(frozen=True)
class PtzCommand:
    pan: float            # -1 (left) .. 1 (right), a speed
    tilt: float           # -1 (down) .. 1 (up)
    zoom: float           # -1 (out) .. 1 (in)
    track_id: int | None  # None: the command is "stop"

    @property
    def stop(self) -> bool:
        return self.pan == 0.0 and self.tilt == 0.0 and self.zoom == 0.0


class PtzController(Protocol):
    def apply(self, camera_id: str, command: PtzCommand) -> None: ...


class SimulatedPtz:
    """Keeps the commands it receives and where they would have pointed the camera; moves nothing."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, PtzCommand]] = []

    def apply(self, camera_id: str, command: PtzCommand) -> None:
        self.commands.append((camera_id, command))


@dataclass
class PtzFollower:
    labels: tuple[str, ...] = ("person", "vehicle")
    deadband: float = 0.08            # no move while the target is this close to the middle
    gain: float = 1.6                 # speed per unit of offset
    max_speed: float = 0.7
    target_fill: float = 0.35         # share of the picture height the target should fill (zoom)
    lost_seconds: float = 3.0         # after this long without the target the camera is told to stop
    _target: int | None = field(default=None, init=False)
    _seen_at: float = field(default=0.0, init=False)

    def follow(self, timestamp: float, tracks: Sequence[Track]) -> PtzCommand | None:
        """None while nothing has to change (target centred, or nothing to follow and the camera already stopped)."""
        pool = [t for t in tracks if t.label in self.labels]
        chosen = next((t for t in pool if t.track_id == self._target), None)
        if chosen is None and pool:
            chosen = max(pool, key=lambda t: ((t.box[2] - t.box[0]) * (t.box[3] - t.box[1]), t.confidence, -t.track_id))
            self._target = chosen.track_id
        if chosen is None:
            if self._target is not None and timestamp - self._seen_at >= self.lost_seconds:
                self._target = None
                return PtzCommand(0.0, 0.0, 0.0, None)
            return None
        self._seen_at = timestamp
        cx, cy = centre(chosen.box)
        dx, dy = cx - 0.5, 0.5 - cy
        height = chosen.box[3] - chosen.box[1]

        def speed(offset: float) -> float:
            return 0.0 if abs(offset) <= self.deadband else max(-self.max_speed, min(self.max_speed, round(offset * self.gain, 3)))
        zoom = 0.0
        if height < self.target_fill * 0.6:
            zoom = 0.3
        elif height > min(0.95, self.target_fill * 1.8):
            zoom = -0.3
        return PtzCommand(speed(dx), speed(dy), zoom, chosen.track_id)
