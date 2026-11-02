"""A detector that runs an ONNX model on the CPU, behind the same interface as the others.

It is the first detector that can be checked on a bench machine without the Jetson. It is off
unless somebody builds it: nothing here is imported by the pipeline, and `onnxruntime` and
`numpy` are only loaded when a model is really opened.

The model contract is the simplest one that exists in most exports: one input `[1, 3, S, S]`
(float32, RGB, 0..1; the grey frame is repeated on the three channels) and one output `[N, 6]`
or `[1, N, 6]` with rows `x1, y1, x2, y2, score, class` in pixels of the input, the
non-maximum suppression already inside the model. Overlapping boxes of the same class are
still merged here, because a model exported without it is a common mistake.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Callable

from .detector import DetectorUnavailable
from .geometry import Box, iou
from .motion import Frame
from .tracker import Detection

SETTINGS_FIELDS = {"model", "labels", "input_size", "min_confidence", "merge_iou", "max_detections"}
MAX_INPUT_SIZE = 2048


@dataclass(frozen=True)
class OnnxSettings:
    model: str
    labels: tuple[str, ...]
    input_size: int = 640
    min_confidence: float = 0.4
    merge_iou: float = 0.5
    max_detections: int = 50


def parse_onnx_settings(raw: Any) -> tuple[OnnxSettings | None, list[str]]:
    """Returns (settings, errors); with any error the settings are None."""
    if not isinstance(raw, dict):
        return None, ["the detector settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - SETTINGS_FIELDS))}"] if set(raw) - SETTINGS_FIELDS else []
    model, labels = raw.get("model"), raw.get("labels")
    if not isinstance(model, str) or not model:
        errors.append("model is required (the path of the .onnx file)")
    if not isinstance(labels, list) or not labels or not all(isinstance(label, str) and label for label in labels):
        errors.append("labels must be a list of names, one per class of the model")
    size = raw.get("input_size", 640)
    if isinstance(size, bool) or not isinstance(size, int) or not 32 <= size <= MAX_INPUT_SIZE:
        errors.append(f"input_size must be a whole number from 32 to {MAX_INPUT_SIZE}")
    values = {}
    for name, default in (("min_confidence", 0.4), ("merge_iou", 0.5)):
        value = raw.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
            errors.append(f"{name} must be a number from 0 to 1")
        values[name] = value
    limit = raw.get("max_detections", 50)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
        errors.append("max_detections must be a whole number from 1 to 1000")
    if errors:
        return None, errors
    return OnnxSettings(str(model), tuple(labels or ()), size, float(values["min_confidence"]), float(values["merge_iou"]), limit), []


def decode(rows: Any, settings: OnnxSettings) -> list[Detection]:
    """Turns the rows of the model output into normalised detections: the confidence filter, the
    class names, the same-class merge and the limit. A row that is not four finite coordinates,
    a score and a known class is dropped, never guessed."""
    size = float(settings.input_size)
    found: list[Detection] = []
    for row in rows:
        try:
            x1, y1, x2, y2, score, cls = (float(v) for v in row[:6])
        except (TypeError, ValueError):
            continue
        if len(row) < 6 or not all(math.isfinite(v) for v in (x1, y1, x2, y2, score, cls)):
            continue
        index = int(cls)
        if index != cls or not 0 <= index < len(settings.labels) or not settings.min_confidence <= score <= 1.0:
            continue
        box: Box = (min(max(min(x1, x2) / size, 0.0), 1.0), min(max(min(y1, y2) / size, 0.0), 1.0),
                    min(max(max(x1, x2) / size, 0.0), 1.0), min(max(max(y1, y2) / size, 0.0), 1.0))
        if box[2] - box[0] <= 0 or box[3] - box[1] <= 0:
            continue
        found.append(Detection(settings.labels[index], round(score, 4), box))
    found.sort(key=lambda d: -d.confidence)
    kept: list[Detection] = []
    for detection in found:
        if all(other.label != detection.label or iou(other.box, detection.box) < settings.merge_iou for other in kept):
            kept.append(detection)
        if len(kept) >= settings.max_detections:
            break
    return kept


def _numpy_tensor(frame: Frame, size: int) -> Any:
    """The grey frame as a `[1, 3, size, size]` float32 tensor (nearest-neighbour resize)."""
    try:
        import numpy  # type: ignore[import-not-found,import-untyped,unused-ignore]
    except ImportError as exc:
        raise DetectorUnavailable("the ONNX detector needs numpy (it comes with onnxruntime)") from exc
    grey = numpy.frombuffer(frame.pixels, dtype=numpy.uint8).reshape(frame.height, frame.width)
    rows = numpy.arange(size) * frame.height // size
    columns = numpy.arange(size) * frame.width // size
    plane = grey[rows][:, columns].astype(numpy.float32) / 255.0
    return numpy.broadcast_to(plane, (1, 3, size, size)).copy()


class OnnxDetector:
    def __init__(self, settings: OnnxSettings, session: Any = None, to_tensor: Callable[[Frame, int], Any] = _numpy_tensor) -> None:
        self.settings = settings
        self._to_tensor = to_tensor
        if session is None:
            try:
                import onnxruntime  # type: ignore[import-not-found,import-untyped,unused-ignore]
            except ImportError as exc:
                raise DetectorUnavailable("the ONNX detector needs the onnxruntime package; it is not installed") from exc
            try:
                session = onnxruntime.InferenceSession(settings.model, providers=["CPUExecutionProvider"])
            except Exception as exc:    # the library raises its own types for a missing or broken model
                raise DetectorUnavailable(f"cannot open the model {settings.model}: {exc}") from exc
        self._session = session
        self._input = session.get_inputs()[0].name
        self.calls = 0

    def detect(self, frame: Frame, hints: list[Box]) -> list[Detection]:
        self.calls += 1
        output = self._session.run(None, {self._input: self._to_tensor(frame, self.settings.input_size)})[0]
        rows = output[0] if len(getattr(output, "shape", ())) == 3 else output
        return decode(rows, self.settings)
