"""The detector is the expensive part, so it sits behind a small interface.

A scripted detector serves tests and simulation, `onnx` runs a model on the CPU and `tensorrt`
is the engine of the Jetson Orin NX (it needs the Jetson packages; with a simulated engine it
runs on any machine and says so).
"""
from __future__ import annotations

from typing import Callable, Protocol

from .geometry import Box
from .motion import Frame
from .tracker import Detection


class DetectorUnavailable(RuntimeError):
    pass


class Detector(Protocol):
    def detect(self, frame: Frame, hints: list[Box]) -> list[Detection]:
        """Objects in the frame. `hints` are the regions where motion was seen."""


class ScriptedDetector:
    """Returns what a function says for each call and counts the calls."""

    def __init__(self, script: Callable[[Frame, list[Box]], list[Detection]]) -> None:
        self._script = script
        self.calls = 0

    def detect(self, frame: Frame, hints: list[Box]) -> list[Detection]:
        self.calls += 1
        return self._script(frame, hints)


def load_detector(name: str, settings: object = None) -> Detector:
    """`onnx` needs the settings of `onnx_detector.parse_onnx_settings`, `tensorrt` those of `tensorrt_detector.parse_tensorrt_settings`."""
    if name == "onnx":
        from .onnx_detector import OnnxDetector, OnnxSettings
        if not isinstance(settings, OnnxSettings):
            raise DetectorUnavailable("the ONNX detector needs its settings (model, labels): see onnx_detector.parse_onnx_settings")
        return OnnxDetector(settings)
    if name == "tensorrt":
        from .tensorrt_detector import TensorrtDetector, TensorrtSettings
        if not isinstance(settings, TensorrtSettings):
            raise DetectorUnavailable("the TensorRT detector needs its settings (engine, labels): see tensorrt_detector.parse_tensorrt_settings")
        return TensorrtDetector(settings)
    raise DetectorUnavailable(f"unknown detector {name!r}")
