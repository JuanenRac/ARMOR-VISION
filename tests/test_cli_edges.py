"""The edges of the command line that the happy paths do not reach: the files that cannot be read by the commands of the heat map and of the live service, a route that cannot answer
at all, and the live service started and stopped (the real server is replaced by one that returns at once, so no port is opened)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from armor_vision import cli
from armor_vision.activity_config import ACTIVITY_EXAMPLE
from armor_vision.heatmap_service import ServiceError


def run(*arguments: str) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(arguments))
    return code, out.getvalue(), err.getvalue()


class CommandEdgeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.on = self.folder / "on.json"
        self.on.write_text(json.dumps({**ACTIVITY_EXAMPLE, "enabled": True}), encoding="utf-8")

    def test_the_heat_map_route_says_when_its_configuration_cannot_be_read(self):
        code, _, err = run("heatmap-route", "--activity-config", str(self.folder / "none.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        broken = self.folder / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        self.assertEqual(run("heatmap-route", "--activity-config", str(broken))[0], 2)

    def test_the_heat_map_route_gives_the_code_of_a_map_it_cannot_answer_at_all(self):
        with mock.patch.object(cli, "answer", side_effect=ServiceError("no map", 1)):
            code, _, err = run("heatmap-route", "--activity-config", str(self.on))
        self.assertEqual(code, 1)
        self.assertIn("error: no map", err)

    def test_the_live_service_does_not_start_from_a_file_it_cannot_read(self):
        code, _, err = run("serve", "--activity-config", str(self.folder / "none.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)
        wrong = self.folder / "wrong.json"
        wrong.write_text(json.dumps({**ACTIVITY_EXAMPLE, "enabled": "yes"}), encoding="utf-8")
        self.assertEqual(run("serve", "--activity-config", str(wrong))[0], 1)
        code, _, err = run("serve", "--activity-config", str(self.on), "--service-config", str(self.folder / "none.json"))
        self.assertEqual(code, 2)
        self.assertIn("cannot read", err)

    def test_the_live_service_starts_says_where_it_listens_and_closes_its_port_when_it_stops(self):
        for how in (None, KeyboardInterrupt):
            server = mock.Mock()
            server.server_address = ("127.0.0.1", 4321)
            server.serve_forever.side_effect = how
            with mock.patch.object(cli, "make_server", return_value=server):
                code, out, _ = run("serve", "--activity-config", str(self.on))
            self.assertEqual(code, 0)
            self.assertIn("armor-vision service on http://127.0.0.1:4321", out)
            server.server_close.assert_called_once()

    def test_the_live_service_reports_a_port_that_cannot_be_opened(self):
        with mock.patch.object(cli, "make_server", side_effect=OSError("address in use")):
            code, _, err = run("serve", "--activity-config", str(self.on))
        self.assertEqual(code, 2)
        self.assertIn("address in use", err)

    def test_the_service_settings_default_when_no_file_is_given(self):
        settings, problems = cli._read_service_settings(None)
        self.assertIsNotNone(settings)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
