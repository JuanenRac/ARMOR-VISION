"""The heat map as a route a server mounts: `heatmap-route` answers one query as a JSON line and the rest of the command line behaves as it always did."""
import base64
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from armor_vision.activity_config import ACTIVITY_EXAMPLE
from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.config import parse_config
from armor_vision.heatmap_service import ServiceError, answer, build_engine


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def detections_file(folder: str, camera: str = "cam-front", count: int = 5) -> str:
    lines = [json.dumps({"camera_id": camera, "timestamp": float(i), "detections": [{"label": "person", "confidence": 0.9, "box": [0.4, 0.6, 0.5, 0.8]}]}) for i in range(count)]
    path = Path(folder) / "detections.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path)


def write_json(folder: str, name: str, value: object) -> str:
    path = Path(folder) / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return str(path)


class AnswerTests(unittest.TestCase):
    def test_off_is_a_404_whatever_the_data(self):
        with tempfile.TemporaryDirectory() as folder:
            data = detections_file(folder)
            for raw in ({}, {"enabled": False}, {**ACTIVITY_EXAMPLE, "enabled": False}):
                self.assertIsNone(build_engine(vision(), raw, data))
                result = answer(vision(), raw, data, {})
                self.assertEqual(result["status"], 404)
                self.assertEqual(base64.b64decode(str(result["body_base64"])), b"not found\n")

    def test_on_without_data_is_an_empty_map(self):
        result = answer(vision(), ACTIVITY_EXAMPLE, None, {})
        self.assertEqual((result["status"], result["content_type"]), (200, "application/json"))
        body = json.loads(base64.b64decode(str(result["body_base64"])))
        self.assertEqual(body["camera_id"], "cam-front")
        self.assertEqual(sum(sum(row) for row in body["weights"]) if isinstance(body["weights"][0], list) else sum(body["weights"]), 0)

    def test_on_with_data_counts_the_positions_in_the_three_formats(self):
        with tempfile.TemporaryDirectory() as folder:
            data = detections_file(folder, count=5)
            result = answer(vision(), ACTIVITY_EXAMPLE, data, {"camera": "cam-front"})
            body = json.loads(base64.b64decode(str(result["body_base64"])))
            weights = body["weights"]
            total = sum(sum(row) for row in weights) if isinstance(weights[0], list) else sum(weights)
            self.assertEqual(total, 5)
            png = answer(vision(), ACTIVITY_EXAMPLE, data, {"format": "png", "scale": "4"})
            self.assertEqual((png["status"], png["content_type"]), (200, "image/png"))
            self.assertTrue(base64.b64decode(str(png["body_base64"])).startswith(b"\x89PNG"))
            svg = answer(vision(), ACTIVITY_EXAMPLE, data, {"format": "svg"})
            self.assertEqual(svg["content_type"], "image/svg+xml")

    def test_a_bad_query_is_refused_by_the_route(self):
        for query, status in (({"format": "gif"}, 400), ({"scale": "0"}, 400), ({"scale": "65"}, 400), ({"camera": "other"}, 404), ({"x": "1"}, 400), ({"camera": "a", "y": "2"}, 400)):
            self.assertEqual(answer(vision(), ACTIVITY_EXAMPLE, None, query)["status"], status, query)

    def test_a_wrong_configuration_or_file_is_an_error_not_an_empty_map(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ServiceError) as caught:
                answer(vision(), {"enabled": True, "bogus": 1}, None, {})
            self.assertEqual(caught.exception.code, 1)
            with self.assertRaises(ServiceError) as caught:
                answer(vision(), ACTIVITY_EXAMPLE, str(Path(folder) / "missing.jsonl"), {})
            self.assertEqual(caught.exception.code, 2)
            bad = Path(folder) / "bad.jsonl"
            bad.write_text("not json\n", encoding="utf-8")
            with self.assertRaises(ServiceError):
                answer(vision(), ACTIVITY_EXAMPLE, str(bad), {})


class CommandTests(unittest.TestCase):
    def test_the_command_prints_one_json_line(self):
        with tempfile.TemporaryDirectory() as folder:
            conf = write_json(folder, "activity.json", ACTIVITY_EXAMPLE)
            data = detections_file(folder)
            code, out, err = run_cli("heatmap-route", "--activity-config", conf, "--detections-file", data, "--format", "svg", "--scale", "3")
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(len(out.splitlines()), 1)
            line = json.loads(out)
            self.assertEqual((line["status"], line["content_type"]), (200, "image/svg+xml"))

    def test_the_command_answers_404_when_off_and_fails_on_a_bad_file(self):
        with tempfile.TemporaryDirectory() as folder:
            off = write_json(folder, "off.json", {"enabled": False})
            code, out, _ = run_cli("heatmap-route", "--activity-config", off)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["status"], 404)
            code, out, _ = run_cli("heatmap-route", "--activity-config", str(Path(folder) / "none.json"))
            self.assertEqual((code, out), (2, ""))
            wrong = write_json(folder, "wrong.json", {"enabled": True, "heatmap": {"cols": 0}})
            code, out, _ = run_cli("heatmap-route", "--activity-config", wrong)
            self.assertEqual((code, out), (1, ""))
            code, out, _ = run_cli("heatmap-route", "--activity-config", write_json(folder, "ok.json", ACTIVITY_EXAMPLE), "--detections-file", str(Path(folder) / "none.jsonl"))
            self.assertEqual((code, out), (2, ""))


if __name__ == "__main__":
    unittest.main()
