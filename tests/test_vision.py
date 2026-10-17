import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from armor_vision.cli import EXAMPLE_CONFIG, main, simulate
from armor_vision.config import parse_config
from armor_vision.detector import DetectorUnavailable, ScriptedDetector, load_detector
from armor_vision.geometry import iou, point_in_polygon, valid_box, valid_polygon
from armor_vision.motion import GRID_COLUMNS, GRID_ROWS, Frame, moved_cells, regions
from armor_vision.pipeline import Pipeline
from armor_vision.tracker import Detection, Tracker

SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def config_with(zone_extra=None, camera_extra=None, profiles=None):
    zone = {"id": "z", "name": "Zone", "points": SQUARE}
    zone.update(zone_extra or {})
    camera = {"zones": [zone]}
    camera.update(camera_extra or {})
    config, errors = parse_config({"cameras": {"cam": camera}, "profiles": profiles or {}})
    assert config is not None, errors
    return config


def person(x=0.4, y=0.5):
    return Detection("person", 0.9, (x, y - 0.2, x + 0.05, y))


def grey(value, width=160, height=90):
    return Frame(width, height, bytes([value]) * (width * height))


class GeometryTests(unittest.TestCase):
    def test_point_in_polygon_inside_outside_and_edge(self):
        self.assertTrue(point_in_polygon((0.5, 0.5), SQUARE))
        self.assertFalse(point_in_polygon((0.9, 0.5), SQUARE))
        self.assertTrue(point_in_polygon((0.2, 0.5), SQUARE))   # on the edge
        self.assertTrue(point_in_polygon((0.8, 0.8), SQUARE))   # on a corner

    def test_concave_polygon(self):
        letter_l = [[0.1, 0.1], [0.3, 0.1], [0.3, 0.6], [0.9, 0.6], [0.9, 0.9], [0.1, 0.9]]
        self.assertTrue(point_in_polygon((0.2, 0.3), letter_l))
        self.assertFalse(point_in_polygon((0.6, 0.3), letter_l))
        self.assertTrue(point_in_polygon((0.6, 0.8), letter_l))

    def test_polygon_validation(self):
        self.assertIsNone(valid_polygon(SQUARE))
        self.assertIn("at least 3", valid_polygon([[0, 0], [1, 1]]))
        self.assertIn("between 0 and 1", valid_polygon([[0, 0], [2, 0], [1, 1]]))
        self.assertIn("no area", valid_polygon([[0, 0], [0.5, 0.5], [1, 1]]))
        self.assertIn("numbers", valid_polygon([[0, 0], ["a", 0], [1, 1]]))
        self.assertIn("[x, y]", valid_polygon([[0, 0], [1], [1, 1]]))
        self.assertIn("numbers", valid_polygon([[0, 0], [True, 0], [1, 1]]))

    def test_iou_and_box_validation(self):
        self.assertEqual(iou((0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1)), 0.0)
        self.assertAlmostEqual(iou((0, 0, 0.5, 0.5), (0, 0, 0.5, 0.5)), 1.0)
        self.assertTrue(valid_box((0.1, 0.1, 0.2, 0.2)))
        self.assertFalse(valid_box((0.3, 0.1, 0.2, 0.2)))
        self.assertFalse(valid_box((0.1, 0.1, 1.2, 0.2)))
        self.assertFalse(valid_box((0.1, 0.1, 0.2)))
        self.assertFalse(valid_box((0.1, 0.1, True, 0.2)))


class ConfigTests(unittest.TestCase):
    def test_example_is_valid(self):
        config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
        self.assertEqual(errors, [])
        self.assertEqual(len(config.cameras["cam-front"].zones), 2)

    def test_any_error_gives_no_config(self):
        bad = copy.deepcopy(EXAMPLE_CONFIG)
        bad["cameras"]["cam-front"]["zones"][0]["kind"] = "panic"
        config, errors = parse_config(bad)
        self.assertIsNone(config)
        self.assertTrue(any("kind" in e for e in errors))

    def test_unknown_fields_are_rejected_everywhere(self):
        for path in (("extra",), ("cameras", "cam-front", "extra"), ("cameras", "cam-front", "zones", 0, "extra")):
            bad = copy.deepcopy(EXAMPLE_CONFIG)
            target = bad
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = 1
            config, errors = parse_config(bad)
            self.assertIsNone(config, path)
            self.assertTrue(any("unknown" in e for e in errors), path)

    def test_duplicate_zone_ids_and_profile_with_missing_zone(self):
        bad = copy.deepcopy(EXAMPLE_CONFIG)
        bad["cameras"]["cam-front"]["zones"][1]["id"] = "drive"
        _, errors = parse_config(bad)
        self.assertTrue(any("used twice" in e for e in errors))
        bad = copy.deepcopy(EXAMPLE_CONFIG)
        bad["profiles"]["away"].append("ghost")
        _, errors = parse_config(bad)
        self.assertTrue(any("ghost" in e for e in errors))

    def test_numbers_are_checked(self):
        for extra in ({"min_frames": 0}, {"min_frames": 1.5}, {"min_seconds": -1}, {"labels": "person"}, {"min_frames": True}):
            config, errors = parse_config({"cameras": {"c": {"zones": [{"id": "z", "points": SQUARE, **extra}]}}})
            self.assertIsNone(config, extra)
        for extra in ({"motion_threshold": 0}, {"motion_threshold": 300}, {"motion_min_cells": 0}):
            config, _ = parse_config({"cameras": {"c": extra}})
            self.assertIsNone(config, extra)

    def test_shapes_are_checked(self):
        for raw in ([], {"cameras": []}, {"cameras": {"c": 1}}, {"cameras": {"c": {"zones": [1]}}}, {"profiles": []},
                    {"profiles": {"away": "drive"}}, {"cameras": {"c": {"masks": [[[0, 0]]]}}}):
            config, errors = parse_config(raw)
            self.assertIsNone(config, raw)
            self.assertTrue(errors)


class MotionTests(unittest.TestCase):
    def test_identical_frames_have_no_motion(self):
        self.assertEqual(moved_cells(grey(10), grey(10), 25), set())

    def test_a_changed_block_is_found_and_boxed(self):
        base = bytearray(b"\x00" * (160 * 90))
        changed = bytearray(base)
        for y in range(0, 20):
            for x in range(0, 20):
                changed[y * 160 + x] = 200
        cells = moved_cells(Frame(160, 90, bytes(base)), Frame(160, 90, bytes(changed)), 25)
        self.assertEqual(cells, {(0, 0), (1, 0), (0, 1), (1, 1), (0, 2)} & cells)
        self.assertIn((0, 0), cells)
        box = regions(cells)[0]
        self.assertEqual((box[0], box[1]), (0.0, 0.0))

    def test_threshold_and_mask(self):
        small = moved_cells(grey(0), grey(20), 25)
        self.assertEqual(small, set())
        everything = moved_cells(grey(0), grey(100), 25)
        self.assertEqual(len(everything), GRID_COLUMNS * GRID_ROWS)
        masked = moved_cells(grey(0), grey(100), 25, masks=(tuple(map(tuple, SQUARE)),))
        self.assertLess(len(masked), len(everything))
        self.assertNotIn((GRID_COLUMNS // 2, GRID_ROWS // 2), masked)

    def test_regions_join_neighbours_only(self):
        boxes = regions({(0, 0), (1, 0), (5, 5)})
        self.assertEqual(len(boxes), 2)

    def test_frame_validation(self):
        with self.assertRaises(ValueError):
            Frame(2, 2, b"abc")
        with self.assertRaises(ValueError):
            moved_cells(grey(0, 16, 9), grey(0, 32, 18), 25)


class TrackerTests(unittest.TestCase):
    def test_same_object_keeps_its_id(self):
        tracker = Tracker()
        first = tracker.update(0.0, [person(0.40)])[0].track_id
        second = tracker.update(0.2, [person(0.41)])[0].track_id
        self.assertEqual(first, second)

    def test_two_objects_do_not_swap(self):
        tracker = Tracker()
        a, b = tracker.update(0.0, [person(0.2), person(0.7)])
        again = tracker.update(0.2, [person(0.21), person(0.71)])
        self.assertEqual([t.track_id for t in again], [a.track_id, b.track_id])

    def test_label_must_match(self):
        tracker = Tracker()
        tracker.update(0.0, [person()])
        track = tracker.update(0.2, [Detection("car", 0.9, person().box)])[0]
        self.assertEqual(track.track_id, 2)

    def test_lost_track_is_dropped_and_a_parked_one_is_remembered(self):
        tracker = Tracker()
        tracker.update(0.0, [person(0.3)])
        tracker.update(5.0, [])
        self.assertEqual(tracker.tracks, [])
        car = Detection("car", 0.9, (0.5, 0.3, 0.7, 0.5))
        for step in range(0, 20):
            tracker.update(step * 0.2, [car])
        self.assertTrue(tracker.tracks[0].stationary)
        tracker.update(60.0, [])
        self.assertEqual(len(tracker.tracks), 1)

    def test_moving_object_is_not_stationary(self):
        tracker = Tracker()
        for step in range(0, 30):
            track = tracker.update(step * 0.2, [person(0.3 + step * 0.01)])[0]
        self.assertFalse(track.stationary)


class RuleTests(unittest.TestCase):
    def run_steps(self, config, make, steps, mode=None, dt=0.2):
        pipeline = Pipeline(config, mode=mode)
        events = []
        for step in range(steps):
            events += pipeline.process_detections("cam", step * dt, make(step))
        return events, pipeline

    def test_inertia_needs_frames_and_seconds(self):
        config = config_with({"min_frames": 3, "min_seconds": 1.0})
        events, _ = self.run_steps(config, lambda s: [person(0.4 + s * 0.01)], 4)
        self.assertEqual(events, [])               # 4 frames but only 0.6 s
        events, _ = self.run_steps(config, lambda s: [person(0.4 + s * 0.01)], 8)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["timestamp"], 1.0)

    def test_fires_once_per_visit_and_again_after_leaving(self):
        config = config_with()

        path = [0.4, 0.4, 0.4, 0.55, 0.7, 0.85, 0.85, 0.7, 0.55]    # walks out of the zone (feet at 0.875, past the edge at 0.8) and back in

        def route(step):
            return [person(path[step])]
        events, _ = self.run_steps(config, route, 9)
        self.assertEqual(len(events), 2)

    def test_somebody_who_comes_in_and_stands_still_is_caught_by_a_long_inertia(self):
        config = config_with({"min_seconds": 10.0})
        events, _ = self.run_steps(config, lambda s: [person(0.4)], 100, dt=0.2)   # 20 s, still from the first frame on
        self.assertEqual(len(events), 1, "somebody who is there from the first frame and never moves is loitering too: the zone fires when its inertia is over")
        path = [0.3 + min(s, 5) * 0.02 for s in range(100)]
        events, _ = self.run_steps(config, lambda s: [person(path[s])], 100, dt=0.2)  # walks in for a second, then stops
        self.assertEqual(len(events), 1)
        self.assertGreaterEqual(events[0]["timestamp"], 10.0)

    def test_a_frame_the_detector_misses_does_not_open_a_new_visit(self):
        config = config_with()
        events, _ = self.run_steps(config, lambda s: [] if s % 5 == 4 else [person(0.4 + s * 0.005)], 40)
        self.assertEqual(len(events), 1)
        self.assertEqual({e["track_id"] for e in events}, {1})

    def test_a_quick_walker_keeps_the_same_track(self):
        tracker = Tracker()
        ids = set()
        for step in range(8):
            seen = tracker.update(step * 1.0, [Detection("person", 0.9, (0.1 + step * 0.08, 0.3, 0.15 + step * 0.08, 0.5))])
            ids |= {track.track_id for track in seen}
        self.assertEqual(ids, {1})

    def test_disarmed_does_not_watch_alert_zones_and_nan_is_refused(self):
        alert = config_with({"kind": "alert"})
        detection = config_with({"kind": "detection"})
        self.assertEqual(len(self.run_steps(alert, lambda s: [person()], 3, mode="armed")[0]), 1)
        self.assertEqual(self.run_steps(alert, lambda s: [person()], 3, mode="disarmed")[0], [])
        self.assertEqual(len(self.run_steps(detection, lambda s: [person()], 3, mode="disarmed")[0]), 1)
        _, errors = parse_config({"cameras": {"cam": {"zones": [{"id": "z", "points": SQUARE, "min_seconds": float("nan")}]}}})
        self.assertTrue(errors)
        _, errors = parse_config({"cameras": {"cam": {"zones": 5, "masks": "x"}}})
        self.assertTrue(any("zones must be a list" in e for e in errors) and any("masks must be a list" in e for e in errors))
        self.assertIsNotNone(valid_polygon([[0.1, 0.1], [0.9, 0.9], [0.9, 0.1], [0.1, 0.9]]), "a bow tie is not a zone")
        self.assertIsNotNone(valid_polygon([[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]), "three points on a line have no area")
        pipeline = Pipeline(detection)
        self.assertEqual(pipeline.process_detections("cam", 0.0, [Detection("person", float("nan"), (0.4, 0.3, 0.45, 0.5))]), [])
        self.assertEqual(pipeline.stats.dropped_detections, 1)

    def test_label_filter(self):
        config = config_with({"labels": ["person"]})
        events, _ = self.run_steps(config, lambda s: [Detection("cat", 0.9, (0.4, 0.3, 0.5, 0.5))], 5)
        self.assertEqual(events, [])

    def test_only_the_feet_decide(self):
        config = config_with()
        high = Detection("person", 0.9, (0.4, 0.0, 0.5, 0.1))      # head high above the zone, feet at 0.1
        events, _ = self.run_steps(config, lambda s: [high], 3)
        self.assertEqual(events, [])

    def test_mask_drops_detections(self):
        config = config_with(camera_extra={"masks": [[[0.3, 0.3], [0.6, 0.3], [0.6, 0.6], [0.3, 0.6]]]})
        events, pipeline = self.run_steps(config, lambda s: [person(0.4, 0.5)], 5)
        self.assertEqual(events, [])
        self.assertEqual(pipeline.stats.dropped_detections, 5)

    def test_malformed_boxes_are_dropped_not_fatal(self):
        config = config_with()
        events, pipeline = self.run_steps(config, lambda s: [Detection("person", 0.9, (0.5, 0.5, 0.4, 0.4))], 3)
        self.assertEqual(events, [])
        self.assertEqual(pipeline.stats.dropped_detections, 3)

    def test_stationary_object_makes_no_new_events(self):
        config = config_with({"labels": ["car"], "kind": "detection"})
        car = Detection("car", 0.9, (0.4, 0.3, 0.6, 0.5))
        events, _ = self.run_steps(config, lambda s: [car], 40)
        self.assertEqual(len(events), 1)

    def test_profiles_choose_what_is_watched(self):
        config = config_with(profiles={"home": [], "away": ["z"]})
        make = lambda s: [person(0.4 + s * 0.01)]
        self.assertEqual(self.run_steps(config, make, 3, mode="home")[0], [])
        self.assertEqual(len(self.run_steps(config, make, 3, mode="away")[0]), 1)

    def test_unknown_mode_watches_everything(self):
        config = config_with(profiles={"home": []})
        events, _ = self.run_steps(config, lambda s: [person()], 3, mode="holiday")
        self.assertEqual(len(events), 1)

    def test_event_never_authorizes_action_and_carries_the_zone_kind(self):
        config = config_with({"kind": "detection"})
        events, _ = self.run_steps(config, lambda s: [person()], 2)
        self.assertEqual(events[0]["type"], "detection")
        self.assertIs(events[0]["authorizes_action"], False)
        self.assertEqual(events[0]["schema"], "armor.vision.event/v1")
        json.dumps(events[0])

    def test_unknown_camera(self):
        pipeline = Pipeline(config_with())
        with self.assertRaises(KeyError):
            pipeline.process_detections("nope", 0.0, [])


class PipelineMotionTests(unittest.TestCase):
    def test_detector_runs_only_when_something_moves(self):
        config = config_with()
        detector = ScriptedDetector(lambda frame, hints: [person()])
        pipeline = Pipeline(config, detector)
        still = grey(10)
        self.assertEqual(pipeline.process_frame("cam", 0.0, still), [])      # reference only
        self.assertEqual(pipeline.process_frame("cam", 0.2, still), [])
        self.assertEqual(detector.calls, 0)
        for step in range(1, 7):
            pipeline.process_frame("cam", step * 0.2 + 0.2, grey(10 + 60 * (step % 2)))
        self.assertGreaterEqual(detector.calls, 5)
        self.assertEqual(pipeline.stats.frames, 8)
        self.assertGreaterEqual(pipeline.stats.events, 1)
        self.assertEqual(pipeline.stats.skipped_by_motion + pipeline.stats.detector_calls, 8)

    def test_motion_under_a_mask_does_not_wake_the_detector(self):
        full = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
        config = config_with(camera_extra={"masks": [full]})
        detector = ScriptedDetector(lambda f, h: [person()])
        pipeline = Pipeline(config, detector)
        pipeline.process_frame("cam", 0.0, grey(0))
        pipeline.process_frame("cam", 0.2, grey(200))
        self.assertEqual(detector.calls, 0)

    def test_process_frame_needs_a_detector_and_a_known_camera(self):
        with self.assertRaises(RuntimeError):
            Pipeline(config_with()).process_frame("cam", 0.0, grey(0))
        with self.assertRaises(KeyError):
            Pipeline(config_with(), ScriptedDetector(lambda f, h: [])).process_frame("x", 0.0, grey(0))

    def test_real_detector_is_honestly_unavailable(self):
        for name in ("tensorrt", "yolo"):
            with self.assertRaises(DetectorUnavailable):
                load_detector(name)


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_simulation_result(self):
        config, _ = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
        events, stats = simulate(config, "away")
        kinds = sorted((e["zone_id"], e["type"], e["label"]) for e in events)
        self.assertEqual(kinds, [("drive", "alert", "person"), ("street", "detection", "car")])
        self.assertEqual(stats["dropped_detections"], 41)    # the person behind the tree, every picture
        events, _ = simulate(config, "home")
        self.assertEqual([e["zone_id"] for e in events], ["street"])

    def test_simulate_command_prints_json_lines(self):
        code, out, _ = self.run_cli("simulate", "--mode", "away")
        self.assertEqual(code, 0)
        lines = [json.loads(line) for line in out.splitlines()]
        self.assertEqual(lines[-1]["stats"]["events"], 2)

    def test_check_config(self):
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "good.json"
            good.write_text(json.dumps(EXAMPLE_CONFIG), encoding="utf-8")
            self.assertEqual(self.run_cli("check-config", str(good))[0], 0)
            bad = Path(folder) / "bad.json"
            bad.write_text(json.dumps({"cameras": {"c": {"zones": [{"id": "z", "points": [[0, 0]]}]}}}), encoding="utf-8")
            code, _, err = self.run_cli("check-config", str(bad))
            self.assertEqual(code, 1)
            self.assertIn("at least 3", err)
            broken = Path(folder) / "broken.json"
            broken.write_text("{", encoding="utf-8")
            self.assertEqual(self.run_cli("check-config", str(broken))[0], 2)
            self.assertEqual(self.run_cli("check-config", str(Path(folder) / "missing.json"))[0], 2)
            self.assertEqual(self.run_cli("simulate", "--config", str(bad))[0], 1)
            self.assertEqual(self.run_cli("simulate", "--config", str(broken))[0], 2)


if __name__ == "__main__":
    unittest.main()
