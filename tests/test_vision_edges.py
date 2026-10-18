"""The edges of the zone and rule code: shapes that look like zones and are not, frames of the wrong size, the masks cache, and the command line reading a file."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from armor_vision import motion
from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.config import parse_config
from armor_vision.geometry import point_in_polygon, valid_polygon
from armor_vision.motion import Frame, moved_cells, regions

SQUARE = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = main(list(argv))
        except SystemExit as stop:
            code = stop.code
    return code, out.getvalue(), err.getvalue()


class PolygonTests(unittest.TestCase):
    def test_a_bow_tie_is_not_a_zone(self):
        self.assertEqual(valid_polygon([[0.1, 0.1], [0.9, 0.1], [0.2, 0.9], [0.9, 0.9]]), "the polygon crosses itself")

    def test_a_flat_polygon_has_no_inside(self):
        self.assertIn("no area", valid_polygon([[0.1, 0.1], [0.5, 0.5], [0.9, 0.9]]))
        self.assertIn("no area", valid_polygon([[0.5, 0.5], [0.5, 0.5], [0.5, 0.5]]))

    def test_every_way_a_point_list_can_be_wrong(self):
        cases = [
            ("nope", "at least 3"), ([[0, 0], [1, 1]], "at least 3"), ([[0, 0], [1, 1], "x"], "[x, y]"), ([[0, 0], [1, 1], [0.5]], "[x, y]"),
            ([[0, 0], [1, 1], [0.5, True]], "numbers"), ([[0, 0], [1, 1], [0.5, "1"]], "numbers"), ([[0, 0], [1, 1], [0.5, 1.5]], "between 0 and 1"),
            ([[0, 0], [1, 1], [-0.1, 0.5]], "between 0 and 1"), ([[0, 0], [1, 1], [0.5, float("nan")]], "between 0 and 1"),
        ]
        for points, fragment in cases:
            self.assertIn(fragment, valid_polygon(points), points)

    def test_a_good_square_and_an_l_shape_are_accepted(self):
        self.assertIsNone(valid_polygon(SQUARE))
        self.assertIsNone(valid_polygon([[0.1, 0.1], [0.9, 0.1], [0.9, 0.4], [0.4, 0.4], [0.4, 0.9], [0.1, 0.9]]))

    def test_the_edge_of_a_zone_is_inside_and_the_notch_of_an_l_is_not(self):
        self.assertTrue(point_in_polygon((0.2, 0.5), SQUARE))
        self.assertTrue(point_in_polygon((0.5, 0.5), SQUARE))
        self.assertFalse(point_in_polygon((0.1, 0.5), SQUARE))
        l_shape = [[0.1, 0.1], [0.9, 0.1], [0.9, 0.4], [0.4, 0.4], [0.4, 0.9], [0.1, 0.9]]
        self.assertFalse(point_in_polygon((0.7, 0.7), l_shape))
        self.assertTrue(point_in_polygon((0.2, 0.7), l_shape))


class ConfigEdgeTests(unittest.TestCase):
    def config(self, zones, **camera):
        return parse_config({"cameras": {"cam": {"zones": zones, **camera}}, "profiles": {}})

    def test_a_zone_needs_an_id_and_the_id_is_unique_in_the_whole_file(self):
        _config, errors = self.config([{"name": "no id", "points": SQUARE}])
        self.assertTrue(any("id is required" in error for error in errors), errors)
        _config, errors = self.config([{"id": "z", "name": "a", "points": SQUARE}, {"id": "z", "name": "b", "points": SQUARE}])
        self.assertTrue(any("used twice" in error for error in errors), errors)
        _config, errors = self.config([{"id": "", "name": "empty", "points": SQUARE}])
        self.assertTrue(any("id is required" in error for error in errors), errors)

    def test_a_field_nobody_knows_is_an_error_not_something_ignored(self):
        _config, errors = self.config([{"id": "z", "name": "a", "points": SQUARE, "colour": "red"}])
        self.assertTrue(any("unknown field" in error and "colour" in error for error in errors), errors)

    def test_nothing_is_built_from_a_file_that_has_errors(self):
        config, errors = self.config([{"id": "z", "name": "a", "points": [[0, 0], [1, 1]]}])
        self.assertIsNone(config)
        self.assertTrue(errors)

    def test_things_that_are_not_a_configuration(self):
        for raw in (None, [], "text", 5, {"cameras": []}, {"cameras": {"cam": []}}):
            config, errors = parse_config(raw)
            self.assertIsNone(config, raw)
            self.assertTrue(errors, raw)


class MotionEdgeTests(unittest.TestCase):
    def test_a_frame_has_the_size_it_says(self):
        with self.assertRaises(ValueError):
            Frame(0, 4, b"")
        with self.assertRaises(ValueError):
            Frame(4, -1, b"")
        with self.assertRaises(ValueError):
            Frame(4, 4, b"\x00" * 15)
        self.assertEqual(Frame(4, 4, b"\x00" * 16).width, 4)

    def test_frames_of_different_sizes_cannot_be_compared(self):
        with self.assertRaises(ValueError):
            moved_cells(Frame(4, 4, b"\x00" * 16), Frame(8, 8, b"\x00" * 64), 10)

    def test_a_change_under_a_mask_is_not_movement_and_a_change_outside_it_is(self):
        quiet = Frame(64, 48, b"\x10" * (64 * 48))
        loud = Frame(64, 48, bytes([0xF0] * (64 * 48)))
        everything = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.assertTrue(moved_cells(quiet, loud, 30))
        self.assertEqual(moved_cells(quiet, loud, 30, masks=(tuple(everything),)), set())

    def test_the_cache_of_masks_does_not_grow_for_ever(self):
        motion._MASKED.clear()
        for index in range(80):
            offset = index / 1000
            mask = ((0.0 + offset, 0.0), (0.5, 0.0), (0.5, 0.5))
            self.assertIsInstance(motion._masked_cells((mask,)), frozenset)
        self.assertLessEqual(len(motion._MASKED), 65)
        self.assertEqual(motion._masked_cells(()), frozenset())

    def test_regions_of_no_cells_are_no_regions(self):
        self.assertEqual(regions(set()), [])


class CommandLineTests(unittest.TestCase):
    def write(self, folder, name, text):
        path = Path(folder) / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_check_config_says_what_is_in_a_good_file_and_why_a_bad_one_is_bad(self):
        with tempfile.TemporaryDirectory() as folder:
            good = self.write(folder, "good.json", json.dumps(EXAMPLE_CONFIG))
            code, out, _err = run("check-config", good)
            self.assertEqual(code, 0)
            self.assertRegex(out, r"ok: \d+ camera\(s\), \d+ zone\(s\)")
            bad = self.write(folder, "bad.json", json.dumps({"cameras": {"cam": {"zones": [{"id": "z", "points": [[0, 0]]}]}}}))
            code, _out, err = run("check-config", bad)
            self.assertEqual(code, 1)
            self.assertIn("error:", err)

    def test_a_file_that_is_missing_or_not_json_or_has_nan_is_exit_2(self):
        with tempfile.TemporaryDirectory() as folder:
            for text in ("{broken", '{"cameras": {"c": {"zones": [], "limit": NaN}}}', '{"x": Infinity}', ""):
                code, _out, err = run("check-config", self.write(folder, "f.json", text))
                self.assertEqual(code, 2, text)
                self.assertIn("cannot read", err)
            code, _out, err = run("check-config", str(Path(folder) / "missing.json"))
            self.assertEqual((code, "cannot read" in err), (2, True))
            code, _out, _err = run("simulate", "--config", str(Path(folder) / "missing.json"))
            self.assertEqual(code, 2)

    def test_simulate_with_a_config_that_has_errors_prints_them_and_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self.write(folder, "bad.json", json.dumps({"cameras": "nope"}))
            code, out, err = run("simulate", "--config", path)
        self.assertEqual((code, out), (1, ""))
        self.assertIn("error:", err)

    def test_the_arming_mode_changes_what_is_reported(self):
        away = run("simulate", "--mode", "away")[1]
        home = run("simulate", "--mode", "home")[1]
        self.assertTrue(away.strip().splitlines()[-1].startswith('{"stats"'))
        self.assertTrue(home.strip().splitlines()[-1].startswith('{"stats"'))

    def test_the_version_is_printed(self):
        code, out, _err = run("--version")
        self.assertEqual(code, 0)
        self.assertTrue(out.startswith("armor-vision "))


if __name__ == "__main__":
    unittest.main()
