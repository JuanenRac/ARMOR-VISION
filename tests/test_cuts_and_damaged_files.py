# ARMOR-VISION - tests/test_cuts_and_damaged_files.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""Cut answers and an audit log whose last line was cut."""
from __future__ import annotations

import http.client
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from armor_vision import context_sync, delivery, phase2  # noqa: E402

BROKEN = (http.client.IncompleteRead(b"{", 100), http.client.BadStatusLine("x"))


class CutAnswerTests(unittest.TestCase):
    def test_a_cut_context_answer_is_a_sync_error(self) -> None:
        settings = mock.Mock(max_bytes=100, timeout_s=1)
        for broken in BROKEN:
            opener = mock.Mock()
            opener.open.side_effect = broken
            with self.assertRaises(context_sync.SyncError):
                context_sync._call(opener, mock.Mock(host="h"), settings)

    def test_a_cut_delivery_answer_is_not_reached(self) -> None:
        for broken in BROKEN:
            opener = mock.Mock()
            opener.open.side_effect = broken
            with mock.patch.object(delivery.urllib.request, "build_opener", return_value=opener):
                self.assertEqual(delivery.http_post("http://127.0.0.1:1", b"{}", "t", 1), 0)


class DamagedFileTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def test_an_audit_log_with_a_cut_last_line_goes_on(self) -> None:
        path = self.folder / "audit.log"
        actor = phase2.Actor("someone", "operator")
        first = phase2.AuditLog(str(path))
        first.record(actor, "read", "plates")
        first.record(actor, "read", "plates")
        raw = path.read_bytes()
        path.write_bytes(raw[:-20] + b"\xf1")   # the second line is cut, with a byte that is not UTF-8
        again = phase2.AuditLog(str(path))
        again.record(actor, "read", "plates")
        self.assertEqual(len(again.entries()), 2)   # the damaged line is left out, the new one is not glued to it
        self.assertEqual(again.verify(), 2)         # and the chain still says which line is damaged
        self.assertEqual(len(phase2.AuditLog(str(path)).entries()), 2)


if __name__ == "__main__":
    unittest.main()
