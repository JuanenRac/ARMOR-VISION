"""The video source: what it accepts, the command it builds and the frames it cuts, with a stand-in program for ffmpeg (the run against a real stream is the video bench of the CI)."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision import video_source as vs


def program(body: str) -> list[str]:
    folder = Path(tempfile.mkdtemp())
    script = folder / "fake_ffmpeg.py"
    script.write_text("import sys\n" + body, encoding="utf-8")
    return [sys.executable, "-I", str(script)]


TWO_PICTURES = "sys.stdout.buffer.write(bytes([10]) * 12 + bytes([200]) * 12)\n"


class CheckSourceTests(unittest.TestCase):
    def test_an_rtsp_address_is_accepted(self):
        self.assertEqual(vs.check_source("rtsp://192.168.0.20:554/stream1"), "rtsp://192.168.0.20:554/stream1")

    def test_credentials_in_the_address_are_refused(self):
        for source in ("rtsp://user:pass@192.168.0.20/s", "rtsp://user@192.168.0.20/s"):
            with self.assertRaises(vs.VideoSourceError):
                vs.check_source(source)

    def test_other_schemes_and_odd_text_are_refused(self):
        for source in ("http://camera/s", "file:///etc/passwd", "rtsp://", "", "a b", "-i x", "rtsp://h/s\nx"):
            with self.subTest(source=source), self.assertRaises(vs.VideoSourceError):
                vs.check_source(source)

    def test_a_file_must_exist(self):
        with self.assertRaises(vs.VideoSourceError):
            vs.check_source(str(ROOT / "no-such-clip.mp4"))
        self.assertTrue(vs.check_source(str(ROOT / "pyproject.toml")).endswith("pyproject.toml"))


class CommandTests(unittest.TestCase):
    def test_the_command_has_no_shell_and_reads_no_input(self):
        command = vs.ffmpeg_command("rtsp://192.168.0.20/s", 320, 180, 5)
        self.assertEqual(command[0], "ffmpeg")
        self.assertIn("-nostdin", command)
        self.assertEqual(command[command.index("-rtsp_transport") + 1], "tcp")
        self.assertEqual(command[command.index("-vf") + 1], "fps=5,scale=320:180,format=gray")
        self.assertEqual(command[-1], "pipe:1")

    def test_a_file_has_no_rtsp_transport(self):
        self.assertNotIn("-rtsp_transport", vs.ffmpeg_command(str(ROOT / "pyproject.toml"), 64, 36, 2))

    def test_sizes_and_rates_outside_the_limits_are_refused(self):
        for args in ((0, 10, 5), (10, 0, 5), (vs.MAX_WIDTH + 1, 10, 5), (10, 10, 0), (10, 10, vs.MAX_FPS + 1), (True, 10, 5), (10, 10, float("nan"))):
            with self.subTest(args=args), self.assertRaises(vs.VideoSourceError):
                vs.ffmpeg_command("rtsp://h/s", *args)
        with self.assertRaises(vs.VideoSourceError):
            vs.ffmpeg_command("rtsp://h/s", 10, 10, 5, transport="http")


class ReadFramesTests(unittest.TestCase):
    def test_the_stream_is_cut_into_frames(self):
        frames = list(vs.read_frames("rtsp://h/s", 4, 3, 5, command=program(TWO_PICTURES)))
        self.assertEqual([frame.pixels[0] for frame in frames], [10, 200])
        self.assertTrue(all((frame.width, frame.height) == (4, 3) for frame in frames))

    def test_max_frames_stops_the_stream(self):
        endless = "while True:\n    sys.stdout.buffer.write(bytes([7]) * 12)\n    sys.stdout.buffer.flush()\n"
        self.assertEqual(len(list(vs.read_frames("rtsp://h/s", 4, 3, 5, max_frames=5, command=program(endless)))), 5)

    def test_a_half_picture_at_the_end_is_dropped(self):
        frames = list(vs.read_frames("rtsp://h/s", 4, 3, 5, command=program("sys.stdout.buffer.write(bytes(12) + bytes(5))\n")))
        self.assertEqual(len(frames), 1)

    def test_a_silent_stream_is_reported(self):
        silent = "import time\ntime.sleep(30)\n"
        with self.assertRaises(vs.VideoSourceError):
            list(vs.read_frames("rtsp://h/s", 4, 3, 5, idle_timeout=0.5, command=program(silent)))

    def test_a_stream_that_fails_says_why(self):
        failing = "sys.stderr.write('connection refused')\nsys.exit(1)\n"
        with self.assertRaises(vs.VideoSourceError) as caught:
            list(vs.read_frames("rtsp://h/s", 4, 3, 5, command=program(failing)))
        self.assertIn("connection refused", str(caught.exception))

    def test_a_program_that_is_not_there_is_reported(self):
        with self.assertRaises(vs.VideoSourceError):
            list(vs.read_frames("rtsp://h/s", 4, 3, 5, command=["/no/such/program"]))

    def test_bad_limits_are_refused(self):
        for kwargs in ({"max_frames": 0}, {"idle_timeout": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(vs.VideoSourceError):
                list(vs.read_frames("rtsp://h/s", 4, 3, 5, command=program(TWO_PICTURES), **kwargs))


if __name__ == "__main__":
    unittest.main()
