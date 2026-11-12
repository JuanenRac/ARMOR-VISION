"""The edges of the client that carries the context to the live service: a certificate file that cannot be used, an answer of the service that is not what it should be, and what the loop says
when rounds fail and recover. No network: the opener is a stand-in and the rounds are scripted."""
import threading
import unittest
from unittest import mock

from armor_vision import context_sync
from armor_vision.context_sync import SyncError, SyncSettings, push_context, run_forever

SETTINGS = SyncSettings("http://server.local:18080", "http://127.0.0.1:18300", "a" * 32, "s" * 32)


class Reply:
    def __init__(self, status, body):
        self.status, self._body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit=-1):
        return self._body[:limit] if limit >= 0 else self._body


class Opener:
    def __init__(self, status, body):
        self.reply, self.requests = Reply(status, body), []

    def open(self, request, timeout=None):
        self.requests.append(request)
        return self.reply


class CertificateFile(unittest.TestCase):
    def test_a_certificate_file_that_cannot_be_read_is_an_error_without_a_path_or_a_token(self):
        settings = SyncSettings("https://server.local", "http://127.0.0.1:18300", "a" * 32, None, ca_file="no-such-file.pem")
        with self.assertRaises(SyncError) as caught:
            context_sync._opener(settings)
        self.assertIn("certificate", str(caught.exception))
        self.assertNotIn("a" * 32, str(caught.exception))


class AnswerOfTheService(unittest.TestCase):
    def test_a_status_other_than_200_is_an_error_that_names_the_status(self):
        with self.assertRaises(SyncError) as caught:
            push_context(SETTINGS, {"cameras": []}, Opener(503, b"{}"))
        self.assertIn("503", str(caught.exception))

    def test_an_answer_that_is_not_json_is_an_error(self):
        for body in (b"not json", b"\xff\xfe"):
            with self.assertRaises(SyncError, msg=body):
                push_context(SETTINGS, {"cameras": []}, Opener(200, body))

    def test_an_answer_that_is_not_an_object_counts_as_empty(self):
        self.assertEqual(push_context(SETTINGS, {"cameras": []}, Opener(200, b"[1, 2]")), {})

    def test_the_token_of_the_service_goes_in_the_header_and_only_when_there_is_one(self):
        opener = Opener(200, b'{"cameras": 0, "ignored": 0}')
        push_context(SETTINGS, {"cameras": []}, opener)
        self.assertEqual(opener.requests[0].get_header("Authorization"), "Bearer " + "s" * 32)
        bare = Opener(200, b"{}")
        push_context(SyncSettings(SETTINGS.server_url, SETTINGS.service_url, SETTINGS.ai_token, None), {"cameras": []}, bare)
        self.assertIsNone(bare.requests[0].get_header("Authorization"))


class Loop(unittest.TestCase):
    class Stop(threading.Event):
        """An event that says stop after a number of waits, so that the loop ends by itself."""

        def __init__(self, waits):
            super().__init__()
            self.left = waits

        def wait(self, timeout=None):
            self.left -= 1
            if self.left <= 0:
                self.set()
            return self.is_set()

    def run_rounds(self, rounds):
        said = []
        with mock.patch.object(context_sync, "sync_once", side_effect=rounds):
            run_forever(SETTINGS, 0.0, self.Stop(len(rounds)), said.append)
        return said

    def test_it_says_the_first_good_round_and_stays_quiet_after_it(self):
        said = self.run_rounds([{"cameras": 2, "ignored": 1}, {"cameras": 2, "ignored": 1}])
        self.assertEqual(said, ["context handed to the service: 2 camera(s), 1 left out"])

    def test_it_says_the_first_failure_of_a_series_and_the_recovery(self):
        down = SyncError("cannot reach server.local: ConnectionRefusedError")
        said = self.run_rounds([down, down, {"cameras": 1}, down])
        self.assertEqual(said, ["error: cannot reach server.local: ConnectionRefusedError", "context handed to the service: 1 camera(s), 0 left out", "error: cannot reach server.local: ConnectionRefusedError"])


if __name__ == "__main__":
    unittest.main()
