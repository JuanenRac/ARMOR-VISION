"""Frame in, events out: motion decides whether the detector runs at all."""
from __future__ import annotations

from dataclasses import dataclass

from .config import VisionConfig
from .detector import Detector
from .geometry import centre, point_in_polygon, valid_box
from .motion import Frame, moved_cells, regions
from .rules import Evaluator
from .tracker import Detection, Tracker


class VisionError(Exception):
    """What a caller can tell apart from a bug of its own: the request cannot be served."""


class UnknownCameraError(VisionError, KeyError):
    """The camera is not in the configuration (still a KeyError for callers written before)."""

    def __str__(self) -> str:
        return str(self.args[0]) if self.args else ""


class NoDetectorError(VisionError, RuntimeError):
    """process_frame was used on a pipeline built without a detector."""


@dataclass
class Stats:
    frames: int = 0
    detector_calls: int = 0
    skipped_by_motion: int = 0
    dropped_detections: int = 0     # inside a mask, malformed, or over the limits
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
            raise UnknownCameraError(f"camera {camera_id!r} is not in the configuration")
        if self._detector is None:
            raise NoDetectorError("process_frame needs a detector; use process_detections otherwise")
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
            raise UnknownCameraError(f"camera {camera_id!r} is not in the configuration")
        self.stats.frames += 1
        return self._track(camera_id, timestamp, detections)

    def _track(self, camera_id: str, timestamp: float, detections: list[Detection]) -> list[dict]:
        camera = self._config.cameras[camera_id]
        kept = []
        for detection in detections:
            confidence = detection.confidence
            if (not valid_box(detection.box) or isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0.0 <= confidence <= 1.0
                    or any(point_in_polygon(centre(detection.box), m) for m in camera.masks)):
                self.stats.dropped_detections += 1
                continue
            kept.append(detection)
        if len(kept) > self._config.max_detections:
            # a detector that returns hundreds of boxes would cost O(n*m) in the tracker: the most certain ones are kept
            trimmed = len(kept) - self._config.max_detections
            kept = sorted(kept, key=lambda d: -d.confidence)[:self._config.max_detections]
            self.stats.dropped_detections += trimmed
        tracker = self._trackers.setdefault(camera_id, Tracker(self._config.max_tracks))
        before = tracker.refused
        tracks = tracker.update(timestamp, kept)
        self.stats.dropped_detections += tracker.refused - before
        events = self._evaluator.evaluate(camera, timestamp, tracks, tracker.tracks)
        self.stats.events += len(events)
        return events
