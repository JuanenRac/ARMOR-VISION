import copy
import io
import json
import random
import struct
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from armor_vision.activity import ActivityDisabled, ActivityEngine, heatmap_route
from armor_vision.activity_config import ACTIVITY_EXAMPLE, HeatmapSettings, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.config import parse_config
from armor_vision.heatmap import Heatmap
from armor_vision.sources import FileSource, SourceError, SyntheticSource
from armor_vision.tracker import Detection


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity(**overrides):
    raw = copy.deepcopy(ACTIVITY_EXAMPLE)
    for key, value in overrides.items():
        raw[key].update(value) if isinstance(value, dict) else raw.__setitem__(key, value)
    config, errors = parse_activity_config(raw)
    assert config is not None, errors
    return config


def run_cli(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


def man(x, y, label="person"):
    return Detection(label, 0.9, (x, y - 0.2, x + 0.05, y))


class ConfigTests(unittest.TestCase):
    def test_default_is_off(self):
        config, errors = parse_activity_config({})
        self.assertEqual(errors, [])
        self.assertFalse(config.enabled)
        with self.assertRaises(ActivityDisabled):
            ActivityEngine(vision(), config)

    def test_example_is_valid_and_bad_values_fail_closed(self):
        self.assertEqual(parse_activity_config(ACTIVITY_EXAMPLE)[1], [])
        bad = [
            [],
            {"enabled": "yes"},
            {"nope": 1},
            {"heatmap": {"cols": 0}},
            {"heatmap": {"cols": 1000, "rows": 1000, "max_cells": 65536}},
            {"heatmap": {"max_cells": 70000}},
            {"heatmap": {"window_seconds": None, "half_life_seconds": 5}},
            {"heatmap": {"window_seconds": float("nan")}},
            {"heatmap": {"half_life_seconds": -1}},
            {"heatmap": {"slices": 1000}},
            {"heatmap": {"position": "head"}},
            {"heatmap": {"labels": [1]}},
            {"heatmap": []},
            {"events": {"dwell_seconds": -1}},
            {"events": {"loiter_radius": 2}},
            {"events": {"lines": [{"id": "l", "a": [0, 0], "b": [0, 0]}]}},
            {"events": {"lines": [{"id": "l", "a": [0, 0], "b": [2, 0]}]}},
            {"events": {"lines": [{"id": "l", "a": [0, 0], "b": [1, 0]}, {"id": "l", "a": [0, 1], "b": [1, 1]}]}},
            {"events": {"lines": [{"a": [0, 0], "b": [1, 0]}]}},
            {"events": {"lines": "x"}},
            {"events": {"bogus": 1}},
        ]
        for raw in bad:
            config, errors = parse_activity_config(raw)
            self.assertIsNone(config, raw)
            self.assertTrue(errors, raw)


class HeatmapTests(unittest.TestCase):
    def settings(self, **kw):
        base = dict(cols=8, rows=4, window_seconds=None, half_life_seconds=None, slices=10, max_cells=64, position="foot", labels=())
        base.update(kw)
        return HeatmapSettings(**base)

    def test_grid_edges_and_rejections(self):
        heat = Heatmap(self.settings())
        self.assertEqual(heat.cell_of((0.0, 0.0)), (0, 0))
        self.assertEqual(heat.cell_of((1.0, 1.0)), (7, 3))
        for bad in [(-0.01, 0.5), (0.5, 1.01), (float("nan"), 0.5), (float("inf"), 0.5)]:
            self.assertIsNone(heat.cell_of(bad))
        self.assertFalse(heat.add(float("nan"), (0.5, 0.5)))
        self.assertFalse(heat.add(0.0, (2.0, 0.5)))
        self.assertTrue(heat.add(0.0, (0.5, 0.5)))
        self.assertEqual((heat.accepted, heat.rejected), (1, 2))

    def test_property_sum_equals_accepted_and_nothing_outside(self):
        rng = random.Random(7)
        heat = Heatmap(self.settings(cols=13, rows=7, max_cells=91))
        accepted = 0
        for index in range(2000):
            point = (rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2))
            if heat.add(float(index), point):
                accepted += 1
        snap = heat.snapshot()
        self.assertEqual(snap.total, accepted)
        self.assertEqual(snap.accepted, accepted)
        self.assertEqual(snap.accepted + snap.rejected, 2000)
        self.assertEqual((len(snap.weights), {len(r) for r in snap.weights}), (7, {13}))
        self.assertTrue(all(w >= 0 for row in snap.weights for w in row))
        self.assertAlmostEqual(snap.maximum and max(max(r) for r in snap.normalized()), 1.0)

    def test_window_forgets_and_refuses_the_stale(self):
        heat = Heatmap(self.settings(window_seconds=10.0))
        heat.add(0.0, (0.1, 0.1))
        heat.add(100.0, (0.9, 0.9))
        self.assertEqual(heat.snapshot().total, 1)
        self.assertFalse(heat.add(1.0, (0.5, 0.5)))        # older than the window
        self.assertEqual(heat.snapshot(now=100.0).weights[3][7], 1)

    def test_decay_halves_by_half_life(self):
        heat = Heatmap(self.settings(window_seconds=100.0, half_life_seconds=10.0, slices=10))
        heat.add(0.0, (0.1, 0.1))                           # slice 0 of 10 s: middle at 5 s
        value = heat.snapshot(now=15.0).weights[0][0]
        self.assertAlmostEqual(value, 0.5 ** ((15.0 - 5.0) / 10.0))
        self.assertLess(heat.snapshot(now=60.0).total, value)

    def test_memory_is_bounded(self):
        heat = Heatmap(self.settings(cols=8, rows=4, window_seconds=10.0, slices=5))
        rng = random.Random(3)
        for index in range(5000):
            heat.add(index * 0.05, (rng.random(), rng.random()))
        self.assertLessEqual(heat.cell_count(), 5 * 8 * 4)
        with self.assertRaises(ValueError):
            Heatmap(self.settings(cols=100, rows=100, max_cells=64))
        with self.assertRaises(ValueError):
            Heatmap(self.settings(half_life_seconds=5.0))

    def test_empty_map_normalises_to_zero(self):
        snap = Heatmap(self.settings()).snapshot()
        self.assertEqual(snap.maximum, 0.0)
        self.assertEqual(sum(sum(r) for r in snap.normalized()), 0.0)

    def test_exports(self):
        heat = Heatmap(self.settings())
        for i in range(5):
            heat.add(float(i), (0.1, 0.1))
        heat.add(6.0, (0.9, 0.9))
        snap = heat.snapshot()
        data = json.loads(snap.to_json("cam"))
        self.assertEqual(data["schema"], "armor.vision.heatmap/v1")
        self.assertFalse(data["contains_images"])
        self.assertEqual(data["total"], 6)
        self.assertEqual(data["normalized"][0][0], 1.0)
        self.assertEqual(snap.to_json("cam"), snap.to_json("cam"))
        for forbidden in ("box", "track_id", "image"):
            self.assertNotIn(f'"{forbidden}"', snap.to_json("cam"))
        svg = ET.fromstring(snap.to_svg(4))
        self.assertTrue(svg.tag.endswith("svg"))
        self.assertEqual(len(svg), 1 + 2)                    # background + two active cells
        png = snap.to_png(4)
        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", png[16:24])
        self.assertEqual((width, height), (32, 16))
        idat = png[png.index(b"IDAT") + 4:png.index(b"IEND") - 8]
        self.assertEqual(len(zlib.decompress(idat)), (1 + width * 3) * height)
        self.assertEqual(snap.to_png(4), png)

    def test_image_size_is_capped(self):
        heat = Heatmap(self.settings(cols=64, rows=64, max_cells=4096))
        heat.add(0.0, (0.5, 0.5))
        png = heat.snapshot().to_png(10_000)
        self.assertLessEqual(struct.unpack(">II", png[16:24])[0], 4096)


class SourceTests(unittest.TestCase):
    def test_synthetic_is_deterministic_and_inside_the_scene(self):
        def collect(seed):
            return [(o.timestamp, o.detections) for o in SyntheticSource("cam-front", seed=seed, duration=20).observations()]
        self.assertEqual(collect(5), collect(5))
        self.assertNotEqual(collect(5), collect(6))
        for _, detections in collect(5):
            for d in detections:
                self.assertTrue(0.0 <= d.box[0] < d.box[2] <= 1.0 and 0.0 <= d.box[1] < d.box[3] <= 1.0)

    def test_synthetic_refuses_bad_settings(self):
        for kwargs in ({"camera_id": ""}, {"camera_id": "c", "seed": True}, {"camera_id": "c", "objects": 1000},
                       {"camera_id": "c", "duration": 0}, {"camera_id": "c", "fps": float("nan")},
                       {"camera_id": "c", "duration": 1e6, "fps": 100}, {"camera_id": "c", "labels": ()}):
            with self.assertRaises(SourceError, msg=kwargs):
                SyntheticSource(**kwargs)

    def write(self, folder, text):
        path = Path(folder) / "d.jsonl"
        path.write_text(text, encoding="utf-8")
        return path

    def test_file_source(self):
        good = ('{"camera_id": "c", "timestamp": 1, "detections": [{"label": "person", "confidence": 0.9, "box": [0.1, 0.1, 0.2, 0.3]}]}\n'
                '\n{"camera_id": "c", "timestamp": 2, "detections": []}\n')
        with tempfile.TemporaryDirectory() as folder:
            seen = list(FileSource(self.write(folder, good)).observations())
            self.assertEqual([o.timestamp for o in seen], [1.0, 2.0])
            self.assertEqual(seen[0].detections[0].label, "person")
            bad_lines = [
                "not json",
                '{"camera_id": "c", "timestamp": NaN, "detections": []}',
                '{"camera_id": "c", "timestamp": 1}',
                '{"camera_id": "", "timestamp": 1, "detections": []}',
                '{"camera_id": "c", "timestamp": true, "detections": []}',
                '{"camera_id": "c", "timestamp": 1, "detections": [], "extra": 1}',
                '{"camera_id": "c", "timestamp": 1, "detections": [1]}',
                '{"camera_id": "c", "timestamp": 1, "detections": [{"label": "p", "confidence": "x", "box": [0, 0, 1, 1]}]}',
                '{"camera_id": "c", "timestamp": 1, "detections": [{"label": "p", "confidence": 1, "box": [0, 0, 1]}]}',
                '{"camera_id": "c", "timestamp": 1, "detections": [{"label": "", "confidence": 1, "box": [0, 0, 1, 1]}]}',
                '{"camera_id": "c", "timestamp": 2, "detections": []}\n{"camera_id": "c", "timestamp": 1, "detections": []}',
                "[]",
            ]
            for text in bad_lines:
                with self.assertRaises(SourceError, msg=text):
                    list(FileSource(self.write(folder, text)).observations())
            with self.assertRaises(SourceError):
                list(FileSource(self.write(folder, good), max_bytes=10).observations())
            with self.assertRaises(SourceError):
                list(FileSource(Path(folder) / "missing.jsonl").observations())
            (Path(folder) / "bin.jsonl").write_bytes(b"\xff\xfe\x00")
            with self.assertRaises(SourceError):
                list(FileSource(Path(folder) / "bin.jsonl").observations())


class EngineTests(unittest.TestCase):
    def engine(self, **events):
        return ActivityEngine(vision(), activity(events=events))

    def test_enter_dwell_loiter_exit(self):
        engine = self.engine(dwell_seconds=2.0, loiter_seconds=4.0, loiter_radius=0.05, lines=[])
        kinds = []
        for step in range(30):                                  # standing in the driveway, then gone
            t = step * 0.5
            detections = [man(0.5, 0.8)] if step < 20 else []
            kinds += [(e["type"], e["zone_id"]) for e in engine.process("cam-front", t, detections)]
        self.assertEqual(kinds, [("zone_enter", "drive"), ("dwell", "drive"), ("loiter", "drive"), ("zone_exit", "drive")])
        self.assertEqual(engine.process("cam-front", 60.0, []), [])      # the exit is reported once
        self.assertEqual(engine._presence, {})

    def test_walking_does_not_loiter_and_leaving_the_zone_exits(self):
        engine = self.engine(dwell_seconds=100.0, loiter_seconds=1.0, loiter_radius=0.02, lines=[])
        events = []
        for step in range(12):
            events += engine.process("cam-front", step * 0.5, [man(0.32 + 0.04 * step, 0.8)])
        self.assertNotIn("loiter", [e["type"] for e in events])
        out = engine.process("cam-front", 6.0, [man(0.05, 0.8)])
        out += engine.process("cam-front", 9.0, [])
        self.assertIn("zone_exit", [e["type"] for e in out])

    def test_line_crossing_with_direction(self):
        engine = self.engine(lines=[{"id": "gate", "a": [0.0, 0.5], "b": [1.0, 0.5]}])
        found = []
        for step, y in enumerate([0.3, 0.4, 0.45, 0.55, 0.6]):
            found += [e for e in engine.process("cam-front", step * 0.2, [man(0.6, y)]) if e["type"] == "line_cross"]
        self.assertEqual([(e["line_id"], e["direction"]) for e in found], [("gate", "to_left")])
        back = []
        for step, y in enumerate([0.6, 0.55, 0.45, 0.4], 10):
            back += [e for e in engine.process("cam-front", step * 0.2, [man(0.6, y)]) if e["type"] == "line_cross"]
        self.assertEqual([e["direction"] for e in back], ["to_right"])

    def test_labels_filter_and_masks(self):
        engine = self.engine(labels=["car"], lines=[])
        self.assertEqual(engine.process("cam-front", 0.0, [man(0.5, 0.8)]), [])
        engine = self.engine(lines=[])
        engine.process("cam-front", 0.0, [Detection("person", 0.9, (0.05, 0.1, 0.1, 0.3)), Detection("p", 2.0, (0.5, 0.5, 0.6, 0.6)),
                                          Detection("p", 0.5, (0.9, 0.9, 0.5, 0.5))])
        self.assertEqual(engine.dropped_detections, 3)
        self.assertEqual(engine.heatmap("cam-front").snapshot().total, 0)

    def test_errors(self):
        engine = self.engine()
        with self.assertRaises(KeyError):
            engine.process("nope", 0.0, [])
        with self.assertRaises(KeyError):
            engine.heatmap("nope")
        with self.assertRaises(ValueError):
            engine.process("cam-front", float("nan"), [])

    def test_property_same_seed_same_everything(self):
        results = []
        for _ in range(2):
            engine = ActivityEngine(vision(), activity(heatmap={"window_seconds": None}))
            events = engine.run(SyntheticSource("cam-front", seed=11, objects=4, duration=40))
            results.append((events, engine.heatmap("cam-front").snapshot().to_json("cam-front")))
        self.assertEqual(results[0], results[1])
        self.assertTrue(results[0][0])

    def test_property_heat_sum_matches_detections(self):
        for seed in (1, 2, 3):
            source = SyntheticSource("cam-front", seed=seed, objects=5, duration=30)
            valid = sum(1 for o in source.observations() for d in o.detections
                        if not (0.0 <= d.box[0] < 0.2 and 0.0 <= d.box[1] + 0.1 < 0.4))   # not under the tree mask
            engine = ActivityEngine(vision(), activity(heatmap={"window_seconds": None, "position": "centre"}))
            engine.run(source)
            snap = engine.heatmap("cam-front").snapshot()
            kept = sum(1 for o in source.observations() for d in o.detections) - engine.dropped_detections
            self.assertEqual(snap.total, kept, seed)
            self.assertLessEqual(snap.total, valid + engine.dropped_detections)
            self.assertEqual(snap.rejected, 0)

    def test_heat_labels_filter(self):
        engine = ActivityEngine(vision(), activity(heatmap={"labels": ["car"]}))
        engine.process("cam-front", 0.0, [man(0.5, 0.8), Detection("car", 0.9, (0.5, 0.32, 0.7, 0.5))])
        self.assertEqual(engine.heatmap("cam-front").snapshot().total, 1)

    def test_state_is_released_when_tracks_expire(self):
        engine = self.engine(lines=[{"id": "g", "a": [0, 0.5], "b": [1, 0.5]}])
        engine.process("cam-front", 0.0, [man(0.5, 0.8)])
        engine.process("cam-front", 100.0, [])
        self.assertEqual((len(engine._presence), len(engine._last_foot)), (0, 0))


class RouteTests(unittest.TestCase):
    def test_route_off_and_on(self):
        self.assertEqual(heatmap_route(None, {})[0], 404)
        engine = ActivityEngine(vision(), activity())
        engine.run(SyntheticSource("cam-front", seed=2, duration=10))
        status, kind, body = heatmap_route(engine, {})
        self.assertEqual((status, kind), (200, "application/json"))
        self.assertEqual(json.loads(body)["camera_id"], "cam-front")
        self.assertEqual(heatmap_route(engine, {"format": "png", "camera": "cam-front"})[1], "image/png")
        self.assertEqual(heatmap_route(engine, {"format": "svg", "scale": "4"})[1], "image/svg+xml")
        for query, code in (({"format": "gif"}, 400), ({"scale": "0"}, 400), ({"scale": "abc"}, 400),
                            ({"x": "1"}, 400), ({"camera": "other"}, 404)):
            self.assertEqual(heatmap_route(engine, query)[0], code, query)


class CliActivityTests(unittest.TestCase):
    def test_off_by_default(self):
        code, out, err = run_cli("simulate", "--simulate-events")
        self.assertEqual((code, out), (3, ""))
        with tempfile.TemporaryDirectory() as folder:
            off = Path(folder) / "off.json"
            off.write_text(json.dumps({"enabled": False}), encoding="utf-8")
            self.assertEqual(run_cli("simulate", "--heatmap", str(Path(folder) / "h.json"), "--activity-config", str(off))[0], 3)
            self.assertFalse((Path(folder) / "h.json").exists())

    def test_simulate_events_and_heatmaps(self):
        with tempfile.TemporaryDirectory() as folder:
            conf = Path(folder) / "a.json"
            conf.write_text(json.dumps(ACTIVITY_EXAMPLE), encoding="utf-8")
            code, out, _ = run_cli("simulate", "--simulate-events", "--activity-config", str(conf), "--seed", "4", "--duration", "30")
            self.assertEqual(code, 0)
            last = json.loads(out.splitlines()[-1])
            self.assertEqual(last["activity"]["events"], len(out.splitlines()) - 1)
            _, again, _ = run_cli("simulate", "--simulate-events", "--activity-config", str(conf), "--seed", "4", "--duration", "30")
            self.assertEqual(out, again)
            for name in ("h.json", "h.png", "h.svg"):
                target = Path(folder) / name
                self.assertEqual(run_cli("simulate", "--heatmap", str(target), "--activity-config", str(conf), "--duration", "10")[0], 0)
                self.assertTrue(target.stat().st_size > 0)
            self.assertEqual(json.loads((Path(folder) / "h.json").read_text())["schema"], "armor.vision.heatmap/v1")
            self.assertEqual(run_cli("simulate", "--heatmap", str(Path(folder) / "h.txt"), "--activity-config", str(conf))[0], 1)
            self.assertEqual(run_cli("simulate", "--heatmap", str(Path(folder) / "nodir" / "h.png"), "--activity-config", str(conf))[0], 2)

    def test_detections_file_and_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            conf = Path(folder) / "a.json"
            conf.write_text(json.dumps(ACTIVITY_EXAMPLE), encoding="utf-8")
            data = Path(folder) / "d.jsonl"
            data.write_text('{"camera_id": "cam-front", "timestamp": 0, "detections": [{"label": "person", "confidence": 0.9, "box": [0.4, 0.6, 0.45, 0.8]}]}\n', encoding="utf-8")
            code, out, _ = run_cli("simulate", "--simulate-events", "--activity-config", str(conf), "--detections-file", str(data))
            self.assertEqual(code, 0)
            self.assertIn("zone_enter", out)
            data.write_text("garbage", encoding="utf-8")
            self.assertEqual(run_cli("simulate", "--simulate-events", "--activity-config", str(conf), "--detections-file", str(data))[0], 2)
            self.assertEqual(run_cli("simulate", "--simulate-events", "--activity-config", str(conf), "--camera", "nope")[0], 1)
            self.assertEqual(run_cli("simulate", "--simulate-events", "--activity-config", str(Path(folder) / "none.json"))[0], 2)
            bad = Path(folder) / "bad.json"
            bad.write_text('{"heatmap": {"cols": 0}}', encoding="utf-8")
            self.assertEqual(run_cli("simulate", "--simulate-events", "--activity-config", str(bad))[0], 1)

    def test_check_and_example(self):
        code, out, _ = run_cli("activity-example")
        self.assertEqual((code, parse_activity_config(json.loads(out))[1]), (0, []))
        with tempfile.TemporaryDirectory() as folder:
            good = Path(folder) / "g.json"
            good.write_text(out, encoding="utf-8")
            self.assertEqual(run_cli("check-activity-config", str(good))[:2], (0, "ok: activity pipeline on\n"))
            bad = Path(folder) / "b.json"
            bad.write_text("[]", encoding="utf-8")
            self.assertEqual(run_cli("check-activity-config", str(bad))[0], 1)
            self.assertEqual(run_cli("check-activity-config", str(Path(folder) / "none.json"))[0], 2)


if __name__ == "__main__":
    unittest.main()
