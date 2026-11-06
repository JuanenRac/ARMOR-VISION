"""The client that carries the context of the server to the live service, run against a stand-in server and a real live service on this machine (no network outside it)."""
import contextlib
import copy
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from armor_vision.activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from armor_vision.cli import EXAMPLE_CONFIG, main
from armor_vision.config import parse_config
from armor_vision.context_sync import SyncError, SyncSettings, check_url, fetch_context, push_context, read_token, run_forever, sync_once
from armor_vision.service import LiveService, ServiceSettings, make_server

AI = "a" * 32
SERVICE = "s" * 32
LINE = {"id": "gate", "a": [0.0, 0.5], "b": [1.0, 0.5]}


def vision():
    config, errors = parse_config(copy.deepcopy(EXAMPLE_CONFIG))
    assert config is not None, errors
    return config


def activity():
    raw = copy.deepcopy(ACTIVITY_EXAMPLE)
    raw["events"]["lines"] = []
    config, errors = parse_activity_config(raw)
    assert config is not None, errors
    return config


class StandInServer:
    """Answers GET /api/v1/ai/context like the server does: only to its bearer token, with what the test sets."""

    def __init__(self, body=None, status=200, redirect=None):
        self.body, self.status, self.redirect = body, status, redirect
        self.seen = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                outer.seen.append((self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != f"Bearer {AI}":
                    self.send_response(401)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if outer.redirect:
                    self.send_response(302)
                    self.send_header("Location", outer.redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = outer.body if isinstance(outer.body, bytes) else json.dumps(outer.body).encode()
                self.send_response(outer.status)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class LiveRunning:
    def __init__(self, token=None):
        self.service = LiveService(vision(), activity(), ServiceSettings(port=0), token)
        self.server = make_server(self.service)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def context(*cameras):
    return {"mode": "away", "nodes": [], "cameras": list(cameras)}


def settings(server, service, **extra):
    return SyncSettings(server_url=server.url, service_url=service.url, ai_token=AI, service_token=extra.pop("service_token", None), **extra)


class SyncTests(unittest.TestCase):
    def test_the_lines_of_the_server_reach_the_service(self):
        with StandInServer(context({"id": "cam-front", "lines": [LINE]}, {"id": "ghost", "lines": [LINE]})) as server, LiveRunning() as live:
            answer = sync_once(settings(server, live))
            self.assertEqual(answer["cameras"], 1)
            self.assertEqual(answer["ignored"], 1)
            self.assertEqual(server.seen, [("/api/v1/ai/context", f"Bearer {AI}")])

    def test_the_token_of_the_service_is_sent_when_there_is_one(self):
        with StandInServer(context({"id": "cam-front", "lines": [LINE]})) as server, LiveRunning(token=SERVICE) as live:
            with self.assertRaisesRegex(SyncError, "401"):
                sync_once(settings(server, live))
            self.assertEqual(sync_once(settings(server, live, service_token=SERVICE))["cameras"], 1)

    def test_a_wrong_token_of_the_server_is_an_error_that_does_not_show_it(self):
        with StandInServer(context()) as server, LiveRunning() as live:
            bad = SyncSettings(server_url=server.url, service_url=live.url, ai_token="b" * 32, service_token=None)
            with self.assertRaises(SyncError) as caught:
                fetch_context(bad)
            self.assertIn("401", str(caught.exception))
            self.assertNotIn("b" * 32, str(caught.exception))

    def test_what_is_not_a_context_is_refused(self):
        for body in (b"not json", b"[1,2]", json.dumps({"cameras": 3}).encode(), b'{"cameras": NaN}'):
            with StandInServer(body) as server, LiveRunning() as live:
                with self.assertRaises(SyncError, msg=body):
                    fetch_context(settings(server, live))

    def test_an_answer_over_the_limit_is_refused(self):
        with StandInServer(context(*[{"id": f"c{n}"} for n in range(200)])) as server, LiveRunning() as live:
            with self.assertRaisesRegex(SyncError, "over 1024 bytes"):
                fetch_context(settings(server, live, max_bytes=1024))

    def test_a_redirect_is_not_followed(self):
        with StandInServer(context(), redirect="http://127.0.0.1:9/elsewhere") as server, LiveRunning() as live:
            with self.assertRaisesRegex(SyncError, "302"):
                fetch_context(settings(server, live))

    def test_a_service_with_the_pipeline_off_or_nobody_listening_is_an_error(self):
        off = copy.deepcopy(ACTIVITY_EXAMPLE)
        off["enabled"] = False
        parsed, _ = parse_activity_config(off)
        service = LiveService(vision(), parsed, ServiceSettings(port=0))
        server_off = make_server(service)
        thread = threading.Thread(target=server_off.serve_forever, daemon=True)
        thread.start()
        try:
            with StandInServer(context()) as server:
                with self.assertRaisesRegex(SyncError, "503"):
                    push_context(SyncSettings(server_url=server.url, service_url=f"http://127.0.0.1:{server_off.server_address[1]}", ai_token=AI, service_token=None), context())
        finally:
            server_off.shutdown()
            server_off.server_close()
        with StandInServer(context()) as server:
            with self.assertRaisesRegex(SyncError, "cannot reach"):
                push_context(SyncSettings(server_url=server.url, service_url="http://127.0.0.1:9", ai_token=AI, service_token=None, timeout_s=2), context())

    def test_the_addresses_and_tokens_are_checked(self):
        for url in ("ftp://x", "http://", "http://user:pw@host", "http://h/?a=1", "http://h/#f", "host:80"):
            with self.assertRaises(SyncError, msg=url):
                check_url(url, "--server")
        self.assertEqual(check_url("http://127.0.0.1:8080/", "--server"), "http://127.0.0.1:8080")
        self.assertIsNone(read_token(None, "X_NONE", {}))
        self.assertEqual(read_token(None, "X_T", {"X_T": AI}), AI)
        with self.assertRaises(SyncError):
            read_token(None, "X_T", {"X_T": "short"})
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder, "token")
            file.write_text(AI + "\n", encoding="utf-8")
            self.assertEqual(read_token(str(file), "X_T", {}), AI)
            with self.assertRaisesRegex(SyncError, "twice"):
                read_token(str(file), "X_T", {"X_T": AI})
            with self.assertRaises(SyncError) as caught:
                read_token(str(Path(folder, "missing")), "X_T", {})
            self.assertNotIn(AI, str(caught.exception))

    def test_the_loop_says_the_first_round_and_each_change_and_stops(self):
        said = []
        stop = threading.Event()
        with StandInServer(context({"id": "cam-front", "lines": [LINE]})) as server, LiveRunning() as live:
            rounds = []
            real = server.httpd.RequestHandlerClass.do_GET

            def counting(handler):
                rounds.append(1)
                if len(rounds) >= 3:
                    stop.set()
                real(handler)
            server.httpd.RequestHandlerClass.do_GET = counting
            self.assertEqual(run_forever(settings(server, live), 0.05, stop, said.append), 0)
        self.assertEqual(len(said), 1)
        self.assertIn("1 camera", said[0])

    def test_the_command_does_one_round_and_prints_the_answer(self):
        with StandInServer(context({"id": "cam-front", "lines": [LINE]})) as server, LiveRunning() as live, tempfile.TemporaryDirectory() as folder:
            token = Path(folder, "ai")
            token.write_text(AI, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["sync-context", "--server", server.url, "--service", live.url, "--ai-token-file", str(token)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out.getvalue())["cameras"], 1)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                self.assertEqual(main(["sync-context", "--server", server.url, "--service", live.url]), 1)
                self.assertEqual(main(["sync-context", "--server", server.url, "--ai-token-file", str(token), "--interval", "2"]), 1)
                self.assertEqual(main(["sync-context", "--server", "ftp://x", "--ai-token-file", str(token)]), 1)
            self.assertNotIn(AI, err.getvalue())


if __name__ == "__main__":
    unittest.main()
