"""The ONNX detector as a YOLOX-nano model is read: the raw output of the export is placed on its grid, the detector file is off unless it says so, and the model is opened only on request."""
import contextlib
import io
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision import cli
from armor_vision.detector import DetectorUnavailable
from armor_vision.motion import Frame
from armor_vision.onnx_detector import (COCO_LABELS, DETECTOR_EXAMPLE, DetectorConfig, OnnxDetector, OnnxSettings, build_detector, decode_yolox, parse_detector_config,
                                        parse_onnx_settings, yolox_grid)

SETTINGS = OnnxSettings("m.onnx", ("person", "car"), 64, 0.4, 0.45, 10, "yolox", "byte")   # 64 pixels: 8*8 + 4*4 + 2*2 = 84 anchors


def empty_rows(settings: OnnxSettings = SETTINGS) -> list[list[float]]:
    return [[0.0, 0.0, 0.0, 0.0, 0.0] + [0.0] * len(settings.labels) for _ in yolox_grid(settings.input_size)]


class Grid(unittest.TestCase):
    def test_the_nano_input_has_the_anchors_of_the_export(self):
        self.assertEqual(len(yolox_grid(416)), 52 * 52 + 26 * 26 + 13 * 13)
        self.assertEqual(yolox_grid(64)[:2], [(0, 0, 8), (1, 0, 8)])
        self.assertEqual(yolox_grid(64)[64], (0, 0, 16))

    def test_the_labels_of_coco_are_eighty(self):
        self.assertEqual(len(COCO_LABELS), 80)
        self.assertEqual(COCO_LABELS[0], "person")
        self.assertEqual(len(set(COCO_LABELS)), 80)


class Decode(unittest.TestCase):
    def test_a_box_is_placed_on_its_cell_and_scaled_by_its_stride(self):
        rows = empty_rows()
        # the anchor of cell (2, 3) of the stride 8, with half a cell of offset inside it
        index = 3 * 8 + 2
        rows[index] = [0.5, 0.5, 0.0, 0.0, 0.9, 0.8, 0.1]     # exp(0) * 8 = 8 pixels wide and high
        found = decode_yolox(rows, SETTINGS)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].label, "person")
        self.assertAlmostEqual(found[0].confidence, 0.72, places=4)
        x1, y1, x2, y2 = found[0].box
        self.assertAlmostEqual(x1, (2.5 * 8 - 4) / 64)
        self.assertAlmostEqual(y1, (3.5 * 8 - 4) / 64)
        self.assertAlmostEqual(x2 - x1, 8 / 64)
        self.assertAlmostEqual(y2 - y1, 8 / 64)

    def test_the_best_class_wins_and_a_weak_score_is_dropped(self):
        rows = empty_rows()
        rows[0] = [0.0, 0.0, 0.0, 0.0, 0.9, 0.1, 0.8]
        rows[1] = [0.0, 0.0, 0.0, 0.0, 0.5, 0.5, 0.1]         # 0.25: under the 0.4 limit
        found = decode_yolox(rows, SETTINGS)
        self.assertEqual([item.label for item in found], ["car"])

    def test_two_overlapping_boxes_of_one_class_are_merged(self):
        rows = empty_rows()
        rows[9] = [0.5, 0.5, 2.0, 2.0, 0.9, 0.9, 0.0]
        rows[10] = [0.5, 0.5, 2.0, 2.0, 0.8, 0.9, 0.0]
        self.assertEqual(len(decode_yolox(rows, SETTINGS)), 1)

    def test_a_model_with_other_anchors_or_classes_is_refused_not_guessed(self):
        with self.assertRaises(DetectorUnavailable) as caught:
            decode_yolox(empty_rows()[:-1], SETTINGS)
        self.assertIn("input_size", str(caught.exception))
        wrong = [row + [0.0] for row in empty_rows()]
        with self.assertRaises(DetectorUnavailable) as caught:
            decode_yolox(wrong, SETTINGS)
        self.assertIn("values per anchor", str(caught.exception))

    def test_a_row_with_a_value_that_is_not_a_number_is_dropped(self):
        rows = empty_rows()
        rows[0] = [0.0, 0.0, "x", 0.0, 0.9, 0.9, 0.0]
        rows[1] = [0.0, 0.0, 1e9, 0.0, 0.9, 0.9, 0.0]       # an enormous width is held, not an overflow
        self.assertEqual(len(decode_yolox(rows, SETTINGS)), 1)


class Settings(unittest.TestCase):
    def test_the_format_and_range_are_checked_and_the_size_must_fit_the_strides(self):
        base = {"model": "m.onnx", "labels": "coco80"}
        ok, errors = parse_onnx_settings({**base, "input_size": 416, "output_format": "yolox", "input_range": "byte"})
        self.assertEqual(errors, [])
        self.assertEqual((ok.output_format, ok.input_range, len(ok.labels)), ("yolox", "byte", 80))
        _, errors = parse_onnx_settings({**base, "output_format": "other", "input_range": "wide"})
        self.assertEqual(len(errors), 2)
        _, errors = parse_onnx_settings({**base, "input_size": 100, "output_format": "yolox"})
        self.assertIn("multiple of 32", " ".join(errors))

    def test_the_old_settings_keep_their_meaning(self):
        ok, errors = parse_onnx_settings({"model": "m.onnx", "labels": ["person"]})
        self.assertEqual(errors, [])
        self.assertEqual((ok.output_format, ok.input_range), ("rows", "unit"))


class Tensor(list):
    def __mul__(self, factor):
        return Tensor(value * factor for value in self)


class Shaped(list):
    def __init__(self, rows):
        super().__init__([rows])
        self.shape = (1, len(rows), len(rows[0]))


class Session:
    def __init__(self, output):
        self.output, self.fed = output, None

    def get_inputs(self):
        return [types.SimpleNamespace(name="images")]

    def run(self, names, feeds):
        self.fed = feeds["images"]
        return [self.output]


class Running(unittest.TestCase):
    def test_a_yolox_model_runs_with_byte_pixels_and_gives_detections(self):
        rows = empty_rows()
        rows[0] = [0.5, 0.5, 0.0, 0.0, 0.9, 0.9, 0.0]
        session = Session(Shaped(rows))
        detector = OnnxDetector(SETTINGS, session=session, to_tensor=lambda frame, size: Tensor([0.5, 1.0]))
        found = detector.detect(Frame(2, 2, bytes(4)), [])
        self.assertEqual(session.fed, [127.5, 255.0])
        self.assertEqual([item.label for item in found], ["person"])


class DetectorFile(unittest.TestCase):
    def test_the_example_is_off_and_keeps_the_model_outside_the_repository(self):
        self.assertIs(DETECTOR_EXAMPLE["enabled"], False)
        self.assertTrue(DETECTOR_EXAMPLE["onnx"]["model"].startswith("/opt/"))
        config, errors = parse_detector_config(DETECTOR_EXAMPLE)
        self.assertEqual(errors, [])
        self.assertIsNone(build_detector(config))

    def test_an_empty_file_is_off_and_a_typo_is_found_while_it_is_off(self):
        config, errors = parse_detector_config({})
        self.assertEqual((errors, config.enabled), ([], False))
        _, errors = parse_detector_config({"enabled": False, "onnx": {"model": "m.onnx"}})
        self.assertTrue(errors)
        _, errors = parse_detector_config({"enabled": "yes"})
        self.assertIn("true or false", " ".join(errors))
        _, errors = parse_detector_config({"enabled": True})
        self.assertTrue(errors)
        _, errors = parse_detector_config({"extra": 1})
        self.assertIn("unknown field", " ".join(errors))

    def test_the_model_is_opened_only_when_it_is_on(self):
        settings, _ = parse_onnx_settings(DETECTOR_EXAMPLE["onnx"])
        with mock.patch.dict(sys.modules, {"onnxruntime": None}):
            self.assertIsNone(build_detector(DetectorConfig(False, settings)))
            with self.assertRaises(DetectorUnavailable):
                build_detector(DetectorConfig(True, settings))


class Command(unittest.TestCase):
    def run_cli(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_example_is_printed_and_checked(self):
        code, out, _ = self.run_cli("detector-example")
        self.assertEqual(code, 0)
        with tempfile.TemporaryDirectory() as holder:
            file = Path(holder) / "detector.json"
            file.write_text(out, encoding="utf-8")
            self.assertEqual(self.run_cli("check-detector-config", str(file))[:2], (0, "ok: detector off\n"))
            self.assertEqual(self.run_cli("check-detector-config", str(file), "--open")[0], 0)   # off: nothing is opened

    def test_a_bad_unreadable_or_unopenable_file_has_its_own_exit_status(self):
        with tempfile.TemporaryDirectory() as holder:
            bad = Path(holder) / "bad.json"
            bad.write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")
            self.assertEqual(self.run_cli("check-detector-config", str(bad))[0], 1)
            self.assertEqual(self.run_cli("check-detector-config", str(Path(holder) / "missing.json"))[0], 2)
            on = Path(holder) / "on.json"
            on.write_text(json.dumps({**DETECTOR_EXAMPLE, "enabled": True}), encoding="utf-8")
            self.assertEqual(self.run_cli("check-detector-config", str(on))[:2], (0, "ok: detector on\n"))
            with mock.patch.dict(sys.modules, {"onnxruntime": None}):
                code, _, err = self.run_cli("check-detector-config", str(on), "--open")
            self.assertEqual(code, 3)
            self.assertIn("onnxruntime", err)


if __name__ == "__main__":
    unittest.main()
