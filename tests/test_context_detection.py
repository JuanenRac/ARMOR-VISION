"""The detection zones and mode profiles each camera gets from the context of the server: read per camera, filtered by mode, applied to the engine, taken by the live service."""
import copy
import unittest

from armor_vision.activity import ActivityEngine
from armor_vision.activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG
from armor_vision.config import parse_config
from armor_vision.context_detection import parse_context_detection
from armor_vision.service import LiveService, ServiceSettings
from armor_vision.tracker import Detection

CAM = "cam-front"
SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]]
ZONE = {"id": "porch", "name": "Porch", "points": SQUARE, "kind": "alert", "labels": ["person"], "min_frames": 1, "min_seconds": 0}
ZONE2 = dict(ZONE, id="yard", name="Yard", labels=[])


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity():
    config, errors = parse_activity_config(copy.deepcopy(ACTIVITY_EXAMPLE))
    assert config is not None, errors
    return config


def context(*cameras, mode="home"):
    return {"mode": mode, "nodes": [], "cameras": list(cameras)}


def camera(zones, profiles=None, camera_id=CAM):
    detection = {"zones": zones}
    if profiles is not None:
        detection["profiles"] = profiles
    return {"id": camera_id, "detection": detection}


def walk(engine, camera_id=CAM):
    out = []
    for t in (0.0, 0.5):
        out += engine.process(camera_id, t, [Detection("person", 0.9, (0.45, 0.4, 0.55, 0.6))])
    return sorted({e["zone_id"] for e in out if e["type"] == "zone_enter"} - {"drive", "street"})


class ParseTests(unittest.TestCase):
    def test_zones_and_profiles_are_read_per_camera(self):
        found, mode, problems = parse_context_detection(context(camera([ZONE, ZONE2], {"away": {"watch": ["porch"], "sensitivity": "high", "notify": False}}), {"id": "other"}, mode="away"))
        self.assertEqual(problems, [])
        self.assertEqual(mode, "away")
        self.assertEqual(sorted(found), [CAM])
        detection = found[CAM]
        self.assertEqual([z.zone_id for z in detection.zones], ["porch", "yard"])
        self.assertEqual(detection.profiles["away"].sensitivity, "high")
        self.assertFalse(detection.profiles["away"].notify)

    def test_a_mode_without_profile_watches_every_zone(self):
        found, _, _ = parse_context_detection(context(camera([ZONE, ZONE2], {"away": {"watch": ["porch"]}})))
        detection = found[CAM]
        self.assertEqual([z.zone_id for z in detection.watched("away")], ["porch"])
        for mode in ("home", "night", "disarmed", "something-new", None):
            self.assertEqual([z.zone_id for z in detection.watched(mode)], ["porch", "yard"], mode)

    def test_a_profile_may_watch_nothing(self):
        found, _, _ = parse_context_detection(context(camera([ZONE], {"night": {"watch": []}})))
        self.assertEqual(found[CAM].watched("night"), ())

    def test_a_bad_camera_loses_only_its_own_zones(self):
        bad_corner = dict(ZONE, points=[[0.1, 0.1], [2, 2], [0.5, 0.5]])
        found, _, problems = parse_context_detection(context(
            camera([bad_corner], camera_id="a"), camera([ZONE], camera_id="b"), camera("no", camera_id="c"),
            camera([ZONE], {"away": {"watch": ["ghost"]}}, camera_id="d"), camera([ZONE], {"sleep": {"watch": []}}, camera_id="e"),
            camera([ZONE], {"away": {"watch": [], "sensitivity": "extreme"}}, camera_id="f"), {"nope": 1}))
        self.assertEqual(sorted(found), ["b"])
        self.assertGreaterEqual(len(problems), 6)

    def test_what_is_not_a_context_gives_nothing(self):
        for raw in (None, [], "x", {"cameras": 3}):
            found, mode, problems = parse_context_detection(raw)
            self.assertEqual((found, mode), ({}, None), raw)
            self.assertTrue(problems, raw)

    def test_more_than_sixteen_zones_are_refused(self):
        zones = [dict(ZONE, id=f"z{i}") for i in range(17)]
        self.assertEqual(parse_context_detection(context(camera(zones)))[0], {})

    def test_an_unknown_field_is_refused(self):
        self.assertEqual(parse_context_detection(context({"id": CAM, "detection": {"zones": [], "extra": 1}}))[0], {})

    def test_a_camera_with_no_zones_is_left_out(self):
        self.assertEqual(parse_context_detection(context(camera([])))[0], {})


class EngineTests(unittest.TestCase):
    def engine(self, mode, profiles=None):
        engine = ActivityEngine(vision(), activity())
        found, found_mode, _ = parse_context_detection(context(camera([ZONE, ZONE2], profiles), mode=mode))
        self.assertEqual(engine.set_camera_detection(found, found_mode), [])
        return engine

    def test_a_zone_of_the_server_reports_for_its_camera(self):
        self.assertEqual(walk(self.engine("home")), ["porch", "yard"])

    def test_the_profile_of_the_mode_picks_the_zones(self):
        self.assertEqual(walk(self.engine("away", {"away": {"watch": ["yard"]}})), ["yard"])
        self.assertEqual(walk(self.engine("home", {"away": {"watch": ["yard"]}})), ["porch", "yard"])

    def test_a_new_context_replaces_the_old_zones(self):
        engine = self.engine("home")
        engine.set_camera_detection({}, "home")
        self.assertEqual(walk(engine), [])

    def test_a_camera_that_is_not_configured_is_ignored_and_reported(self):
        engine = ActivityEngine(vision(), activity())
        found, mode, _ = parse_context_detection(context(camera([ZONE], camera_id="ghost")))
        self.assertEqual(engine.set_camera_detection(found, mode), ["ghost"])

    def test_a_zone_id_that_the_configuration_has_keeps_the_configured_one(self):
        base = vision()
        taken = base.cameras[CAM].zones[0]
        engine = ActivityEngine(base, activity())
        found, mode, _ = parse_context_detection(context(camera([dict(ZONE, id=taken.zone_id, points=[[0.0, 0.0], [0.1, 0.0], [0.1, 0.1]])])))
        engine.set_camera_detection(found, mode)
        self.assertEqual(engine._camera_zones, {})


class ServiceTests(unittest.TestCase):
    def test_the_service_takes_the_zones_with_the_lines(self):
        service = LiveService(vision(), activity(), ServiceSettings(port=0))
        answer = service.apply_context(context(camera([ZONE]), camera([ZONE], camera_id="ghost"), camera("no", camera_id="x")))
        self.assertEqual(answer[0], 200)
        self.assertEqual(answer[1]["cameras"], 1)
        self.assertEqual(answer[1]["ignored"], 2)


if __name__ == "__main__":
    unittest.main()
