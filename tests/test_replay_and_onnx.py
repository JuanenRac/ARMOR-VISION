"""The offline replay through the zone rules and the optional ONNX detector."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.detector import DetectorUnavailable, load_detector
from armor_vision.motion import Frame
from armor_vision.onnx_detector import OnnxDetector, OnnxSettings, decode, parse_onnx_settings


def run(*args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(args))
    return code, out.getvalue(), err.getvalue()


def walk_file(folder, camera="cam-front", steps=12):
    path = Path(folder) / "walk.jsonl"
    lines = []
    for step in range(steps):
        x = 0.4 + 0.02 * step
        lines.append(json.dumps({"camera_id": camera, "timestamp": step * 0.5,
                                 "detections": [{"label": "person", "confidence": 0.9, "box": [x, 0.62, x + 0.06, 0.82]}]}))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class ReplayTests(unittest.TestCase):
    def test_a_walk_through_the_driveway_raises_one_alert(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run("replay", str(walk_file(folder)))
        self.assertEqual(code, 0, err)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual([e["zone_id"] for e in lines[:-1]], ["drive"])
        self.assertEqual(lines[-1]["events_per_zone"], {"drive": 1})
        self.assertFalse(lines[0]["authorizes_action"])

    def test_the_arming_mode_decides_what_is_watched(self):
        with tempfile.TemporaryDirectory() as folder:
            path = walk_file(folder)
            _code, home, _err = run("replay", str(path), "--mode", "home")
            _code, away, _err = run("replay", str(path), "--mode", "away")
        self.assertEqual(json.loads(home.splitlines()[-1])["events_per_zone"], {})
        self.assertEqual(json.loads(away.splitlines()[-1])["events_per_zone"], {"drive": 1})

    def test_a_recording_of_another_house_is_refused_not_quiet(self):
        with tempfile.TemporaryDirectory() as folder:
            code, out, err = run("replay", str(walk_file(folder, camera="cam-garden")))
        self.assertEqual((code, out), (2, ""))
        self.assertIn("cam-garden", err)

    def test_a_bad_file_is_refused_whole(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.jsonl"
            path.write_text('{"camera_id":"cam-front","timestamp":0,"detections":[]}\nnot json\n', encoding="utf-8")
            code, out, _err = run("replay", str(path))
            self.assertEqual((code, out), (2, ""))
            self.assertEqual(run("replay", str(Path(folder) / "missing.jsonl"))[0], 2)

    def test_the_example_configuration_is_the_default(self):
        self.assertIn("cam-front", EXAMPLE_CONFIG["cameras"])


class FakeSession:
    def __init__(self, rows):
        self.rows, self.fed = rows, []

    def get_inputs(self):
        return [type("Input", (), {"name": "images"})()]

    def run(self, _names, feed):
        self.fed.append(feed)
        return [Rows([self.rows])]


class Rows(list):
    shape = (1, 2, 6)


SETTINGS = OnnxSettings("model.onnx", ("person", "car"), input_size=100, min_confidence=0.5, merge_iou=0.5, max_detections=3)


class OnnxTests(unittest.TestCase):
    def test_the_settings_are_checked_whole(self):
        ok, errors = parse_onnx_settings({"model": "m.onnx", "labels": ["person"]})
        self.assertEqual((errors, ok.input_size, ok.min_confidence), ([], 640, 0.4))
        for bad in ({}, {"model": "m", "labels": []}, {"model": "m", "labels": ["a"], "input_size": 8},
                    {"model": "m", "labels": ["a"], "min_confidence": 2}, {"model": "m", "labels": ["a"], "extra": 1},
                    {"model": "m", "labels": ["a"], "max_detections": True}, [], None):
            settings, errors = parse_onnx_settings(bad)
            self.assertIsNone(settings)
            self.assertTrue(errors)

    def test_decode_normalises_filters_and_merges(self):
        rows = [[10, 20, 30, 80, 0.9, 0], [11, 21, 31, 81, 0.8, 0],       # the same person twice: one is kept
                [50, 50, 70, 70, 0.3, 1],                                  # under the confidence
                [50, 50, 70, 70, 0.9, 7],                                  # a class the model does not have
                [50, 50, float("nan"), 70, 0.9, 1], [1, 2, 3], "junk",     # malformed rows
                [60, 10, 90, 40, 0.7, 1]]
        found = decode(rows, SETTINGS)
        self.assertEqual([(d.label, d.confidence) for d in found], [("person", 0.9), ("car", 0.7)])
        self.assertEqual(found[0].box, (0.1, 0.2, 0.3, 0.8))

    def test_the_limit_and_the_clipping(self):
        rows = [[0, 0, 5, 5, 0.9, 0], [20, 20, 25, 25, 0.8, 0], [40, 40, 45, 45, 0.7, 0], [60, 60, 65, 65, 0.6, 0]]
        self.assertEqual(len(decode(rows, SETTINGS)), 3)
        clipped = decode([[-10, -10, 500, 50, 0.9, 0]], SETTINGS)[0].box
        self.assertEqual(clipped, (0.0, 0.0, 1.0, 0.5))

    def test_the_detector_runs_the_session_with_the_tensor_it_was_given(self):
        session = FakeSession([[10, 20, 30, 80, 0.9, 0]])
        detector = OnnxDetector(SETTINGS, session=session, to_tensor=lambda frame, size: ("tensor", frame.width, size))
        found = detector.detect(Frame(2, 2, bytes(4)), [])
        self.assertEqual(session.fed, [{"images": ("tensor", 2, 100)}])
        self.assertEqual((len(found), detector.calls), (1, 1))

    def test_without_the_package_it_says_so(self):
        with self.assertRaises(DetectorUnavailable):
            load_detector("onnx")
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            with self.assertRaises(DetectorUnavailable):
                load_detector("onnx", SETTINGS)


if __name__ == "__main__":
    unittest.main()
