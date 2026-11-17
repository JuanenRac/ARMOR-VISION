"""The optional hash of a model file: nothing changes without it; with it a file that differs is refused before any library opens it."""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision.detector import DetectorUnavailable  # noqa: E402
from armor_vision.onnx_detector import OnnxDetector, check_model_sha256, parse_onnx_settings  # noqa: E402
from armor_vision.tensorrt_detector import TensorrtDetector, parse_tensorrt_settings  # noqa: E402

CONTENT = b"not really a model"
GOOD = hashlib.sha256(CONTENT).hexdigest()


class ModelHash(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = str(Path(folder.name) / "model.bin")
        Path(self.path).write_bytes(CONTENT)

    def test_without_a_hash_nothing_is_read_or_refused(self):
        check_model_sha256(str(Path(self.path).with_name("missing.bin")), None)

    def test_the_same_file_passes_and_another_one_does_not(self):
        check_model_sha256(self.path, GOOD)
        with self.assertRaises(DetectorUnavailable) as raised:
            check_model_sha256(self.path, "0" * 64)
        self.assertIn("SHA-256 differs", str(raised.exception))
        with self.assertRaises(DetectorUnavailable):
            check_model_sha256(self.path + ".gone", GOOD)

    def test_the_settings_take_a_hash_in_hex_only(self):
        base = {"model": self.path, "labels": ["person"]}
        parsed, errors = parse_onnx_settings({**base, "sha256": GOOD.upper()})
        self.assertEqual((errors, parsed.sha256), ([], GOOD))
        self.assertIsNone(parse_onnx_settings(base)[0].sha256)
        for bad in ("abc", "g" * 64, 5, ""):
            with self.subTest(bad=bad):
                self.assertTrue(parse_onnx_settings({**base, "sha256": bad})[1])

    def test_the_onnx_detector_checks_the_file_before_opening_it(self):
        settings, _ = parse_onnx_settings({"model": self.path, "labels": ["person"], "sha256": "1" * 64})
        with self.assertRaises(DetectorUnavailable) as raised:
            OnnxDetector(settings)
        self.assertIn("SHA-256 differs", str(raised.exception))      # refused for the hash, not for a missing runtime

    def test_the_tensorrt_detector_checks_the_engine_before_opening_it(self):
        settings, errors = parse_tensorrt_settings({"engine": self.path, "labels": ["person"], "sha256": "1" * 64})
        self.assertEqual(errors, [])
        self.assertEqual(settings.sha256, "1" * 64)
        with self.assertRaises(DetectorUnavailable) as raised:
            TensorrtDetector(settings)
        self.assertIn("SHA-256 differs", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
