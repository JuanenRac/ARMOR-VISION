"""The detector is the expensive part, so it sits behind a small interface.

Version 0.0.1 ships only a scripted detector (for tests and simulation). The
real model for the Jetson Orin NX is not written yet and asking for it says so.
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


def load_detector(name: str) -> Detector:
    if name == "tensorrt":
        raise DetectorUnavailable(
            "the TensorRT detector for the Jetson Orin NX is not written yet; "
            "this version only runs the scripted detector of the tests and the simulation")
    raise DetectorUnavailable(f"unknown detector {name!r}")
