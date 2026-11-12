"""The TensorRT detector with a simulated engine, the two streams of a camera and the clips with their retention."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision import recording as rec
from armor_vision import streams
from armor_vision.detector import DetectorUnavailable, load_detector
from armor_vision.motion import Frame
from armor_vision.tensorrt_detector import SimulatedEngine, TensorrtDetector, TensorrtEngine, parse_tensorrt_settings
from armor_vision.video_source import VideoSourceError

RAW = {"engine": "model.engine", "labels": ["person", "car"], "input_size": 64}
FRAME = Frame(4, 3, bytes(12))


class TensorrtSettingsTests(unittest.TestCase):
    def test_settings_are_read(self):
        settings, errors = parse_tensorrt_settings(RAW)
        self.assertEqual(errors, [])
        self.assertEqual((settings.engine, settings.labels, settings.input_size, settings.min_confidence), ("model.engine", ("person", "car"), 64, 0.4))

    def test_every_mistake_is_told(self):
        for raw, text in (([], "object"), ({**RAW, "model": "x"}, "unknown"), ({"labels": ["a"]}, "engine is required"), ({**RAW, "input_size": 8}, "input_size"),
                          ({**RAW, "min_confidence": 2}, "min_confidence"), ({**RAW, "labels": []}, "labels")):
            settings, errors = parse_tensorrt_settings(raw)
            self.assertIsNone(settings)
            self.assertTrue(any(text in e for e in errors), (raw, errors))


class TensorrtDetectorTests(unittest.TestCase):
    def detector(self, rows):
        settings, _ = parse_tensorrt_settings(RAW)
        engine = SimulatedEngine(rows)
        return TensorrtDetector(settings, engine), engine

    def test_rows_become_detections_and_the_evidence_is_the_simulator(self):
        detector, engine = self.detector([[6.4, 6.4, 32, 64, 0.9, 0], [0, 0, 10, 10, 0.1, 1]])
        found = detector.detect(FRAME, [])
        self.assertEqual([(d.label, d.confidence) for d in found], [("person", 0.9)])
        self.assertEqual(found[0].box, (0.1, 0.1, 0.5, 1.0))
        self.assertEqual((detector.evidence, detector.calls, engine.calls, engine.sizes), ("simulator", 1, 1, [64]))

    def test_a_function_of_the_frame_can_be_the_script(self):
        detector, _ = self.detector(lambda frame: [[0, 0, frame.width * 10, 40, 0.8, 1]])
        self.assertEqual(detector.detect(FRAME, [])[0].label, "car")

    def test_same_class_overlaps_are_merged(self):
        detector, _ = self.detector([[0, 0, 32, 32, 0.9, 0], [1, 1, 32, 32, 0.8, 0]])
        self.assertEqual(len(detector.detect(FRAME, [])), 1)

    def test_load_detector_needs_the_settings_and_a_missing_engine_is_unavailable(self):
        with self.assertRaises(DetectorUnavailable):
            load_detector("tensorrt")
        settings, _ = parse_tensorrt_settings({**RAW, "engine": str(Path(tempfile.gettempdir()) / "no-such.engine")})
        with self.assertRaises(DetectorUnavailable) as raised:
            load_detector("tensorrt", settings)
        self.assertIn("does not exist", str(raised.exception))

    def test_an_existing_file_without_the_jetson_packages_is_unavailable(self):
        with tempfile.NamedTemporaryFile(suffix=".engine") as handle:
            with self.assertRaises(DetectorUnavailable) as raised:
                TensorrtEngine(handle.name)
            self.assertIn("tensorrt", str(raised.exception))


class StreamPairTests(unittest.TestCase):
    def setUp(self):
        folder = Path(tempfile.mkdtemp())
        self.sub, self.main = folder / "sub.mp4", folder / "main.mp4"
        self.sub.write_bytes(b"x")
        self.main.write_bytes(b"y")
        self.raw = {"analysis": str(self.sub), "record": str(self.main)}

    def test_two_files_make_a_pair(self):
        pair, errors = streams.parse_stream_pair(self.raw)
        self.assertEqual(errors, [])
        self.assertEqual((pair.width, pair.height, pair.fps, pair.segment_seconds, pair.transport), (320, 180, 5.0, 10, "tcp"))

    def test_two_rtsp_addresses_make_a_pair_and_credentials_are_refused(self):
        pair, errors = streams.parse_stream_pair({"analysis": "rtsp://10.0.0.2/sub", "record": "rtsp://10.0.0.2/main"})
        self.assertEqual(errors, [])
        self.assertIsNotNone(pair)
        bad, errors = streams.parse_stream_pair({"analysis": "rtsp://admin:pw@10.0.0.2/sub", "record": "rtsp://10.0.0.2/main"})
        self.assertIsNone(bad)
        self.assertTrue(any("analysis" in e and "password" in e for e in errors))

    def test_every_mistake_is_told(self):
        for change, text in (({"record": str(self.sub)}, "same address"), ({"width": 0}, "width"), ({"segment_seconds": 1}, "segment_seconds"), ({"fps": 99}, "fps"),
                             ({"transport": "http"}, "transport"), ({"extra": 1}, "unknown"), ({"record": str(self.main) + ".missing"}, "record")):
            pair, errors = streams.parse_stream_pair({**self.raw, **change})
            self.assertIsNone(pair)
            self.assertTrue(any(text in e for e in errors), (change, errors))
        self.assertIsNone(streams.parse_stream_pair([])[0])

    def test_the_record_command_copies_without_decoding_and_cuts_segments(self):
        pair, _ = streams.parse_stream_pair({"analysis": "rtsp://10.0.0.2/sub", "record": "rtsp://10.0.0.2/main", "segment_seconds": 20})
        command = streams.record_command(pair, "/var/rec/cam1")
        self.assertEqual(command[command.index("-i") + 1], "rtsp://10.0.0.2/main")
        self.assertEqual(command[command.index("-c") + 1], "copy")
        self.assertEqual(command[command.index("-segment_time") + 1], "20")
        self.assertIn("-rtsp_transport", command)
        self.assertTrue(command[-1].endswith(streams.SEGMENT_NAME))
        with self.assertRaises(VideoSourceError):
            streams.record_command(pair, "-oops")

    def test_the_analysis_frames_come_from_the_small_stream_only(self):
        pair, _ = streams.parse_stream_pair({**self.raw, "width": 2, "height": 2})
        program = [sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(bytes([1]) * 4 + bytes([2]) * 4)"]
        frames = list(streams.analysis_frames(pair, command=program, idle_timeout=10))
        self.assertEqual([f.pixels for f in frames], [bytes([1]) * 4, bytes([2]) * 4])

    def test_the_recorder_starts_runs_and_stops_a_child(self):
        folder = Path(tempfile.mkdtemp()) / "cam1"
        pair, _ = streams.parse_stream_pair(self.raw)
        recorder = streams.SegmentRecorder(pair, str(folder), command=[sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        self.assertFalse(recorder.running)
        recorder.start()
        recorder.start()
        self.assertTrue(recorder.running and folder.is_dir())
        recorder.stop()
        self.assertFalse(recorder.running)
        self.assertIsNone(streams.SegmentRecorder(pair, str(folder), command=["x"]).stop())

    def test_a_program_that_cannot_start_is_a_source_error(self):
        pair, _ = streams.parse_stream_pair(self.raw)
        with self.assertRaises(VideoSourceError):
            streams.SegmentRecorder(pair, tempfile.mkdtemp(), command=[str(Path(tempfile.gettempdir()) / "no-such-program-xyz")]).start()


def seg(start, seconds=10.0, name=None):
    return rec.Segment(name or f"s{int(start)}.mkv", float(start), seconds)


class RecordingTests(unittest.TestCase):
    def test_a_file_name_is_a_segment(self):
        got = rec.segment_from_name("/rec/cam/20260131-101500.mkv", 10)
        self.assertEqual((got.start, got.end), (1769854500.0, 1769854510.0))
        for name in ("clip.mkv", "20261331-101500.mkv", "20260131-101500", "20260131-101500.m"):
            self.assertIsNone(rec.segment_from_name(name, 10))

    def test_the_segments_of_a_clip_include_the_seconds_before_and_after(self):
        segments = [seg(t) for t in range(0, 100, 10)]
        planner = rec.ClipPlanner(rec.RecordingSettings(pre_seconds=5, post_seconds=10))
        planner.trigger("cam", "person", 52.0)
        self.assertEqual(planner.due(55.0, lambda cam: segments), [])
        self.assertEqual(planner.open_cameras, ["cam"])
        (clip,) = planner.due(62.0, lambda cam: segments)
        self.assertEqual((clip.camera_id, clip.label, clip.start, clip.end, clip.triggers), ("cam", "person", 47.0, 62.0, 1))
        self.assertEqual([s.start for s in clip.segments], [40.0, 50.0, 60.0])
        self.assertEqual(planner.open_cameras, [])

    def test_a_new_trigger_extends_the_clip_up_to_its_limit(self):
        planner = rec.ClipPlanner(rec.RecordingSettings(pre_seconds=0, post_seconds=10, max_clip_seconds=30))
        for t in (0.0, 8.0, 16.0, 24.0):
            planner.trigger("cam", "person" if t == 0 else "vehicle", t)
        self.assertEqual(planner.due(29.9, lambda cam: []), [])
        (clip,) = planner.due(30.0, lambda cam: [])
        self.assertEqual((clip.label, clip.start, clip.end, clip.triggers), ("person", 0.0, 30.0, 4))

    def test_two_cameras_have_two_clips(self):
        planner = rec.ClipPlanner()
        planner.trigger("b", "person", 100.0)
        planner.trigger("a", "vehicle", 100.0)
        clips = planner.due(1000.0, lambda cam: [])
        self.assertEqual([(c.camera_id, c.clip_id) for c in clips], [("a", "clip-000001"), ("b", "clip-000002")])

    def test_recording_settings(self):
        got, errors = rec.parse_recording_settings({"pre_seconds": 3, "post_seconds": 20})
        self.assertEqual((errors, got.pre_seconds, got.post_seconds, got.max_clip_seconds), ([], 3.0, 20.0, 300.0))
        for raw in ([], {"x": 1}, {"pre_seconds": -1}, {"post_seconds": "5"}, {"max_clip_seconds": 0}, {"pre_seconds": True}, {"pre_seconds": float("nan")}):
            self.assertIsNone(rec.parse_recording_settings(raw)[0], raw)

    def test_retention_by_type_keeps_a_shared_segment_as_long_as_the_longest(self):
        day = 86400.0
        now = 100 * day
        old, shared, fresh, orphan_old, orphan_new = seg(now - 20 * day, name="old"), seg(now - 10 * day, name="shared"), seg(now - 1 * day, name="fresh"), seg(now - 9 * day, name="o1"), seg(now - 2 * day, name="o2")
        clips = [rec.Clip("c1", "cam", "vehicle", 0, 0, 1, (old, shared)), rec.Clip("c2", "cam", "person", 0, 0, 1, (shared, fresh))]
        retention, errors = rec.parse_retention({"person": 30, "vehicle": 14, "continuous": 7, "default": 3})
        self.assertEqual(errors, [])
        plan = rec.plan_retention(retention, now, clips, [old, shared, fresh, orphan_old, orphan_new])
        self.assertEqual([(e.path, e.reason) for e in plan], [("old", "vehicle"), ("o1", "continuous")])
        erased = []
        self.assertEqual(rec.apply_retention(plan), 0)
        self.assertEqual(rec.apply_retention(plan, erased.append), 2)
        self.assertEqual(erased, ["old", "o1"])

    def test_an_unlisted_type_follows_default_and_retention_is_checked(self):
        self.assertEqual(rec.days_for({"default": 4.0}, "cat"), 4.0)
        self.assertEqual(rec.days_for({}, None), 7.0)
        for raw in ({}, [], {"person": -1}, {"person": "30"}, {"": 3}):
            self.assertIsNone(rec.parse_retention(raw)[0], raw)


if __name__ == "__main__":
    unittest.main()
