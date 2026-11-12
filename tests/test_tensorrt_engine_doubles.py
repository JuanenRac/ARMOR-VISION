"""The opening of a TensorRT engine tried on a computer: the packages of the Jetson (tensorrt, pycuda) are replaced by stand-ins, so every way the opening can fail is reached without a Jetson.
Nothing here runs a model: the inference itself needs the board and stays out of reach of these tests."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from armor_vision.detector import DetectorUnavailable
from armor_vision.tensorrt_detector import TensorrtEngine


def fake_modules(good=True, deserialize_error=None):
    """The modules the engine imports. With `good` the runtime gives an engine that makes an execution context; without it, nothing (the file is not an engine of this version)."""
    class FakeEngine:
        def create_execution_context(self):
            return "context"

    class Logger:
        WARNING = 1

        def __init__(self, level):
            self.level = level

    class Runtime:
        def __init__(self, logger):
            self.logger = logger

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def deserialize_cuda_engine(self, data):
            if deserialize_error is not None:
                raise deserialize_error
            return FakeEngine() if good else None

    tensorrt = types.ModuleType("tensorrt")
    tensorrt.Logger, tensorrt.Runtime = Logger, Runtime  # type: ignore[attr-defined]
    driver = types.ModuleType("pycuda.driver")
    autoinit = types.ModuleType("pycuda.autoinit")
    pycuda = types.ModuleType("pycuda")
    pycuda.driver, pycuda.autoinit = driver, autoinit  # type: ignore[attr-defined]
    return {"tensorrt": tensorrt, "pycuda": pycuda, "pycuda.driver": driver, "pycuda.autoinit": autoinit}


class TensorrtEngineOpeningTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "model.engine")
        Path(self.path).write_bytes(b"not a real engine")

    def test_a_missing_file_is_unavailable_before_anything_is_imported(self):
        with self.assertRaises(DetectorUnavailable) as caught:
            TensorrtEngine(os.path.join(os.path.dirname(self.path), "none.engine"))
        self.assertIn("does not exist", str(caught.exception))

    def test_without_the_packages_of_the_jetson_it_says_so(self):
        with mock.patch.dict(sys.modules, {"tensorrt": None, "pycuda": None, "pycuda.driver": None, "pycuda.autoinit": None}):
            with self.assertRaises(DetectorUnavailable) as caught:
                TensorrtEngine(self.path)
        self.assertIn("tensorrt and pycuda", str(caught.exception))

    def test_a_file_that_is_not_an_engine_of_this_version_is_unavailable(self):
        modules = fake_modules(good=False)
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(DetectorUnavailable) as caught:
                TensorrtEngine(self.path, to_tensor=lambda frame, size: frame)
        self.assertIn("cannot open the TensorRT engine", str(caught.exception))

    def test_an_error_of_the_runtime_is_unavailable_and_keeps_its_message(self):
        modules = fake_modules(deserialize_error=RuntimeError("driver mismatch"))
        with mock.patch.dict(sys.modules, modules):
            with self.assertRaises(DetectorUnavailable) as caught:
                TensorrtEngine(self.path, to_tensor=lambda frame, size: frame)
        self.assertIn("driver mismatch", str(caught.exception))

    def test_a_good_engine_opens_and_is_still_only_simulator_evidence(self):
        modules = fake_modules()
        with mock.patch.dict(sys.modules, modules):
            engine = TensorrtEngine(self.path, to_tensor=lambda frame, size: frame)
        self.assertEqual(engine.evidence, "simulator")   # until it has run on a Jetson

    def test_the_default_converter_needs_numpy_only_when_it_is_asked_for(self):
        modules = fake_modules()
        with mock.patch.dict(sys.modules, modules):
            try:
                engine = TensorrtEngine(self.path)   # no converter given: the one of the ONNX detector is taken
            except DetectorUnavailable:
                self.skipTest("numpy is not installed")
        self.assertEqual(engine.evidence, "simulator")


if __name__ == "__main__":
    unittest.main()
