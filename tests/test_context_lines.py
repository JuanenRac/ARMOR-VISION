"""The counting lines each camera gets from the context of the server: read per camera, applied to the engine, taken by the live service."""
import copy
import unittest

from armor_vision.activity import ActivityEngine
from armor_vision.activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG
from armor_vision.config import parse_config
from armor_vision.context_lines import parse_context_lines
from armor_vision.service import LiveService, ServiceSettings
from armor_vision.tracker import Detection

CAM = "cam-front"


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity():
    raw = copy.deepcopy(ACTIVITY_EXAMPLE)
    raw["events"]["lines"] = []
    config, errors = parse_activity_config(raw)
    assert config is not None, errors
    return config


def context(*cameras):
    return {"mode": "home", "nodes": [], "cameras": list(cameras)}


LINE = {"id": "gate", "a": [0.0, 0.5], "b": [1.0, 0.5]}


class ParseTests(unittest.TestCase):
    def test_each_camera_keeps_its_own_lines(self):
        found, problems = parse_context_lines(context({"id": "a", "lines": [LINE]}, {"id": "b"}, {"id": "c", "lines": [dict(LINE, id="x", labels=["person"])]}))
        self.assertEqual(problems, [])
        self.assertEqual(sorted(found), ["a", "c"])
        self.assertEqual(found["a"][0].line_id, "gate")
        self.assertEqual(found["c"][0].labels, ("person",))

    def test_a_bad_camera_loses_only_its_own_lines(self):
        found, problems = parse_context_lines(context({"id": "a", "lines": [dict(LINE, a=[2, 2])]}, {"id": "b", "lines": [LINE]}, {"id": "c", "lines": "no"}, {"nope": 1}))
        self.assertEqual(sorted(found), ["b"])
        self.assertEqual(len(problems), 3)

    def test_what_is_not_a_context_gives_nothing(self):
        for raw in (None, [], "x", {"cameras": 3}):
            self.assertEqual(parse_context_lines(raw)[0], {}, raw)
            self.assertTrue(parse_context_lines(raw)[1], raw)

    def test_more_than_sixteen_lines_are_refused(self):
        lines = [dict(LINE, id=f"l{i}") for i in range(17)]
        self.assertEqual(parse_context_lines(context({"id": "a", "lines": lines}))[0], {})


def cross(engine, camera=CAM):
    out = []
    for t, y in ((0.0, 0.46), (0.5, 0.54)):
        out += engine.process(camera, t, [Detection("person", 0.9, (0.4, y - 0.3, 0.5, y))])
    return [e for e in out if e["type"] == "line_cross"]


class EngineTests(unittest.TestCase):
    def test_a_line_of_the_server_counts_crossings_of_its_camera_only(self):
        engine = ActivityEngine(vision(), activity())
        self.assertEqual(cross(engine), [])
        lines, _ = parse_context_lines(context({"id": CAM, "lines": [LINE]}))
        self.assertEqual(engine.set_camera_lines(lines), [])
        engine2 = ActivityEngine(vision(), activity())
        engine2.set_camera_lines(lines)
        self.assertEqual([e["line_id"] for e in cross(engine2)], ["gate"])

    def test_a_camera_that_is_not_configured_is_ignored_and_reported(self):
        engine = ActivityEngine(vision(), activity())
        lines, _ = parse_context_lines(context({"id": "ghost", "lines": [LINE]}))
        self.assertEqual(engine.set_camera_lines(lines), ["ghost"])

    def test_a_new_context_replaces_the_old_lines(self):
        engine = ActivityEngine(vision(), activity())
        engine.set_camera_lines(parse_context_lines(context({"id": CAM, "lines": [LINE]}))[0])
        engine.set_camera_lines({})
        self.assertEqual(cross(engine), [])


class ServiceTests(unittest.TestCase):
    def test_the_service_takes_the_context(self):
        service = LiveService(vision(), activity(), ServiceSettings(port=0))
        self.assertEqual(service.apply_context(context({"id": CAM, "lines": [LINE]}, {"id": "ghost", "lines": [LINE]}, {"id": "x", "lines": 3}))[1]["cameras"], 1)
        self.assertEqual(service.apply_context("no")[0], 400)

    def test_the_service_refuses_it_while_the_pipeline_is_off(self):
        off = copy.deepcopy(ACTIVITY_EXAMPLE)
        off["enabled"] = False
        config, _ = parse_activity_config(off)
        self.assertEqual(LiveService(vision(), config, ServiceSettings(port=0)).apply_context(context())[0], 503)


if __name__ == "__main__":
    unittest.main()
