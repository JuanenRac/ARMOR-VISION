"""The edges of the optional ONNX detector: a model that cannot be opened, a runtime that is not installed, the tensor made from a grey frame and the two shapes of the model output."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision.detector import DetectorUnavailable
from armor_vision.motion import Frame
from armor_vision.onnx_detector import OnnxDetector, OnnxSettings, _numpy_tensor

SETTINGS = OnnxSettings("model.onnx", ("person", "car"), 100, 0.5, 0.5, 3)


class Shaped(list):
    """An output that has a shape, as a numpy array has."""

    def __init__(self, rows, three_d):
        super().__init__([rows] if three_d else rows)
        self.shape = (1, len(rows), 6) if three_d else (len(rows), 6)


class Session:
    def __init__(self, output):
        self.output = output

    def get_inputs(self):
        return [types.SimpleNamespace(name="images")]

    def run(self, names, feeds):
        return [self.output]


class Runtime(unittest.TestCase):
    def test_a_runtime_that_is_not_installed_is_said_not_hidden(self):
        with mock.patch.dict(sys.modules, {"onnxruntime": None}):
            with self.assertRaises(DetectorUnavailable) as caught:
                OnnxDetector(SETTINGS)
        self.assertIn("onnxruntime", str(caught.exception))

    def test_a_model_that_cannot_be_opened_is_said_with_its_file_name(self):
        def refuse(path, providers):
            raise RuntimeError("broken file")
        fake = types.SimpleNamespace(InferenceSession=refuse)
        with mock.patch.dict(sys.modules, {"onnxruntime": fake}):
            with self.assertRaises(DetectorUnavailable) as caught:
                OnnxDetector(SETTINGS)
        self.assertIn("model.onnx", str(caught.exception))
        self.assertIn("broken file", str(caught.exception))

    def test_the_session_is_opened_on_the_processor_only(self):
        seen = {}

        def open_session(path, providers):
            seen["providers"] = providers
            return Session([])
        with mock.patch.dict(sys.modules, {"onnxruntime": types.SimpleNamespace(InferenceSession=open_session)}):
            OnnxDetector(SETTINGS)
        self.assertEqual(seen["providers"], ["CPUExecutionProvider"])


class Output(unittest.TestCase):
    def detect(self, output):
        return OnnxDetector(SETTINGS, session=Session(output), to_tensor=lambda frame, size: None).detect(Frame(2, 2, bytes(4)), [])

    def test_a_flat_list_of_rows_and_a_batch_of_one_give_the_same_detections(self):
        rows = [[10, 20, 30, 80, 0.9, 0]]
        flat, batch = self.detect(Shaped(rows, three_d=False)), self.detect(Shaped(rows, three_d=True))
        self.assertEqual(len(flat), 1)
        self.assertEqual(flat, batch)

    def test_an_empty_output_is_no_detection(self):
        self.assertEqual(self.detect(Shaped([], three_d=False)), [])


class Tensor(unittest.TestCase):
    def test_a_grey_frame_becomes_three_equal_planes_scaled_to_zero_one(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("numpy is not installed")
        frame = Frame(4, 2, bytes([0, 255, 0, 255, 255, 0, 255, 0]))
        tensor = _numpy_tensor(frame, 4)
        self.assertEqual(tensor.shape, (1, 3, 4, 4))
        self.assertEqual(tensor.dtype, numpy.float32)
        self.assertTrue((tensor[0, 0] == tensor[0, 1]).all() and (tensor[0, 1] == tensor[0, 2]).all())
        self.assertEqual((float(tensor.min()), float(tensor.max())), (0.0, 1.0))
        self.assertEqual(tensor[0, 0, 0].tolist(), [0.0, 1.0, 0.0, 1.0])

    def test_without_numpy_it_says_so(self):
        with mock.patch.dict(sys.modules, {"numpy": None}):
            with self.assertRaises(DetectorUnavailable):
                _numpy_tensor(Frame(2, 2, bytes(4)), 2)


if __name__ == "__main__":
    unittest.main()
