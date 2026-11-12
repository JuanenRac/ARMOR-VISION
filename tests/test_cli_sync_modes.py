"""The command that hands the context of the server to a running service, in the ways the loopback tests of the happy path do not reach: one round that fails, and the loop that is
stopped by the person. The rounds themselves are replaced by functions, so nothing is connected to."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from armor_vision import cli
from armor_vision.context_sync import SyncError


def run(*arguments: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class SyncContextModesTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        token = Path(folder.name) / "ai.token"
        token.write_text("a-token-of-the-server-0123456789\n", encoding="utf-8")
        self.base = ["sync-context", "--server", "http://127.0.0.1:1", "--service", "http://127.0.0.1:2", "--ai-token-file", str(token)]

    def test_one_round_that_fails_exits_with_2_and_says_why(self):
        with mock.patch.object(cli, "sync_once", side_effect=SyncError("the server did not answer")):
            code, out, err = run(*self.base)
        self.assertEqual(code, 2)
        self.assertIn("the server did not answer", err)
        self.assertEqual(out, "")

    def test_one_round_that_works_prints_the_answer_sorted_and_exits_0(self):
        with mock.patch.object(cli, "sync_once", return_value={"b": 2, "a": 1}):
            code, out, err = run(*self.base)
        self.assertEqual((code, out.strip(), err), (0, '{"a": 1, "b": 2}', ""))

    def test_the_loop_stopped_by_the_person_exits_0_and_raises_its_stop_flag(self):
        seen = {}

        def forever(settings, interval, stop):
            seen["interval"], seen["stop"] = interval, stop
            raise KeyboardInterrupt

        with mock.patch.object(cli, "run_forever", side_effect=forever):
            code, _out, _err = run(*self.base, "--interval", "30")
        self.assertEqual(code, 0)
        self.assertEqual(seen["interval"], 30)
        self.assertTrue(seen["stop"].is_set())

    def test_the_loop_returns_the_code_it_ends_with(self):
        with mock.patch.object(cli, "run_forever", return_value=2):
            code, _out, _err = run(*self.base, "--interval", "5")
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
