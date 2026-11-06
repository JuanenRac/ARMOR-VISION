"""The count of crossings per counting line: kept in the engine, listed per camera and line, handed out by GET /counts of the live service, with nothing but numbers in it."""
import copy
import http.client
import json
import threading
import unittest

from armor_vision.activity import ActivityEngine
from armor_vision.activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG
from armor_vision.config import parse_config
from armor_vision.context_lines import parse_context_lines
from armor_vision.service import COUNTS_SCHEMA, LiveService, ServiceSettings, make_server
from armor_vision.tracker import Detection

CAM = "cam-front"
LINE = {"id": "gate", "a": [0.0, 0.5], "b": [1.0, 0.5]}


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity(enabled=True, global_lines=()):
    raw = copy.deepcopy(ACTIVITY_EXAMPLE)
    raw["enabled"] = enabled
    raw["events"]["lines"] = list(global_lines)
    config, errors = parse_activity_config(raw)
    assert config is not None, errors
    return config


def walk(engine, ys, camera=CAM, start=0.0):
    for step, y in enumerate(ys):
        engine.process(camera, start + step * 0.5, [Detection("person", 0.9, (0.4, y - 0.3, 0.5, y))])


def lines_of(*cameras):
    return parse_context_lines({"mode": "home", "nodes": [], "cameras": list(cameras)})[0]


class EngineCountTests(unittest.TestCase):
    def test_there_are_no_counts_without_lines(self):
        self.assertEqual(ActivityEngine(vision(), activity()).line_counts(), {})

    def test_a_line_is_listed_with_zeros_before_anything_crosses_it(self):
        engine = ActivityEngine(vision(), activity())
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        self.assertEqual(engine.line_counts(), {CAM: {"gate": {"to_left": 0, "to_right": 0}}})

    def test_each_crossing_is_counted_in_its_direction(self):
        engine = ActivityEngine(vision(), activity())
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        walk(engine, [0.46, 0.54])          # down
        walk(engine, [0.54, 0.46], start=10.0)   # and back up
        walk(engine, [0.46, 0.54], start=20.0)
        counts = engine.line_counts()[CAM]["gate"]
        self.assertEqual(counts["to_left"] + counts["to_right"], 3)
        self.assertEqual(sorted(counts.values()), [1, 2])

    def test_a_line_taken_away_takes_its_count_with_it(self):
        engine = ActivityEngine(vision(), activity())
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        walk(engine, [0.46, 0.54])
        engine.set_camera_lines({})
        self.assertEqual(engine.line_counts(), {})
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        self.assertEqual(engine.line_counts()[CAM]["gate"], {"to_left": 0, "to_right": 0})

    def test_a_new_context_with_the_same_line_keeps_its_count(self):
        engine = ActivityEngine(vision(), activity())
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        walk(engine, [0.46, 0.54])
        before = engine.line_counts()
        engine.set_camera_lines(lines_of({"id": CAM, "lines": [LINE]}))
        self.assertEqual(engine.line_counts(), before)

    def test_a_global_line_of_the_configuration_is_counted_too(self):
        engine = ActivityEngine(vision(), activity(global_lines=[{"id": "street", "a": [0.0, 0.5], "b": [1.0, 0.5]}]))
        walk(engine, [0.46, 0.54])
        counts = engine.line_counts()[CAM]["street"]
        self.assertEqual(sum(counts.values()), 1)


class Running:
    def __init__(self, enabled=True, token=None):
        self.service = LiveService(vision(), activity(enabled), ServiceSettings(port=0), token)
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
            data = None if body is None else json.dumps(body).encode()
            connection.request(method, path, body=data, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()


class ServiceCountTests(unittest.TestCase):
    def test_the_route_lists_the_counts_as_numbers_only(self):
        with Running() as live:
            self.assertEqual(live.call("POST", "/context", {"mode": "home", "nodes": [], "cameras": [{"id": CAM, "lines": [LINE]}]})[0], 200)
            for step, y in enumerate((0.46, 0.54)):
                observation = {"camera_id": CAM, "timestamp": step * 0.5, "detections": [{"label": "person", "confidence": 0.9, "box": [0.4, y - 0.3, 0.5, y]}]}
                self.assertEqual(live.call("POST", "/ingest", observation)[0], 200)
            status, body = live.call("GET", "/counts")
            self.assertEqual(status, 200)
            answer = json.loads(body)
            self.assertEqual(answer["schema"], COUNTS_SCHEMA)
            self.assertEqual(set(answer), {"schema", "cameras"})
            counts = answer["cameras"][CAM]["gate"]
            self.assertEqual(sorted(counts), ["to_left", "to_right"])
            self.assertEqual(sum(counts.values()), 1)
            self.assertTrue(all(isinstance(value, int) for value in counts.values()))

    def test_the_route_is_not_there_while_the_pipeline_is_off_and_takes_no_parameters(self):
        off = Running(enabled=False)
        with off:
            self.assertEqual(off.call("GET", "/counts")[0], 404)
        with Running() as live:
            self.assertEqual(live.call("GET", "/counts?camera=x")[0], 400)
            self.assertEqual(live.call("POST", "/counts", {})[0], 404)

    def test_the_route_asks_for_the_token_like_the_others(self):
        token = "t" * 32
        with Running(token=token) as live:
            self.assertEqual(live.call("GET", "/counts")[0], 401)
            self.assertEqual(live.call("GET", "/counts", headers={"Authorization": f"Bearer {token}"})[0], 200)


if __name__ == "__main__":
    unittest.main()
