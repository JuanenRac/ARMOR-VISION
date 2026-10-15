"""Frame in, events out: motion decides whether the detector runs at all."""
from __future__ import annotations

from dataclasses import dataclass

from .config import VisionConfig
from .detector import Detector
from .geometry import centre, point_in_polygon, valid_box
from .motion import Frame, moved_cells, regions
from .rules import Evaluator
from .tracker import Detection, Tracker


@dataclass
class Stats:
    frames: int = 0
    detector_calls: int = 0
    skipped_by_motion: int = 0
    dropped_detections: int = 0     # inside a mask, or with a malformed box
    events: int = 0


class Pipeline:
    def __init__(self, config: VisionConfig, detector: Detector | None = None, mode: str | None = None) -> None:
        self._config = config
        self._detector = detector
        self._evaluator = Evaluator(config, mode)
        self._trackers: dict[str, Tracker] = {}
        self._previous: dict[str, Frame] = {}
        self.stats = Stats()

    def set_mode(self, mode: str | None) -> None:
        self._evaluator.set_mode(mode)

    def process_frame(self, camera_id: str, timestamp: float, frame: Frame) -> list[dict]:
        """One picture from a camera. The detector runs only when enough of the
        picture moved (outside the masks); the first frame only sets the reference."""
        camera = self._config.cameras.get(camera_id)
        if camera is None:
            raise KeyError(f"camera {camera_id!r} is not in the configuration")
        if self._detector is None:
            raise RuntimeError("process_frame needs a detector; use process_detections otherwise")
        self.stats.frames += 1
        previous = self._previous.get(camera_id)
        self._previous[camera_id] = frame
        if previous is None:
            self.stats.skipped_by_motion += 1
            return []
        cells = moved_cells(previous, frame, camera.motion_threshold, camera.masks)
        if len(cells) < camera.motion_min_cells:
            self.stats.skipped_by_motion += 1
            return []
        self.stats.detector_calls += 1
        detections = self._detector.detect(frame, regions(cells))
        return self._track(camera_id, timestamp, detections)

    def process_detections(self, camera_id: str, timestamp: float, detections: list[Detection]) -> list[dict]:
        """Detections that already exist (from another service or a simulation)."""
        if camera_id not in self._config.cameras:
            raise KeyError(f"camera {camera_id!r} is not in the configuration")
        self.stats.frames += 1
        return self._track(camera_id, timestamp, detections)

    def _track(self, camera_id: str, timestamp: float, detections: list[Detection]) -> list[dict]:
        camera = self._config.cameras[camera_id]
        kept = []
        for detection in detections:
            if not valid_box(detection.box) or any(point_in_polygon(centre(detection.box), m) for m in camera.masks):
                self.stats.dropped_detections += 1
                continue
            kept.append(detection)
        tracker = self._trackers.setdefault(camera_id, Tracker())
        tracks = tracker.update(timestamp, kept)
        events = self._evaluator.evaluate(camera, timestamp, tracks)
        self.stats.events += len(events)
        return events
