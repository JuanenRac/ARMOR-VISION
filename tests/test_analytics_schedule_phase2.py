"""Speed in a zone, abandoned objects, the PTZ follower, the vectors of an event, the schedule by hour and the second phase (all off by default)."""
import json
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision import analytics as an
from armor_vision import phase2 as p2
from armor_vision.config import parse_config
from armor_vision.motion import Frame
from armor_vision.pipeline import Pipeline
from armor_vision.schedule import parse_schedule
from armor_vision.tracker import Detection, Track, Tracker

SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
GROUND = [[0, 0], [10, 0], [10, 20], [0, 20]]          # the picture is a 10 x 20 metre yard


def track(track_id=1, label="person", box=(0.4, 0.4, 0.5, 0.5), history=None, stationary=False, confidence=0.9):
    item = Track(track_id, label, box, confidence, 0.0, 0.0)
    item.history = history or []
    item.stationary = stationary
    return item


def foot_box(x, y):
    return (x - 0.02, y - 0.1, x + 0.02, y)


class CalibrationTests(unittest.TestCase):
    def test_the_reference_points_come_back_and_the_middle_is_the_middle(self):
        calibration, errors = an.Calibration.from_points(SQUARE, GROUND)
        self.assertEqual(errors, [])
        self.assertEqual([round(v, 6) for v in calibration.to_ground((0.5, 0.5))], [5.0, 10.0])
        self.assertEqual([round(v, 6) for v in calibration.to_ground((1.0, 1.0))], [10.0, 20.0])

    def test_bad_reference_points_are_refused(self):
        for image, ground, text in (([[0, 0]] * 3, GROUND, "four"), (SQUARE, [[0, 0]] * 4, "different"), ([[0, 0], [0.5, 0], [1, 0], [0.2, 0]], GROUND, "line"),
                                    ([[0, 0], [2, 0], [1, 1], [0, 1]], GROUND, "normalised"), ([[0, 0], [1, 0], [1, 1], ["a", 1]], GROUND, "finite"), ("x", GROUND, "four")):
            calibration, errors = an.Calibration.from_points(image, ground)
            self.assertIsNone(calibration, (image, ground))
            self.assertTrue(any(text in e for e in errors), (text, errors))


def speed_settings(**extra):
    raw = {"zone": SQUARE, "reference": {"image": SQUARE, "ground": GROUND}, **extra}
    settings, errors = an.parse_speed_settings(raw)
    assert settings is not None, errors
    return settings


class SpeedTests(unittest.TestCase):
    def test_a_walker_crossing_the_yard_is_measured(self):
        estimator = an.SpeedEstimator(speed_settings(report_every=0.1))
        readings = []
        for step in range(5):                                     # 0.2 of the height (4 m) per second
            readings += estimator.update(float(step), [track(box=foot_box(0.5, 0.2 + 0.2 * step))])
        self.assertTrue(readings)
        self.assertAlmostEqual(readings[-1].metres_per_second, 4.0, places=2)
        self.assertAlmostEqual(readings[-1].kmh, 14.4, places=1)

    def test_only_over_the_limit_is_reported_and_once_per_interval(self):
        estimator = an.SpeedEstimator(speed_settings(limit_kmh=10, report_every=2.5))
        out = []
        for step in range(7):
            out += estimator.update(step * 0.5, [track(box=foot_box(0.5, 0.1 + 0.1 * step))])   # 0.2 per second = 4 m/s = 14.4 km/h
        self.assertEqual(len(out), 2)
        self.assertTrue(an.speed_event("cam", out[0], 10)["over_limit"])
        self.assertFalse(an.speed_event("cam", out[0], 50)["over_limit"])
        self.assertIs(an.speed_event("cam", out[0])["authorizes_action"], False)
        slow = an.SpeedEstimator(speed_settings(limit_kmh=30))
        self.assertEqual(sum((slow.update(float(s), [track(box=foot_box(0.5, 0.2 + 0.1 * s))]) for s in range(6)), []), [])

    def test_a_jump_of_the_tracker_is_not_a_speed_and_leaving_the_zone_restarts_the_measure(self):
        settings, _ = an.parse_speed_settings({"zone": [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]], "reference": {"image": SQUARE, "ground": GROUND}, "report_every": 0.1, "max_kmh": 20})
        estimator = an.SpeedEstimator(settings)
        self.assertEqual(estimator.update(0.0, [track(box=foot_box(0.3, 0.3))]), [])
        self.assertEqual(estimator.update(1.0, [track(box=foot_box(0.7, 0.7))]), [])      # 28 m in a second: a jump
        self.assertEqual(estimator.update(2.0, [track(box=foot_box(0.95, 0.95))]), [])    # outside the zone
        self.assertEqual(estimator.update(3.0, [track(box=foot_box(0.5, 0.5))]), [])      # starts again: one sample
        self.assertEqual(estimator.update(3.1, [track(box=foot_box(0.5, 0.5))]), [])      # too short a time

    def test_settings_mistakes(self):
        good = {"zone": SQUARE, "reference": {"image": SQUARE, "ground": GROUND}}
        for change, text in (({"zone": [[0, 0]]}, "zone"), ({"reference": {"image": SQUARE}}, "reference"), ({"window_seconds": 0}, "window_seconds"), ({"limit_kmh": -1}, "limit_kmh"),
                             ({"extra": 1}, "unknown")):
            settings, errors = an.parse_speed_settings({**good, **change})
            self.assertIsNone(settings)
            self.assertTrue(any(text in e for e in errors), (change, errors))
        self.assertIsNone(an.parse_speed_settings([])[0])
        self.assertIsNone(an.parse_speed_settings({})[0])


class AbandonedTests(unittest.TestCase):
    def test_a_bag_left_alone_for_a_minute_is_reported_once(self):
        detector = an.AbandonedObjectDetector(an.AbandonedSettings(min_seconds=60))
        bag = track(7, "backpack", (0.7, 0.7, 0.75, 0.75), stationary=True)
        events = []
        for second in range(0, 130, 10):
            events += detector.update("cam", float(second), [bag])
        self.assertEqual([(e["track_id"], e["alone_seconds"], e["authorizes_action"]) for e in events], [(7, 60.0, False)])

    def test_the_owner_standing_near_resets_the_wait(self):
        detector = an.AbandonedObjectDetector(an.AbandonedSettings(min_seconds=30))
        bag = track(7, "suitcase", (0.7, 0.7, 0.75, 0.75), stationary=True)
        owner = track(8, "person", (0.6, 0.6, 0.65, 0.7))
        events = detector.update("cam", 0.0, [bag]) + detector.update("cam", 20.0, [bag]) + detector.update("cam", 25.0, [bag, owner]) + detector.update("cam", 50.0, [bag])
        self.assertEqual(events, [])
        self.assertEqual(len(detector.update("cam", 80.0, [bag])), 1)

    def test_other_things_and_moving_things_are_ignored_and_a_gone_object_is_forgotten(self):
        detector = an.AbandonedObjectDetector(an.AbandonedSettings(min_seconds=1))
        car = track(1, "car", stationary=True)
        moving = track(2, "box", stationary=False)
        for t in (0.0, 5.0, 10.0):
            self.assertEqual(detector.update("cam", t, [car, moving]), [])
        bag = track(3, "bag", stationary=True)
        detector.update("cam", 20.0, [bag])
        detector.update("cam", 21.0, [])
        self.assertEqual(detector.update("cam", 22.0, [bag]), [])      # it was forgotten, the wait starts again

    def test_settings(self):
        got, errors = an.parse_abandoned_settings({"labels": ["bag"], "min_seconds": 30})
        self.assertEqual((errors, got.labels, got.min_seconds), ([], ("bag",), 30.0))
        for raw in ([], {"labels": []}, {"min_seconds": 0}, {"owner_distance": 9}, {"x": 1}, {"owner_labels": [3]}):
            self.assertIsNone(an.parse_abandoned_settings(raw)[0], raw)


class PtzTests(unittest.TestCase):
    def test_the_target_off_centre_gives_a_move_towards_it(self):
        follower = an.PtzFollower()
        command = follower.follow(0.0, [track(1, "person", (0.7, 0.2, 0.8, 0.4))])
        self.assertGreater(command.pan, 0)
        self.assertGreater(command.tilt, 0)
        self.assertEqual(command.track_id, 1)
        left = an.PtzFollower().follow(0.0, [track(1, "person", (0.1, 0.5, 0.2, 0.8))])
        self.assertLess(left.pan, 0)

    def test_a_centred_target_is_not_chased_and_the_speed_is_bounded(self):
        centred = an.PtzFollower().follow(0.0, [track(1, "person", (0.46, 0.35, 0.54, 0.65))])
        self.assertEqual((centred.pan, centred.tilt), (0.0, 0.0))
        far = an.PtzFollower(max_speed=0.5).follow(0.0, [track(1, "person", (0.95, 0.4, 1.0, 0.6))])
        self.assertEqual(far.pan, 0.5)

    def test_it_keeps_its_target_zooms_and_stops_when_it_is_lost(self):
        follower = an.PtzFollower(lost_seconds=3)
        first = follower.follow(0.0, [track(1, "person", (0.3, 0.3, 0.32, 0.34)), track(2, "person", (0.5, 0.2, 0.7, 0.8))])
        self.assertEqual(first.track_id, 2)                                           # the biggest
        again = follower.follow(1.0, [track(1, "person", (0.3, 0.3, 0.7, 0.9)), track(2, "person", (0.5, 0.45, 0.52, 0.5))])
        self.assertEqual(again.track_id, 2)                                           # keeps it though another is bigger now
        self.assertEqual(again.zoom, 0.3)                                             # small in the picture: zoom in
        self.assertIsNone(follower.follow(2.0, []))
        stop = follower.follow(5.0, [])
        self.assertTrue(stop.stop and stop.track_id is None)
        self.assertIsNone(follower.follow(6.0, []))
        wide = an.PtzFollower().follow(0.0, [track(1, "person", (0.2, 0.0, 0.8, 1.0))])
        self.assertEqual(wide.zoom, -0.3)

    def test_other_labels_are_not_followed_and_the_simulated_controller_only_records(self):
        self.assertIsNone(an.PtzFollower().follow(0.0, [track(1, "cat")]))
        ptz = an.SimulatedPtz()
        ptz.apply("cam", an.PtzCommand(0.1, 0, 0, 1))
        self.assertEqual(len(ptz.commands), 1)


class VectorsTests(unittest.TestCase):
    def test_direction_and_speed_from_the_history(self):
        moving = track(1, history=[(0.0, (0.2, 0.2)), (1.0, (0.5, 0.6))])
        (vector,) = an.track_vectors([moving, track(2, history=[(0.0, (0.5, 0.5)), (2.0, (0.5, 0.5))]), track(3, history=[(0.0, (0.1, 0.1))])])
        self.assertEqual((vector["track_id"], vector["dx"], vector["dy"], vector["speed"]), (1, 0.6, 0.8, 0.5))

    def test_the_fastest_first_and_bounded(self):
        tracks = [track(i, history=[(0.0, (0.1, 0.1)), (1.0, (0.1 + 0.01 * i, 0.1))]) for i in range(1, 30)]
        found = an.track_vectors(tracks, 16)
        self.assertEqual((len(found), found[0]["track_id"]), (16, 29))
        self.assertEqual(an.track_vectors(tracks, 0), [])

    def test_an_event_carries_the_vectors_on_request(self):
        config, _ = parse_config({"cameras": {"cam": {"zones": [{"id": "z", "name": "Z", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}}]}}})
        plain, with_vectors = Pipeline(config), Pipeline(config, with_vectors=True)
        detection = Detection("person", 0.9, (0.4, 0.4, 0.5, 0.6))
        self.assertNotIn("vectors", plain.process_detections("cam", 0.0, [detection])[0])
        for step in range(3):
            events = with_vectors.process_detections("cam", float(step), [Detection("person", 0.9, (0.4 + 0.05 * step, 0.4, 0.5 + 0.05 * step, 0.6))])
        self.assertEqual(events, [])      # one visit, one event: the first call
        first = Pipeline(config, with_vectors=True).process_detections("cam", 0.0, [detection])[0]
        self.assertEqual(first["vectors"], [])

    def test_make_event_refuses_too_many(self):
        from armor_vision.rules import make_event
        config, _ = parse_config({"cameras": {"cam": {"zones": [{"id": "z", "name": "Z", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}}]}}})
        zone = config.cameras["cam"].zones[0]
        item = Tracker().update(0.0, [Detection("person", 0.9, (0.1, 0.1, 0.2, 0.2))])[0]
        self.assertEqual(make_event("cam", zone, item, 0.0, vectors=[])["vectors"], [])
        with self.assertRaises(ValueError):
            make_event("cam", zone, item, 0.0, vectors=[{}] * 17)


class ScheduleTests(unittest.TestCase):
    def cam(self):
        config, errors = parse_config({"cameras": {"cam": {"motion_threshold": 25, "motion_min_cells": 2, "masks": [{"x": 0, "y": 0, "w": 0.1, "h": 0.1}]}}})
        assert config is not None, errors
        return config.cameras["cam"]

    def schedule(self, **extra):
        raw = {"utc_offset_minutes": 0, "cameras": {"cam": [
            {"name": "night", "from": "22:00", "to": "06:00", "motion_threshold": 15, "masks": [{"x": 0.5, "y": 0.5, "w": 0.2, "h": 0.2}]},
            {"name": "away", "from": "08:00", "to": "18:00", "days": ["mon", "tue", "wed", "thu", "fri"], "mode": "away", "motion_min_cells": 1},
            {"name": "day", "from": "06:00", "to": "22:00", "motion_threshold": 40}]}, **extra}
        schedule, errors = parse_schedule(raw, {"cam"})
        assert schedule is not None, errors
        return schedule

    @staticmethod
    def at(year, month, day, hour, minute=0):
        import calendar
        return float(calendar.timegm((year, month, day, hour, minute, 0)))

    def test_night_crosses_midnight_and_adds_its_masks(self):
        schedule, camera = self.schedule(), self.cam()
        for hour in (23, 2, 5):
            effective = schedule.effective(camera, self.at(2026, 11, 11, hour))        # a Wednesday
            self.assertEqual((effective.name, effective.motion_threshold, len(effective.masks), effective.motion_min_cells), ("night", 15, 2, 2))
        self.assertEqual(schedule.effective(camera, self.at(2026, 11, 11, 6)).name, "day")
        self.assertEqual(schedule.effective(camera, self.at(2026, 11, 11, 22)).name, "night")

    def test_a_window_of_a_mode_and_of_weekdays(self):
        schedule, camera = self.schedule(), self.cam()
        wednesday, sunday = self.at(2026, 11, 11, 10), self.at(2026, 11, 15, 10)
        self.assertEqual(schedule.effective(camera, wednesday, "away").name, "away")
        self.assertEqual(schedule.effective(camera, wednesday, "away").motion_min_cells, 1)
        self.assertEqual(schedule.effective(camera, wednesday, "stay").name, "day")
        self.assertEqual(schedule.effective(camera, wednesday, None).name, "day")
        self.assertEqual(schedule.effective(camera, sunday, "away").name, "day")

    def test_a_camera_without_windows_keeps_its_own_values(self):
        effective = self.schedule().effective(self.cam().__class__("other", (), (), 30, 3), self.at(2026, 11, 11, 3))
        self.assertEqual((effective.name, effective.motion_threshold, effective.motion_min_cells), (None, 30, 3))

    def test_a_fixed_offset_moves_the_clock(self):
        schedule, _ = parse_schedule({"utc_offset_minutes": 120, "cameras": {"cam": [{"name": "n", "from": "00:00", "to": "01:00"}]}})
        camera = self.cam()
        self.assertEqual(schedule.effective(camera, self.at(2026, 11, 11, 22, 30)).name, "n")      # 00:30 at +02:00
        self.assertIsNone(schedule.effective(camera, self.at(2026, 11, 11, 20)).name)
        local, _ = parse_schedule({"cameras": {"cam": [{"name": "all", "from": "00:00", "to": "00:00"}]}})
        self.assertEqual(local.effective(camera, time.time()).name, "all")

    def test_mistakes_are_told(self):
        window = {"name": "n", "from": "22:00", "to": "06:00"}
        for raw, text in (([], "object"), ({"x": 1}, "unknown"), ({"utc_offset_minutes": 9999}, "utc_offset"), ({"cameras": []}, "cameras"), ({"cameras": {"ghost": [window]}}, "not in"),
                          ({"cameras": {"cam": {}}}, "list"), ({"cameras": {"cam": [{**window, "from": "25:00"}]}}, "from"), ({"cameras": {"cam": [{**window, "days": ["xyz"]}]}}, "days"),
                          ({"cameras": {"cam": [{**window, "motion_threshold": 0}]}}, "motion_threshold"), ({"cameras": {"cam": [{**window, "motion_min_cells": 0}]}}, "motion_min_cells"),
                          ({"cameras": {"cam": [{"from": "01:00", "to": "02:00"}]}}, "name"), ({"cameras": {"cam": [{**window, "masks": [[[0, 0]]]}]}}, "mask"),
                          ({"cameras": {"cam": [{**window, "bogus": 1}]}}, "unknown"), ({"cameras": {"cam": ["x"]}}, "object"), ({"cameras": {"cam": [{**window, "mode": ""}]}}, "mode")):
            schedule, errors = parse_schedule(raw, {"cam"})
            self.assertIsNone(schedule, raw)
            self.assertTrue(any(text in e for e in errors), (text, errors))

    def test_the_pipeline_uses_the_masks_and_sensitivity_of_the_hour(self):
        config, _ = parse_config({"cameras": {"cam": {"motion_threshold": 25, "motion_min_cells": 1, "zones": [{"id": "z", "name": "Z", "rect": {"x": 0, "y": 0, "w": 1, "h": 1}}]}}})
        schedule, _ = parse_schedule({"utc_offset_minutes": 0, "cameras": {"cam": [{"name": "night", "from": "22:00", "to": "06:00", "masks": [{"x": 0, "y": 0, "w": 1, "h": 1}]}]}})
        calls = []

        class Spy:
            def detect(self, frame, hints):
                calls.append(1)
                return []
        dark = Frame(32, 18, bytes(32 * 18))
        light = Frame(32, 18, b"".join((bytes([255]) * 16 + bytes(16)) for _ in range(18)))     # the left half changes: a block, not the whole picture
        night = Pipeline(config, Spy(), schedule=schedule)
        night.process_frame("cam", self.at(2026, 11, 11, 23), dark)
        night.process_frame("cam", self.at(2026, 11, 11, 23) + 1, light)
        self.assertEqual(calls, [])                                  # everything is masked at night
        day = Pipeline(config, Spy(), schedule=schedule)
        day.process_frame("cam", self.at(2026, 11, 11, 12), dark)
        day.process_frame("cam", self.at(2026, 11, 11, 12) + 1, light)
        self.assertEqual(calls, [1])


ADMIN = p2.Actor("owner", "admin")


class Phase2Tests(unittest.TestCase):
    FRAME = Frame(2, 2, bytes(4))
    BOX = (0.1, 0.1, 0.3, 0.3)

    def test_everything_is_off_by_default(self):
        settings = p2.Phase2Settings()
        self.assertEqual([settings.enabled(f) for f in p2.FEATURES], [False, False, False])
        self.assertEqual(p2.parse_phase2_settings(None)[0], settings)
        phase = p2.Phase2(settings)
        for call in (lambda: phase.index("a", "x"), lambda: phase.search("x"), lambda: phase.read_plate(self.FRAME, self.BOX), lambda: phase.enrol("ana", [1.0], True, ADMIN),
                     lambda: phase.match_face(self.FRAME, self.BOX)):
            with self.assertRaises(p2.FeatureDisabled):
                call()

    def test_a_switch_needs_the_acknowledgement_of_its_notice(self):
        settings, errors = p2.parse_phase2_settings({"faces": True})
        self.assertIsNone(settings)
        self.assertTrue(any("not acknowledged" in e for e in errors))
        settings, errors = p2.parse_phase2_settings({"faces": True, "acknowledged": ["faces"]})
        self.assertEqual((errors, settings.enabled("faces"), settings.enabled("plates")), ([], True, False))
        acknowledged_only = p2.parse_phase2_settings({"acknowledged": ["plates"]})[0]
        self.assertFalse(acknowledged_only.enabled("plates"))
        for raw in ([], {"faces": "yes"}, {"x": 1}, {"acknowledged": ["eyes"]}, {"acknowledged": "faces"}):
            self.assertIsNone(p2.parse_phase2_settings(raw)[0], raw)

    def test_every_notice_exists_in_the_eight_languages(self):
        self.assertEqual(set(p2.PRIVACY_NOTICE), set(p2.FEATURES))
        for feature in p2.FEATURES:
            self.assertEqual(set(p2.PRIVACY_NOTICE[feature]), set(p2.LANGUAGES))
            self.assertEqual(len({p2.privacy_notice(feature, lang) for lang in p2.LANGUAGES}), 8)
            self.assertTrue(all(len(p2.privacy_notice(feature, lang)) > 40 for lang in p2.LANGUAGES))
        self.assertEqual(p2.privacy_notice("plates", "xx"), p2.privacy_notice("plates", "en"))
        self.assertIn("GDPR", p2.privacy_notice("faces", "en"))
        self.assertIn("RGPD", p2.privacy_notice("faces", "pt"))
        with self.assertRaises(KeyError):
            p2.privacy_notice("eyes")

    def test_semantic_search_finds_by_words_and_can_forget(self):
        phase = p2.Phase2(p2.Phase2Settings(semantic_search=True, acknowledged=("semantic_search",)))
        phase.index("e1", "a person with a red jacket at the gate", {"camera": "gate"})
        phase.index("e2", "a white van in the driveway")
        phase.index("e3", "a cat on the wall")
        found = phase.search("red jacket person")
        self.assertEqual((found[0]["id"], found[0]["meta"], found[0]["evidence"]), ("e1", {"camera": "gate"}, "simulator"))
        self.assertEqual([r["id"] for r in phase.search("van driveway", limit=1)], ["e2"])
        self.assertEqual(phase.search("zebra"), [])
        self.assertEqual(phase.forget_index(ADMIN), 3)
        self.assertEqual(phase.search("person"), [])

    def test_plates_are_read_only_when_on_and_well_formed(self):
        script = {self.BOX: ("1234 abc", 0.9), (0, 0, 0.5, 0.5): ("???", 0.9), (0.5, 0.5, 0.9, 0.9): ("1234ABC", 0.3)}
        phase = p2.Phase2(p2.Phase2Settings(plates=True, acknowledged=("plates",)), plates=p2.SimulatedPlateReader(script))
        self.assertEqual(phase.read_plate(self.FRAME, self.BOX), {"plate": "1234 ABC", "confidence": 0.9, "evidence": "simulator", "authorized": False, "authorizes_action": False})
        self.assertIsNone(phase.read_plate(self.FRAME, (0, 0, 0.5, 0.5)))
        self.assertIsNone(phase.read_plate(self.FRAME, (0.5, 0.5, 0.9, 0.9)))
        self.assertIsNone(phase.read_plate(self.FRAME, (0.2, 0.2, 0.3, 0.3)))

    def test_only_an_enrolled_person_with_consent_can_be_named(self):
        script = {self.BOX: ("ana", 0.95), (0.5, 0.5, 0.6, 0.6): ("stranger", 0.99), (0.7, 0.7, 0.8, 0.8): ("ana", 0.2)}
        phase = p2.Phase2(p2.Phase2Settings(faces=True, acknowledged=("faces",)), faces=p2.SimulatedFaceMatcher(script))
        with self.assertRaises(p2.FeatureDisabled):
            phase.enrol("ana", [1.0], False, ADMIN)
        self.assertIsNone(phase.match_face(self.FRAME, self.BOX))
        phase.enrol("ana", [1.0, 0.0], True, ADMIN)
        self.assertEqual(phase.match_face(self.FRAME, self.BOX)["person"], "ana")
        self.assertIsNone(phase.match_face(self.FRAME, (0.5, 0.5, 0.6, 0.6)))        # not enrolled: never named
        self.assertIsNone(phase.match_face(self.FRAME, (0.7, 0.7, 0.8, 0.8)))        # not sure enough
        self.assertTrue(phase.unenrol("ana", ADMIN))
        self.assertFalse(phase.unenrol("ana", ADMIN))
        self.assertIsNone(phase.match_face(self.FRAME, self.BOX))


class Phase2PrivacyTests(unittest.TestCase):
    FRAME = Frame(2, 2, bytes(4))
    BOX = (0.1, 0.1, 0.3, 0.3)
    DAY = 86400.0

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.now = 1_000_000.0
        self.dir = Path(self.tmp.name)

    def clock(self):
        return self.now

    def settings(self, **extra):
        return p2.Phase2Settings(True, True, True, p2.FEATURES, **extra)

    def stored(self, **extra):
        paths = {"audit_file": str(self.dir / "audit.log"), "vault_file": str(self.dir / "vault.bin"), "key_file": str(self.dir / "vault.key")}
        paths.update(extra)
        return p2.Phase2(self.settings(**paths), clock=self.clock,
                         plates=p2.SimulatedPlateReader({self.BOX: ("1234 ABC", 0.9)}), faces=p2.SimulatedFaceMatcher({self.BOX: ("ana", 0.9)}))

    def test_settings_accept_retention_and_paths_and_refuse_a_vault_without_key(self):
        parsed, errors = p2.parse_phase2_settings({"retention_days": 7, "audit_file": "a.log", "vault_file": "v.bin", "key_file": "k"})
        self.assertEqual((errors, parsed.retention_days, parsed.vault_file), ([], 7, "v.bin"))
        self.assertEqual(p2.parse_phase2_settings({})[0].retention_days, 30)
        for raw in ({"retention_days": 0}, {"retention_days": True}, {"retention_days": 4000}, {"retention_days": "7"}, {"vault_file": "v.bin"}, {"audit_file": 5}, {"key_file": " k"}):
            self.assertIsNone(p2.parse_phase2_settings(raw)[0], raw)

    def test_the_confirmation_exists_in_eight_languages_and_enabling_needs_it_and_an_admin(self):
        self.assertEqual(set(p2.CONFIRMATION), set(p2.LANGUAGES))
        self.assertEqual(len(set(p2.CONFIRMATION.values())), 8)
        self.assertEqual(p2.confirmation_text("xx"), p2.confirmation_text("en"))
        phase = p2.Phase2(p2.Phase2Settings(), clock=self.clock)
        with self.assertRaises(p2.PermissionDenied):
            phase.enable(p2.Actor("guest", "operator"), "faces", True)
        with self.assertRaises(p2.FeatureDisabled):
            phase.enable(ADMIN, "faces", False)
        with self.assertRaises(KeyError):
            phase.enable(ADMIN, "eyes", True)
        self.assertFalse(phase.settings.enabled("faces"))
        self.assertTrue(phase.enable(ADMIN, "faces", True).enabled("faces"))
        self.assertFalse(phase.settings.enabled("plates"))
        self.assertFalse(phase.disable(ADMIN, "faces").enabled("faces"))
        with self.assertRaises(p2.PermissionDenied):
            phase.disable(None, "faces")
        with self.assertRaises(KeyError):
            phase.disable(ADMIN, "eyes")
        self.assertEqual([e["result"] for e in phase.audit.entries()], ["denied", "not-confirmed", "ok", "ok", "denied"])

    def test_only_the_administrator_manages_lists_exports_and_erases(self):
        phase = self.stored()
        operator = p2.Actor("guard", "operator")
        calls = (lambda a: phase.allow_plate(a, "1234 ABC"), lambda a: phase.disallow_plate(a, "1234 ABC"), lambda a: phase.allowed_plates(a), lambda a: phase.enrol("ana", [1.0], True, a),
                 lambda a: phase.unenrol("ana", a), lambda a: phase.forget_index(a), lambda a: phase.export_subject(a, "ana"), lambda a: phase.erase_subject(a, "ana"),
                 lambda a: phase.erase_everything(a))
        for call in calls:
            for actor in (None, operator, p2.SERVICE):
                with self.assertRaises(p2.PermissionDenied):
                    call(actor)
        self.assertEqual(sum(e["result"] == "denied" for e in phase.audit.entries()), len(calls) * 3)

    def test_the_authorised_vehicles_are_listed_by_the_admin_and_marked_on_reads(self):
        phase = self.stored()
        self.assertFalse(phase.read_plate(self.FRAME, self.BOX)["authorized"])
        phase.allow_plate(ADMIN, "1234-abc", "van")
        result = phase.read_plate(self.FRAME, self.BOX)
        self.assertEqual((result["authorized"], result["authorizes_action"]), (True, False))
        self.assertEqual(phase.allowed_plates(ADMIN), {"1234ABC": "van"})
        with self.assertRaises(ValueError):
            phase.allow_plate(ADMIN, "???")
        self.assertTrue(phase.disallow_plate(ADMIN, "1234 ABC"))
        self.assertFalse(phase.disallow_plate(ADMIN, "1234 ABC"))
        self.assertFalse(phase.read_plate(self.FRAME, self.BOX)["authorized"])

    def test_the_vault_is_encrypted_and_survives_a_restart(self):
        phase = self.stored()
        phase.enrol("ana", [0.25, 0.75], True, ADMIN)
        phase.allow_plate(ADMIN, "1234 ABC")
        phase.index("e1", "a person with a red jacket", {"subject": "ana"})
        phase.read_plate(self.FRAME, self.BOX, camera="gate")
        raw = (self.dir / "vault.bin").read_bytes()
        for secret in (b"ana", b"1234", b"red jacket", b"gate", b"0.25"):
            self.assertNotIn(secret, raw)
        self.assertEqual(len((self.dir / "vault.key").read_bytes()), 32)
        again = self.stored()
        self.assertEqual(again.export_subject(ADMIN, "ana")["enrolled"], True)
        self.assertEqual(again.export_subject(ADMIN, "1234ABC")["sightings"][0]["camera"], "gate")
        self.assertEqual(again.search("red jacket")[0]["id"], "e1")

    def test_a_wrong_key_or_a_changed_vault_does_not_open(self):
        phase = self.stored()
        phase.enrol("ana", [1.0], True, ADMIN)
        vault = self.dir / "vault.bin"
        good = vault.read_bytes()
        with self.assertRaises(p2.VaultError):
            p2.Phase2(self.settings(vault_file=str(vault), key_file=str(self.dir / "other.key")), clock=self.clock)
        changed = bytearray(good)
        changed[20] ^= 1
        vault.write_bytes(bytes(changed))
        with self.assertRaises(p2.VaultError):
            self.stored()
        vault.write_bytes(b"short")
        with self.assertRaises(p2.VaultError):
            self.stored()
        (self.dir / "bad.key").write_bytes(b"x")
        with self.assertRaises(p2.VaultError):
            p2.load_key(str(self.dir / "bad.key"))
        with self.assertRaises(p2.VaultError):
            p2.Phase2(self.settings(vault_file=str(vault)), clock=self.clock)       # a vault with no key

    def test_a_vault_with_the_right_key_but_odd_content_is_refused(self):
        key = p2.load_key(str(self.dir / "vault.key"))
        (self.dir / "vault.bin").write_bytes(p2.seal(key, b'{"index": 5}'))
        with self.assertRaises(p2.VaultError):
            self.stored()

    def test_seal_and_unseal_properties(self):
        rng = random.Random(7)
        key = bytes(rng.randrange(256) for _ in range(32))
        for size in (0, 1, 31, 32, 33, 1000):
            plain = bytes(rng.randrange(256) for _ in range(size))
            sealed = p2.seal(key, plain)
            self.assertEqual(p2.unseal(key, sealed), plain)
            self.assertNotEqual(p2.seal(key, plain), sealed)                 # a new nonce every time
            if size > 8:
                self.assertNotIn(plain[:8], sealed)
        self.assertEqual(p2.seal(key, b"abc", nonce=bytes(16)), p2.seal(key, b"abc", nonce=bytes(16)))
        with self.assertRaises(p2.VaultError):
            p2.unseal(bytes(32), p2.seal(key, b"abc"))

    def test_retention_erases_old_sightings_and_index_entries_but_not_the_enrolled(self):
        phase = self.stored(retention_days=2)
        phase.enrol("ana", [1.0], True, ADMIN)
        phase.index("old", "a red van")
        phase.read_plate(self.FRAME, self.BOX)
        self.now += 1 * self.DAY
        phase.index("new", "a red bicycle")
        self.now += 1.5 * self.DAY                                           # "old" is 2.5 days old, "new" is 1.5
        self.assertEqual([r["id"] for r in phase.search("red")], ["new"])
        self.assertEqual(phase.export_subject(ADMIN, "1234ABC")["sightings"], [])
        self.assertTrue(phase.export_subject(ADMIN, "ana")["enrolled"])
        self.assertEqual(phase.purge(), {"index": 0, "sightings": 0})
        self.now += 5 * self.DAY
        self.assertEqual(phase.purge(), {"index": 1, "sightings": 0})
        self.assertIn("retention-purge", [e["action"] for e in phase.audit.entries()])

    def test_export_and_erase_on_request(self):
        phase = self.stored()
        phase.enrol("ana", [0.5], True, ADMIN)
        phase.allow_plate(ADMIN, "1234 ABC", "van")
        phase.read_plate(self.FRAME, self.BOX, camera="gate")
        phase.index("e1", "ana at the gate", {"subject": "ana"})
        data = phase.export_subject(ADMIN, "ana")
        self.assertEqual((data["enrolled"], data["index_entries"], data["evidence"]), (True, ["e1"], "simulator"))
        self.assertNotIn("0.5", json.dumps(data))                            # the biometric template is never handed out
        self.assertEqual(phase.erase_subject(ADMIN, "ana"), {"enrolled": 1, "authorised_vehicle": 0, "sightings": 0, "index_entries": 1})
        self.assertEqual(phase.erase_subject(ADMIN, "1234 ABC"), {"enrolled": 0, "authorised_vehicle": 1, "sightings": 1, "index_entries": 0})
        self.assertEqual(phase.export_subject(ADMIN, "ana")["enrolled"], False)
        self.assertEqual(self.stored().export_subject(ADMIN, "1234ABC")["sightings"], [])    # also gone from the vault
        phase.enrol("bea", [1.0], True, ADMIN)
        phase.erase_everything(ADMIN)
        self.assertFalse((self.dir / "vault.bin").exists())
        self.assertFalse(phase.export_subject(ADMIN, "bea")["enrolled"])

    def test_the_audit_log_chains_every_use_and_holds_no_personal_data(self):
        phase = self.stored()
        phase.enrol("ana", [1.0], True, ADMIN)
        phase.allow_plate(ADMIN, "1234 ABC")
        phase.read_plate(self.FRAME, self.BOX)
        phase.match_face(self.FRAME, self.BOX)
        phase.index("e1", "a secret description")
        phase.search("secret description")
        phase.export_subject(ADMIN, "ana")
        text = (self.dir / "audit.log").read_text(encoding="utf-8")
        for private in ('"ana"', "1234", "ABC", "secret"):
            self.assertNotIn(private, text)
        entries = phase.audit.entries()
        self.assertEqual([e["action"] for e in entries], ["enrol", "allow-plate", "read-plate", "match-face", "index", "search", "export"])
        self.assertEqual([e["seq"] for e in entries], list(range(1, 8)))
        self.assertIsNone(phase.audit.verify())
        self.assertIsNone(p2.AuditLog(str(self.dir / "audit.log"), self.clock, (self.dir / "vault.key").read_bytes()).verify())    # reopened from the file
        for tamper in (lambda ls: ls.pop(2), lambda ls: ls.__setitem__(1, ls[1].replace("allow-plate", "nothing")), lambda ls: ls.__setitem__(0, "not json"), lambda ls: ls.reverse(),
                       lambda ls: ls.__setitem__(0, "[]")):
            lines = list(phase.audit.lines)
            tamper(lines)
            log = p2.AuditLog()
            log.lines = lines
            self.assertIsNotNone(log.verify())

    def test_actors_are_checked(self):
        for name, role in (("", "admin"), ("x", "root")):
            with self.assertRaises(ValueError):
                p2.Actor(name, role)

    def test_scripted_readers_come_from_made_up_readings(self):
        plates, faces = p2.scripted_readers({"plates": [{"box": [0.1, 0.1, 0.3, 0.3], "text": "9999 ZZZ", "confidence": 0.8}],
                                             "faces": [{"box": [0.5, 0.5, 0.6, 0.6], "person": "demo", "confidence": 0.9}]})
        self.assertEqual(plates.read(self.FRAME, self.BOX), ("9999 ZZZ", 0.8))
        self.assertIsNone(faces.match(self.FRAME, (0.5, 0.5, 0.6, 0.6), {}))          # not enrolled: nobody
        self.assertEqual(faces.match(self.FRAME, (0.5, 0.5, 0.6, 0.6), {"demo": [1.0]}), ("demo", 0.9))
        path = self.dir / "script.json"
        path.write_text(json.dumps({"plates": [{"box": [0, 0, 1, 1], "text": "1111 AAA", "confidence": 0.7}]}), encoding="utf-8")
        self.assertEqual(p2.load_scripted_readers(str(path))[0].read(self.FRAME, (0, 0, 1, 1)), ("1111 AAA", 0.7))
        for bad in ([], {"x": 1}, {"plates": [{"box": [1, 2, 3], "text": "a", "confidence": 1}]}, {"plates": [{"box": [0, 0, 1, 1], "text": 5, "confidence": 1}]},
                    {"faces": [{"box": [0, 0, 1, True], "person": "a", "confidence": 1}]}, {"faces": [{"box": [0, 0, 1, 1], "person": "a", "confidence": True}]}, {"faces": ["x"]}):
            with self.assertRaises(ValueError, msg=bad):
                p2.scripted_readers(bad)

    def test_nothing_in_the_second_phase_can_reach_the_network(self):
        source = Path(p2.__file__).read_text(encoding="utf-8")
        for module in ("socket", "urllib", "http", "requests", "ssl", "smtplib", "ftplib", "subprocess", "webbrowser"):
            self.assertNotRegex(source, rf"(?m)^\s*(import|from)\s+{module}\b", module)


if __name__ == "__main__":
    unittest.main()
