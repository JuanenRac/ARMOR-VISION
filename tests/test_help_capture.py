"""The picture of the help of `sync-context` in the documentation shows what the command prints now: when the options change, the picture must be made again.
Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later."""
import html
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PICTURE = ROOT / "images" / "sync-context-help.svg"


def printed_help() -> list[str]:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), COLUMNS="80", PYTHONIOENCODING="utf-8")
    done = subprocess.run([sys.executable, "-m", "armor_vision", "sync-context", "--help"], capture_output=True, text=True, env=env, encoding="utf-8", check=True)
    return done.stdout.rstrip("\n").replace("\r\n", "\n").split("\n")


class HelpCaptureTests(unittest.TestCase):
    def test_the_picture_shows_the_help_the_command_prints_now(self):
        text = PICTURE.read_text(encoding="utf-8")
        shown = [html.unescape(line) for line in re.findall(r'<text x="20" y="\d+" data-line="\d+">(.*?)</text>', text)]
        # The words are compared, not the line breaks: the width and the wrapping of the help depend on the version of Python.
        squeeze = lambda lines: " ".join(" ".join(lines).split())  # noqa: E731
        self.assertEqual(squeeze(shown), squeeze(printed_help()), "run the command again and remake images/sync-context-help.svg")

    def test_the_picture_is_described_and_the_usage_guide_shows_it(self):
        text = PICTURE.read_text(encoding="utf-8")
        self.assertIn("<title", text)
        self.assertIn("<desc", text)
        self.assertIn("images/sync-context-help.svg", (ROOT / "docs" / "USAGE.md").read_text(encoding="utf-8"))

    def test_every_option_of_the_command_is_in_the_picture(self):
        text = PICTURE.read_text(encoding="utf-8")
        for option in ("--server", "--service", "--ai-token-file", "--service-token-file", "--ca-file", "--interval", "--timeout", "--max-bytes"):
            self.assertIn(option, text)


if __name__ == "__main__":
    unittest.main()
