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

SETTINGS_FIELDS = {"model", "labels", "input_size", "min_confidence", "merge_iou", "max_detections", "output_format", "input_range"}
MAX_INPUT_SIZE = 2048
OUTPUT_FORMATS = ("rows", "yolox")     # rows: [N, 6] with the non-maximum suppression inside; yolox: the raw [1, N, 5 + classes] of a YOLOX export (decoded and merged here)
INPUT_RANGES = ("unit", "byte")        # unit: pixels 0..1; byte: pixels 0..255 as YOLOX takes them
YOLOX_STRIDES = (8, 16, 32)
#: The 80 classes of the COCO data set, in the order of the YOLOX models that are trained on it. `"labels": "coco80"` stands for this list.
COCO_LABELS = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle", "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich",
    "orange", "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote",
    "keyboard", "cell phone", "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


@dataclass(frozen=True)
class OnnxSettings:
    model: str
    labels: tuple[str, ...]
    input_size: int = 640
    min_confidence: float = 0.4
    merge_iou: float = 0.5
    max_detections: int = 50
    output_format: str = "rows"
    input_range: str = "unit"


def parse_onnx_settings(raw: Any) -> tuple[OnnxSettings | None, list[str]]:
    """Returns (settings, errors); with any error the settings are None."""
    if not isinstance(raw, dict):
        return None, ["the detector settings must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - SETTINGS_FIELDS))}"] if set(raw) - SETTINGS_FIELDS else []
    model, labels = raw.get("model"), raw.get("labels")
    if labels == "coco80":
        labels = list(COCO_LABELS)
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
    output_format, input_range = raw.get("output_format", "rows"), raw.get("input_range", "unit")
    if output_format not in OUTPUT_FORMATS:
        errors.append(f"output_format must be one of {', '.join(OUTPUT_FORMATS)}")
    if input_range not in INPUT_RANGES:
        errors.append(f"input_range must be one of {', '.join(INPUT_RANGES)}")
    if output_format == "yolox" and (isinstance(size, int) and not isinstance(size, bool)) and size % max(YOLOX_STRIDES):
        errors.append(f"input_size must be a multiple of {max(YOLOX_STRIDES)} for a YOLOX model")
    if errors:
        return None, errors
    return OnnxSettings(str(model), tuple(labels or ()), size, float(values["min_confidence"]), float(values["merge_iou"]), limit, str(output_format), str(input_range)), []


def yolox_grid(size: int) -> list[tuple[int, int, int]]:
    """(x, y, stride) of every anchor of a YOLOX model with a square input of `size`, in the order of its output: the three strides in turn, each row of cells after the other."""
    anchors: list[tuple[int, int, int]] = []
    for stride in YOLOX_STRIDES:
        cells = size // stride
        anchors.extend((x, y, stride) for y in range(cells) for x in range(cells))
    return anchors


def decode_yolox(rows: Any, settings: OnnxSettings) -> list[Detection]:
    """The raw output of a YOLOX export (`x, y, w, h, objectness, one score per class` for every anchor, not yet turned into pixels): the boxes are placed on the grid, the score is the
    objectness times the best class score, and then the same filter and same-class merge as the other format. A model whose rows do not match the labels or the input size is refused."""
    anchors = yolox_grid(settings.input_size)
    if len(rows) != len(anchors):
        raise DetectorUnavailable(f"the model gives {len(rows)} anchors, a YOLOX model with input_size {settings.input_size} gives {len(anchors)}: check input_size")
    classes = len(settings.labels)
    found: list[list[float]] = []
    for (gx, gy, stride), row in zip(anchors, rows, strict=True):
        if len(row) != 5 + classes:
            raise DetectorUnavailable(f"the model gives {len(row)} values per anchor, {5 + classes} were expected (4 for the box, 1 objectness and one per label)")
        try:
            scores = [float(v) for v in row[5:]]
            best = max(range(classes), key=scores.__getitem__)
            score = float(row[4]) * scores[best]
            if not math.isfinite(score) or score < settings.min_confidence:
                continue
            cx, cy = (float(row[0]) + gx) * stride, (float(row[1]) + gy) * stride
            w, h = math.exp(min(float(row[2]), 20.0)) * stride, math.exp(min(float(row[3]), 20.0)) * stride
        except (TypeError, ValueError, OverflowError):
            continue
        found.append([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, score, float(best)])
    return decode(found, settings)


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
        tensor = self._to_tensor(frame, self.settings.input_size)
        if self.settings.input_range == "byte":
            tensor = tensor * 255.0
        output = self._session.run(None, {self._input: tensor})[0]
        rows = output[0] if len(getattr(output, "shape", ())) == 3 else output
        if self.settings.output_format == "yolox":
            return decode_yolox(rows, self.settings)
        return decode(rows, self.settings)


@dataclass(frozen=True)
class DetectorConfig:
    """The detector file: off unless it says `enabled`. The model is chosen by path and is never part of this repository."""

    enabled: bool
    settings: OnnxSettings | None


#: A detector file to start from: a YOLOX-nano export (Apache-2.0, trained on COCO), switched off, with the model outside the repository.
DETECTOR_EXAMPLE = {
    "enabled": False,
    "onnx": {"model": "/opt/armor/models/yolox_nano.onnx", "labels": "coco80", "input_size": 416, "min_confidence": 0.4, "merge_iou": 0.45, "max_detections": 50,
             "output_format": "yolox", "input_range": "byte"},
}


def parse_detector_config(raw: Any) -> tuple[DetectorConfig | None, list[str]]:
    """Returns (config, errors). `enabled` defaults to false; the settings are read (and refused when wrong) even while it is off, so that a typo is found before the switch is turned."""
    if not isinstance(raw, dict):
        return None, ["the detector file must be an object"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - {'enabled', 'onnx'}))}"] if set(raw) - {"enabled", "onnx"} else []
    enabled = raw.get("enabled", False)
    if not isinstance(enabled, bool):
        errors.append("enabled must be true or false")
    settings = None
    if "onnx" in raw or enabled is True:
        settings, problems = parse_onnx_settings(raw.get("onnx"))
        errors.extend(problems)
    if errors:
        return None, errors
    return DetectorConfig(enabled is True, settings), []


def build_detector(config: DetectorConfig) -> "OnnxDetector | None":
    """None while the detector is off (the pipeline then runs on the detections it is given); otherwise the model is opened, and DetectorUnavailable says why it could not be."""
    if not config.enabled or config.settings is None:
        return None
    return OnnxDetector(config.settings)
