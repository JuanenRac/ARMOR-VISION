"""Where the detections come from: a pluggable source.

A source is anything with `observations()` that yields `Observation`s in time
order. Two exist here, both without a camera: a synthetic scene (objects that
move about, always the same for the same seed) and a file of recorded
detections. A real camera or RTSP source is for the hardware and is not written.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Protocol

from .tracker import Detection

MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_OBJECTS = 64
MAX_STEPS = 200_000


class SourceError(ValueError):
    """The source cannot be trusted: nothing is read from it."""


@dataclass(frozen=True)
class Observation:
    camera_id: str
    timestamp: float
    detections: tuple[Detection, ...]


class DetectionSource(Protocol):
    def observations(self) -> Iterator[Observation]: ...


class SyntheticSource:
    """People that walk about a scene, stop for a while and walk on. Deterministic: the same
    seed and settings always give the same detections."""

    BOX_W, BOX_H = 0.05, 0.2

    def __init__(self, camera_id: str, seed: int = 1, objects: int = 3, duration: float = 60.0, fps: float = 5.0,
                 labels: tuple[str, ...] = ("person",)) -> None:
        if not isinstance(camera_id, str) or not camera_id:
            raise SourceError("camera_id is required")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise SourceError("seed must be a whole number")
        if isinstance(objects, bool) or not isinstance(objects, int) or not 0 <= objects <= MAX_OBJECTS:
            raise SourceError(f"objects must be a whole number from 0 to {MAX_OBJECTS}")
        for name, value in (("duration", duration), ("fps", fps)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise SourceError(f"{name} must be a number above 0")
        if duration * fps > MAX_STEPS:
            raise SourceError(f"duration x fps is over {MAX_STEPS} pictures")
        if not labels or not all(isinstance(label, str) and label for label in labels):
            raise SourceError("labels must be a list of names")
        self.camera_id, self.seed, self.objects = camera_id, seed, objects
        self.duration, self.fps, self.labels = float(duration), float(fps), tuple(labels)

    def observations(self) -> Iterator[Observation]:
        rng = random.Random(self.seed)
        w, h = self.BOX_W, self.BOX_H
        things: list[dict[str, Any]] = []
        for index in range(self.objects):
            things.append({
                "label": self.labels[index % len(self.labels)],
                "x": rng.uniform(0.05, 0.95 - w), "y": rng.uniform(0.25, 0.98),
                "vx": rng.uniform(-0.08, 0.08), "vy": rng.uniform(-0.05, 0.05),
                "moving": True, "start": rng.uniform(0.0, self.duration / 4.0),
            })
        steps = int(self.duration * self.fps) + 1
        dt = 1.0 / self.fps
        for step in range(steps):
            t = round(step * dt, 6)
            detections = []
            for thing in things:
                if t < thing["start"]:
                    continue
                if rng.random() < dt / 8.0:                 # now and then it stops or sets off again
                    thing["moving"] = not thing["moving"]
                    if thing["moving"]:
                        thing["vx"], thing["vy"] = rng.uniform(-0.08, 0.08), rng.uniform(-0.05, 0.05)
                if thing["moving"]:
                    thing["x"] += thing["vx"] * dt
                    thing["y"] += thing["vy"] * dt
                    if not 0.05 <= thing["x"] <= 0.95 - w:
                        thing["vx"] = -thing["vx"]
                        thing["x"] = min(max(thing["x"], 0.05), 0.95 - w)
                    if not 0.25 <= thing["y"] <= 0.98:
                        thing["vy"] = -thing["vy"]
                        thing["y"] = min(max(thing["y"], 0.25), 0.98)
                x, y = round(thing["x"], 6), round(thing["y"], 6)
                detections.append(Detection(thing["label"], 0.9, (x, round(y - h, 6), round(x + w, 6), y)))
            yield Observation(self.camera_id, t, tuple(detections))


class FileSource:
    """Recorded detections, one JSON object per line:
    {"camera_id": "cam", "timestamp": 1.5, "detections": [{"label": "person", "confidence": 0.9, "box": [x0, y0, x1, y1]}]}
    Any malformed line, a time that goes backwards or a file that is too big refuses the whole file."""

    def __init__(self, path: str | Path, max_bytes: int = MAX_FILE_BYTES) -> None:
        self.path, self.max_bytes = Path(path), max_bytes

    @staticmethod
    def _no_constants(name: str):
        raise SourceError(f"{name} is not allowed in the file")

    def observations(self) -> Iterator[Observation]:
        try:
            if self.path.stat().st_size > self.max_bytes:
                raise SourceError(f"the file is over {self.max_bytes} bytes")
            text = self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SourceError(f"cannot read {self.path}: {exc}") from exc
        except UnicodeDecodeError as exc:
            raise SourceError(f"{self.path} is not UTF-8 text") from exc
        parsed: list[Observation] = []
        last: dict[str, float] = {}
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line, parse_constant=self._no_constants)
            except ValueError as exc:
                raise SourceError(f"line {number}: not JSON ({exc})") from exc
            observation = self._observation(record, number)
            if observation.timestamp < last.get(observation.camera_id, -math.inf):
                raise SourceError(f"line {number}: time goes backwards for camera {observation.camera_id!r}")
            last[observation.camera_id] = observation.timestamp
            parsed.append(observation)
        yield from parsed

    @staticmethod
    def _observation(record: object, number: int) -> Observation:
        where = f"line {number}"
        if not isinstance(record, dict) or set(record) - {"camera_id", "timestamp", "detections"}:
            raise SourceError(f"{where}: must be an object with camera_id, timestamp and detections only")
        camera_id, t, raw = record.get("camera_id"), record.get("timestamp"), record.get("detections")
        if not isinstance(camera_id, str) or not camera_id:
            raise SourceError(f"{where}: camera_id is required")
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t):
            raise SourceError(f"{where}: timestamp must be a finite number")
        if not isinstance(raw, list):
            raise SourceError(f"{where}: detections must be a list")
        detections = []
        for item in raw:
            if not isinstance(item, dict) or set(item) - {"label", "confidence", "box"}:
                raise SourceError(f"{where}: a detection must be an object with label, confidence and box only")
            label, confidence, box = item.get("label"), item.get("confidence"), item.get("box")
            if not isinstance(label, str) or not label:
                raise SourceError(f"{where}: a detection needs a label")
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
                raise SourceError(f"{where}: confidence must be a number")
            if (not isinstance(box, list) or len(box) != 4
                    or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in box)):
                raise SourceError(f"{where}: box must be four numbers")
            detections.append(Detection(label, float(confidence), (float(box[0]), float(box[1]), float(box[2]), float(box[3]))))
        return Observation(camera_id, float(t), tuple(detections))
