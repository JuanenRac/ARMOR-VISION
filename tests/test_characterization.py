"""Pins the behaviour that exists before the activity pipeline: it must not change when the switch is off."""
import hashlib
import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from armor_vision.cli import main

SIMULATION_AWAY_SHA256 = "4023a3c3d759df578b70fbfb5749df614e4b54fc08a692927ac2101430010571"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CharacterizationTests(unittest.TestCase):
    def test_built_in_simulation_output_is_byte_for_byte_the_same(self):
        code, out, _ = run("simulate", "--mode", "away")
        self.assertEqual(code, 0)
        self.assertEqual(hashlib.sha256(out.encode()).hexdigest(), SIMULATION_AWAY_SHA256)
        # no mode at all watches every zone: same two events
        code, out2, _ = run("simulate")
        self.assertEqual(out2, out)

    def test_last_line_holds_only_the_five_counters(self):
        _, out, _ = run("simulate")
        stats = json.loads(out.splitlines()[-1])["stats"]
        self.assertEqual(sorted(stats), ["detector_calls", "dropped_detections", "events", "frames", "skipped_by_motion"])


if __name__ == "__main__":
    unittest.main()
