"""A detector for the Jetson Orin NX behind the same interface as the others: a TensorRT engine.

The engine sits behind a small `Engine` interface (`infer(frame, size) -> rows`), so everything around it - the settings, the
decoding of the rows and the limits - runs and is tested on any machine with `SimulatedEngine`, a stand-in that returns the rows
it is told to. `TensorrtEngine` is the one that opens a serialized engine file with the `tensorrt` and `pycuda` packages of the
Jetson; it is written but has never run on a Jetson, so the evidence of every result of this module on a bench machine is
`simulator`. The model contract is the one of the ONNX detector: one input `[1, 3, S, S]` (float32, RGB, 0..1) and one output with
rows `x1, y1, x2, y2, score, class` in pixels of the input.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from .detector import DetectorUnavailable
from .geometry import Box
from .motion import Frame
from .onnx_detector import OnnxSettings, decode, parse_onnx_settings
from .tracker import Detection

EVIDENCE_SIMULATOR = "simulator"
SETTINGS_FIELDS = {"engine", "labels", "input_size", "min_confidence", "merge_iou", "max_detections"}


@dataclass(frozen=True)
class TensorrtSettings:
    engine: str                    # the path of the serialized engine (.engine / .plan)
    labels: tuple[str, ...]
    input_size: int = 640
    min_confidence: float = 0.4
    merge_iou: float = 0.5
    max_detections: int = 50

    def decoding(self) -> OnnxSettings:
        """The same decoding rules as the ONNX detector (confidence filter, classes, same-class merge, limit)."""
        return OnnxSettings(self.engine, self.labels, self.input_size, self.min_confidence, self.merge_iou, self.max_detections)


def parse_tensorrt_settings(raw: Any) -> tuple[TensorrtSettings | None, list[str]]:
    """Returns (settings, errors); with any error the settings are None. The fields of the ONNX ones, with `engine` instead of `model`."""
    if not isinstance(raw, dict):
        return None, ["the detector settings must be an object"]
    unknown = sorted(set(raw) - SETTINGS_FIELDS)
    if unknown:
        return None, [f"unknown field(s): {', '.join(unknown)}"]
    parsed, errors = parse_onnx_settings({("model" if key == "engine" else key): value for key, value in raw.items()})
    errors = [e.replace("model is required (the path of the .onnx file)", "engine is required (the path of the serialized TensorRT engine)") for e in errors]
    if parsed is None:
        return None, errors
    return TensorrtSettings(parsed.model, parsed.labels, parsed.input_size, parsed.min_confidence, parsed.merge_iou, parsed.max_detections), []


class Engine(Protocol):
    def infer(self, frame: Frame, size: int) -> Any:
        """The rows `[N, 6]` the model gives for this frame resized to `size` x `size`."""


class SimulatedEngine:
    """Returns the rows it is told to (a list, or a function of the frame) and counts the calls; its evidence is always `simulator`."""

    evidence = EVIDENCE_SIMULATOR

    def __init__(self, rows: Any = ()) -> None:
        self._rows = rows
        self.calls = 0
        self.sizes: list[int] = []

    def infer(self, frame: Frame, size: int) -> Any:
        self.calls += 1
        self.sizes.append(size)
        return self._rows(frame) if callable(self._rows) else self._rows


class TensorrtEngine:
    """Opens a serialized engine with TensorRT and PyCUDA. Written for the Jetson, never run on one: `evidence` stays `simulator` until it has."""

    evidence = EVIDENCE_SIMULATOR

    def __init__(self, path: str, to_tensor: Callable[[Frame, int], Any] | None = None) -> None:
        if not os.path.isfile(path):
            raise DetectorUnavailable(f"the TensorRT engine {path} does not exist")
        try:
            import pycuda.autoinit  # type: ignore[import-not-found,import-untyped,unused-ignore]  # noqa: F401
            import pycuda.driver as cuda  # type: ignore[import-not-found,import-untyped,unused-ignore]
            import tensorrt  # type: ignore[import-not-found,import-untyped,unused-ignore]
        except ImportError as exc:
            raise DetectorUnavailable("the TensorRT detector needs the tensorrt and pycuda packages of the Jetson; they are not installed") from exc
        if to_tensor is None:
            from .onnx_detector import _numpy_tensor
            to_tensor = _numpy_tensor
        self._to_tensor, self._cuda = to_tensor, cuda
        try:
            logger = tensorrt.Logger(tensorrt.Logger.WARNING)
            with open(path, "rb") as handle, tensorrt.Runtime(logger) as runtime:
                self._engine = runtime.deserialize_cuda_engine(handle.read())
            if self._engine is None:
                raise RuntimeError("the file is not an engine of this TensorRT version")
            self._context = self._engine.create_execution_context()
        except Exception as exc:
            raise DetectorUnavailable(f"cannot open the TensorRT engine {path}: {exc}") from exc

    def infer(self, frame: Frame, size: int) -> Any:    # pragma: no cover - needs a Jetson
        import numpy
        cuda = self._cuda
        tensor = numpy.ascontiguousarray(self._to_tensor(frame, size), dtype=numpy.float32)
        output = numpy.empty(tuple(self._engine.get_tensor_shape(self._engine.get_tensor_name(1))), dtype=numpy.float32)
        device_in, device_out = cuda.mem_alloc(tensor.nbytes), cuda.mem_alloc(output.nbytes)
        try:
            cuda.memcpy_htod(device_in, tensor)
            self._context.execute_v2([int(device_in), int(device_out)])
            cuda.memcpy_dtoh(output, device_out)
        finally:
            device_in.free()
            device_out.free()
        return output[0] if output.ndim == 3 else output


class TensorrtDetector:
    def __init__(self, settings: TensorrtSettings, engine: Engine | None = None) -> None:
        self.settings = settings
        self._decoding = settings.decoding()
        self._engine = engine if engine is not None else TensorrtEngine(settings.engine)
        self.calls = 0

    @property
    def evidence(self) -> str:
        return getattr(self._engine, "evidence", EVIDENCE_SIMULATOR)

    def detect(self, frame: Frame, hints: list[Box]) -> list[Detection]:
        self.calls += 1
        return decode(self._engine.infer(frame, self.settings.input_size), self._decoding)
