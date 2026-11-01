"""The live service: the activity engine in memory, detections in by POST /ingest, the heat map out by GET /heatmap. The command that replays a file keeps answering as before
(tests/test_heatmap_service.py); here the service must give the same map for the same detections, stay inside its limits and refuse what it does not understand."""
import base64
import copy
import http.client
import json
import random
import tempfile
import threading
import unittest
from pathlib import Path

from armor_vision.activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.config import parse_config
from armor_vision.heatmap_service import answer
from armor_vision.service import SERVICE_EXAMPLE, LiveService, ServiceSettings, make_server, parse_service_settings


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity(enabled=True, **heatmap):
    raw = copy.deepcopy(ACTIVITY_EXAMPLE)
    raw["enabled"] = enabled
    raw.setdefault("heatmap", {}).update(heatmap)
    parsed, problems = parse_activity_config(raw)
    assert parsed is not None, problems
    return parsed, raw


def record(t, camera="cam-front", box=(0.4, 0.6, 0.5, 0.8), count=1):
    return {"camera_id": camera, "timestamp": float(t), "detections": [{"label": "person", "confidence": 0.9, "box": list(box)} for _ in range(count)]}


class Running:
    """The service on a free port of this machine, in a thread."""

    def __init__(self, settings=None, enabled=True):
        parsed, _ = activity(enabled)
        self.service = LiveService(vision(), parsed, settings or ServiceSettings(port=0))
        self.server = make_server(self.service)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()

    def call(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            data = body if isinstance(body, (bytes, type(None))) else json.dumps(body).encode()
            connection.request(method, path, body=data, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader("Content-Type"), response.read()
        finally:
            connection.close()


class SettingsTests(unittest.TestCase):
    def test_the_defaults_are_local_and_the_example_is_valid(self):
        settings, problems = parse_service_settings(None)
        self.assertEqual(problems, [])
        self.assertEqual((settings.host, settings.allow_remote, settings.max_body_bytes, settings.max_detections), ("127.0.0.1", False, 65536, 64))
        example, problems = parse_service_settings(copy.deepcopy(SERVICE_EXAMPLE))
        self.assertEqual(problems, [])
        self.assertIsNotNone(example)

    def test_a_wrong_file_means_no_settings_at_all(self):
        for raw in ([], {"host": ""}, {"port": 0}, {"port": 70000}, {"port": True}, {"allow_remote": "yes"}, {"host": "0.0.0.0"}, {"host": "192.168.0.5"}, {"max_body_bytes": 10},
                    {"max_body_bytes": 2 * 1024 * 1024}, {"max_detections": 0}, {"max_detections": 1000}, {"max_query_bytes": 1}, {"nope": 1}, {"simulate": {"seed": 1}},
                    {"simulate": {"camera_id": "c", "objects": 1000}}, {"simulate": {"camera_id": "c", "extra": 1}}):
            settings, problems = parse_service_settings(raw)
            self.assertIsNone(settings, raw)
            self.assertTrue(problems, raw)

    def test_a_remote_address_needs_the_switch(self):
        self.assertIsNone(parse_service_settings({"host": "0.0.0.0"})[0])
        self.assertIsNotNone(parse_service_settings({"host": "0.0.0.0", "allow_remote": True})[0])
        for host in ("127.0.0.1", "localhost", "::1"):
            self.assertIsNotNone(parse_service_settings({"host": host})[0], host)


class ServiceTests(unittest.TestCase):
    def test_the_map_of_the_service_is_the_map_of_the_same_detections_replayed_from_a_file(self):
        _, raw = activity()
        rows = [record(i, box=(0.1 + 0.05 * (i % 8), 0.5, 0.2 + 0.05 * (i % 8), 0.8)) for i in range(40)]
        with tempfile.TemporaryDirectory() as folder, Running() as running:
            path = Path(folder) / "d.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            for row in rows:
                self.assertEqual(running.call("POST", "/ingest", row, {"Content-Type": "application/json"})[0], 200)
            for fmt in ("json", "svg", "png"):
                expected = answer(vision(), raw, str(path), {"format": fmt})
                status, kind, body = running.call("GET", f"/heatmap?format={fmt}")
                self.assertEqual((status, kind), (expected["status"], expected["content_type"]), fmt)
                self.assertEqual(body, base64.b64decode(str(expected["body_base64"])), fmt)

    def test_off_is_a_404_for_the_map_and_a_503_for_an_observation(self):
        with Running(enabled=False) as running:
            self.assertEqual(running.call("GET", "/heatmap")[0], 404)
            self.assertEqual(running.call("POST", "/ingest", record(1))[0], 503)
            self.assertFalse(json.loads(running.call("GET", "/health")[2])["activity"])

    def test_what_is_not_understood_is_refused_and_changes_nothing(self):
        with Running() as running:
            cases = [
                (b"not json", 400), (b'{"camera_id":"cam-front","timestamp":NaN,"detections":[]}', 400), (json.dumps({"camera_id": "cam-front"}).encode(), 400),
                (json.dumps({**record(1), "extra": 1}).encode(), 400), (json.dumps(record(1, camera="ghost")).encode(), 404),
                (json.dumps({"camera_id": "cam-front", "timestamp": 1, "detections": [{"label": "person", "confidence": 0.9, "box": [0, 0, 1], "x": 1}]}).encode(), 400),
                (json.dumps(record(1, count=65)).encode(), 400), (b"x" * 70000, 413),
            ]
            for body, status in cases:
                self.assertEqual(running.call("POST", "/ingest", body)[0], status, body[:40])
            self.assertEqual(running.call("POST", "/ingest", record(5))[0], 200)
            self.assertEqual(running.call("POST", "/ingest", record(4))[0], 409, "time goes backwards for the camera")
            self.assertEqual(json.loads(running.call("GET", "/health")[2])["accepted"], 1)
            weights = json.loads(running.call("GET", "/heatmap")[2])
            self.assertEqual(weights["total"], 1)
            for method, path in (("PUT", "/ingest"), ("DELETE", "/heatmap"), ("GET", "/ingest"), ("POST", "/heatmap"), ("GET", "/nothing")):
                self.assertIn(running.call(method, path)[0], (404, 405), (method, path))

    def test_the_queries_of_the_route_are_the_ones_it_always_had(self):
        with Running() as running:
            self.assertEqual(running.call("GET", "/heatmap?camera=ghost")[0], 404)
            self.assertEqual(running.call("GET", "/heatmap?scale=0")[0], 400)
            self.assertEqual(running.call("GET", "/heatmap?format=gif")[0], 400)
            self.assertEqual(running.call("GET", "/heatmap?x=1")[0], 400)
            self.assertEqual(running.call("GET", "/heatmap?format=json&format=svg")[0], 400)
            self.assertEqual(running.call("GET", "/heatmap?" + "a" * 600)[0], 414)

    def test_the_memory_is_bounded_whatever_comes_in(self):
        parsed, _ = activity(cols=8, rows=6, max_cells=48, window_seconds=60.0, slices=6)
        service = LiveService(vision(), parsed, ServiceSettings(port=0))
        rng = random.Random(3)
        for step in range(3000):
            x, y = rng.random() * 0.9, rng.random() * 0.7 + 0.2
            status, _ = service.ingest(record(step * 0.5, box=(x, y, x + 0.05, y + 0.1), count=rng.randint(0, 5)))
            self.assertEqual(status, 200)
        engine = service._engine
        assert engine is not None
        heat = engine.heatmap("cam-front")
        self.assertLessEqual(len(heat._slices), 6)
        self.assertTrue(all(len(cells) <= 48 for cells in heat._slices.values()))
        self.assertLessEqual(len(engine._trackers["cam-front"].tracks), 5 * 6)

    def test_the_simulated_scene_fills_the_map_before_anything_comes_in(self):
        parsed, _ = activity()
        settings, problems = parse_service_settings({"port": 8765, "simulate": {"camera_id": "cam-front", "seed": 2, "objects": 3, "duration": 20, "fps": 5}})
        self.assertEqual(problems, [])
        assert settings is not None
        service = LiveService(vision(), parsed, settings)
        status, kind, body = service.heatmap({})
        self.assertEqual((status, kind), (200, "application/json"))
        self.assertGreater(json.loads(body)["total"], 0)

    def test_the_command_checks_its_files_and_refuses_to_serve_what_is_off(self):
        with tempfile.TemporaryDirectory() as folder:
            off = Path(folder) / "off.json"
            off.write_text(json.dumps({**ACTIVITY_EXAMPLE, "enabled": False}), encoding="utf-8")
            self.assertEqual(main(["serve", "--activity-config", str(off)]), 1)
            bad = Path(folder) / "svc.json"
            bad.write_text(json.dumps({"host": "0.0.0.0"}), encoding="utf-8")
            on = Path(folder) / "on.json"
            on.write_text(json.dumps({**ACTIVITY_EXAMPLE, "enabled": True}), encoding="utf-8")
            self.assertEqual(main(["serve", "--activity-config", str(on), "--service-config", str(bad)]), 1)
            self.assertEqual(main(["check-service-config", str(bad)]), 1)
            self.assertEqual(main(["check-service-config", str(Path(folder) / "none.json")]), 2)
            self.assertEqual(main(["service-example"]), 0)


if __name__ == "__main__":
    unittest.main()
