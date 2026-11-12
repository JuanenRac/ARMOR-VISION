"""The delivery of activity events under abuse: addresses that pretend to be this machine, tokens that try to add a header, a server that redirects, an event that cannot be written as
JSON, a queue that is hammered, and settings of every wrong kind (a fixed seed, never a network beyond the loopback address of this machine)."""
import copy
import http.server
import json
import random
import tempfile
import threading
import unittest
from pathlib import Path

from armor_vision.delivery import DELIVERY_EXAMPLE, DELIVERY_PATH, KINDS, DeliveryConfigError, EventDeliverer, http_post, load_delivery_token, parse_delivery_settings

TOKEN = "k" * 32


def refused(url):
    parsed, problems = parse_delivery_settings({"url": url})
    return parsed is None and bool(problems)


class AddressAbuseTest(unittest.TestCase):
    def test_a_name_that_only_starts_like_this_machine_is_not_this_machine(self):
        for url in ("http://localhost.evil.example", "http://127.0.0.1.evil.example", "http://evil.example/127.0.0.1", "http://localhost@evil.example", "http://127.0.0.1@evil.example"):
            self.assertTrue(refused(url), url)

    def test_the_odd_spellings_of_an_address_are_not_trusted_in_clear(self):
        for url in ("http://0.0.0.0", "http://127.1", "http://2130706433", "http://0x7f.0.0.1", "http://[::]", "http://10.0.0.5", "http://169.254.1.1", "http://[fe80::1]"):
            self.assertTrue(refused(url), url)

    def test_this_machine_is_allowed_in_clear(self):
        for url in ("http://127.0.0.1", "http://127.0.0.1:18200", "http://localhost", "http://[::1]:8080", "http://127.5.5.5"):
            parsed, problems = parse_delivery_settings({"url": url})
            self.assertEqual(problems, [], url)
            self.assertIsNotNone(parsed, url)

    def test_whitespace_control_characters_and_length_are_refused(self):
        for url in ("http://127.0.0.1\n", "http://127.0.0.1 ", " http://127.0.0.1", "http://127.0.0.1\r\nHost: evil", "http://127.0.0.1\t", "https://" + "a" * 195 + ".example", 5, None, ["http://127.0.0.1"]):
            parsed, problems = parse_delivery_settings({"url": url})
            self.assertIsNone(parsed, repr(url))
            self.assertTrue(problems, repr(url))

    def test_a_path_a_query_a_fragment_or_credentials_are_refused(self):
        for url in ("https://armor.example/api", "https://armor.example/?x=1", "https://armor.example#frag", "https://user@armor.example", "https://user:pw@armor.example", "https://armor.example:notaport", "https://armor.example:0", "https://armor.example:65536", "https://armor.example:-1", "http://127.0.0.1:99999",
                    "https:///no-host", "https://", "javascript:alert(1)", "file:///etc/passwd", "//armor.example", "armor.example"):
            self.assertTrue(refused(url), url)

    def test_the_trailing_slash_is_the_only_extra_that_is_cleaned(self):
        parsed, problems = parse_delivery_settings({"url": "https://armor.example:8443/"})
        self.assertEqual((problems, parsed.url), ([], "https://armor.example:8443"))


class TokenAbuseTest(unittest.TestCase):
    def raises(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
            parsed, _ = parse_delivery_settings({"url": "http://127.0.0.1", "token_file": str(path)})
            with self.assertRaises(DeliveryConfigError) as caught:
                load_delivery_token(parsed, {})
        return str(caught.exception)

    def test_a_token_that_would_add_a_header_is_refused_and_not_echoed(self):
        sample = "a" * 30 + "\r\nX-Evil: 1"
        message = self.raises(sample)
        self.assertNotIn("X-Evil", message)
        self.assertNotIn("a" * 30, message)

    def test_odd_bytes_in_the_token_file_are_refused_without_saying_what(self):
        for blob in (b"\xff\xfe" + b"a" * 40, b"\xef\xbb\xbf" + b"b" * 40, b"c" * 40 + b"\x00", ("d" * 20 + "é" + "d" * 20).encode("utf-8"), b"e" * 23, b"f" * 201, b"   ", b""):
            message = self.raises(blob)
            self.assertNotIn("ccccc", message)
            self.assertNotIn("fffff", message)

    def test_a_token_with_a_space_inside_is_refused(self):
        self.raises("g" * 20 + " " + "g" * 20)

    def test_the_longest_and_shortest_good_tokens_pass_and_the_edges_fail(self):
        for good in ("a" * 24, "b" * 200, "A1._~+/=-" * 3):
            parsed, _ = parse_delivery_settings({"url": "http://127.0.0.1"})
            self.assertEqual(load_delivery_token(parsed, {"ARMOR_VISION_DELIVERY_TOKEN": good}), good)
        for bad in ("a" * 23, "b" * 201):
            parsed, _ = parse_delivery_settings({"url": "http://127.0.0.1"})
            with self.assertRaises(DeliveryConfigError):
                load_delivery_token(parsed, {"ARMOR_VISION_DELIVERY_TOKEN": bad})

    def test_a_missing_file_does_not_name_the_path_content(self):
        parsed, _ = parse_delivery_settings({"url": "http://127.0.0.1", "token_file": "/no/such/folder/token"})
        with self.assertRaises(DeliveryConfigError) as caught:
            load_delivery_token(parsed, {})
        self.assertIn("FileNotFoundError", str(caught.exception))

    def test_the_token_is_not_in_the_counters_nor_the_settings(self):
        deliverer = EventDeliverer(parse_delivery_settings({"url": "http://127.0.0.1"})[0], TOKEN, lambda *a: 200, start=False)
        deliverer.offer([{"type": "dwell"}])
        deliverer.drain()
        self.assertNotIn(TOKEN, json.dumps(deliverer.counters()))
        self.assertNotIn(TOKEN, repr(deliverer.settings))


class Answers(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, str | None]] = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        self.send_response(type(self).status)
        if type(self).location:
            self.send_header("Location", type(self).location)
        self.send_header("Content-Length", "0")
        self.end_headers()


def serve(status, location=None):
    handler = type("Handler", (Answers,), {"seen": [], "status": status, "location": location})
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
    return server, handler


class RedirectAbuseTest(unittest.TestCase):
    def test_a_redirect_is_not_followed_and_the_token_goes_nowhere_else(self):
        elsewhere, other = serve(200)
        origin, first = serve(307, f"http://127.0.0.1:{elsewhere.server_port}/steal")
        try:
            status = http_post(f"http://127.0.0.1:{origin.server_port}{DELIVERY_PATH}", b"{}", TOKEN, 5)
        finally:
            for server in (origin, elsewhere):
                server.shutdown()
                server.server_close()
        self.assertEqual(status, 307)
        self.assertEqual(first.seen, [(DELIVERY_PATH, f"Bearer {TOKEN}")])
        self.assertEqual(other.seen, [], "the token reached a second address")

    def test_every_status_is_counted_the_same_way(self):
        for status, ok in ((200, True), (204, True), (299, True), (301, False), (401, False), (403, False), (404, False), (429, False), (500, False), (503, False)):
            server, _ = serve(status)
            try:
                deliverer = EventDeliverer(parse_delivery_settings({"url": f"http://127.0.0.1:{server.server_port}"})[0], TOKEN, start=False)
                deliverer.offer([{"type": "dwell"}])
                deliverer.drain()
            finally:
                server.shutdown()
                server.server_close()
            self.assertEqual(deliverer.counters(), {"sent": int(ok), "failed": int(not ok), "dropped": 0}, status)

    def test_the_bearer_header_carries_the_token_to_the_path_of_the_route(self):
        server, handler = serve(200)
        try:
            self.assertEqual(http_post(f"http://127.0.0.1:{server.server_port}{DELIVERY_PATH}", b'{"a":1}', TOKEN, 5), 200)
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(handler.seen, [("/api/v1/ai/activity-events", f"Bearer {TOKEN}")])


class QueueAbuseTest(unittest.TestCase):
    def deliverer(self, post, **changes):
        raw = copy.deepcopy(DELIVERY_EXAMPLE)
        raw.update(changes)
        return EventDeliverer(parse_delivery_settings(raw)[0], TOKEN, post, start=False)

    def test_an_event_that_cannot_be_written_as_json_is_a_failure_not_a_crash(self):
        deliverer = self.deliverer(lambda *a: 200)
        deliverer.offer([{"type": "dwell", "bad": object()}, {"type": "dwell", "bad": float("nan")}, {"type": "dwell", "bad": {1, 2}}])
        deliverer.drain()
        counters = deliverer.counters()
        self.assertEqual(counters, {"sent": 1, "failed": 2, "dropped": 0}, "the NaN is written as JSON; the object and the set are not")

    def test_an_event_without_a_type_or_with_a_wrong_one_is_never_queued(self):
        deliverer = self.deliverer(lambda *a: 200)
        self.assertEqual(deliverer.offer([{}, {"type": None}, {"type": 5}, {"type": "line_cross_x"}, {"type": "ALERT"}, {"type": ["dwell"]}]), 0)
        self.assertEqual(deliverer.counters(), {"sent": 0, "failed": 0, "dropped": 0})

    def test_a_flood_keeps_the_newest_and_counts_what_it_dropped(self):
        seen = []
        deliverer = self.deliverer(lambda url, body, token, timeout: seen.append(json.loads(body)["n"]) or 200, queue_max=8)
        deliverer.offer([{"type": "dwell", "n": n} for n in range(1000)])
        deliverer.drain()
        self.assertEqual(seen, list(range(992, 1000)))
        self.assertEqual(deliverer.counters(), {"sent": 8, "failed": 0, "dropped": 992})

    def test_a_post_that_raises_anything_is_a_failure_and_the_next_event_still_goes(self):
        calls = []

        def post(url, body, token, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")
            if len(calls) == 2:
                raise MemoryError("small")
            return 200

        deliverer = self.deliverer(post)
        deliverer.offer([{"type": "dwell"}] * 3)
        deliverer.drain()
        self.assertEqual(deliverer.counters(), {"sent": 1, "failed": 2, "dropped": 0})

    def test_threads_offering_at_the_same_time_lose_no_count(self):
        deliverer = self.deliverer(lambda *a: 200, queue_max=4096)
        workers = [threading.Thread(target=lambda: deliverer.offer([{"type": "loiter"}] * 200)) for _ in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(10)
        deliverer.drain()
        self.assertEqual(deliverer.counters(), {"sent": 1600, "failed": 0, "dropped": 0})

    def test_close_on_a_full_queue_never_raises_and_a_second_close_is_harmless(self):
        deliverer = EventDeliverer(parse_delivery_settings({"url": "http://127.0.0.1", "queue_max": 1})[0], TOKEN, lambda *a: 200, start=False)
        deliverer.offer([{"type": "dwell"}])
        deliverer.close()
        deliverer.close()


class SettingsFuzzTest(unittest.TestCase):
    def test_random_settings_never_raise_and_are_either_good_or_explained(self):
        rng = random.Random(20260101)
        pieces = [None, True, False, 0, 1, -1, 5, 4096, 4097, 2**70, 0.5, "", "x", "http://127.0.0.1", "https://armor.example", "dwell", "zone_enter", [], ["dwell"], ["nope"], {}, {"a": 1}, "é", "a" * 300]
        keys = list(DELIVERY_EXAMPLE) + ["extra", "", "URL"]
        for _ in range(400):
            raw = {key: rng.choice(pieces) for key in rng.sample(keys, rng.randint(0, len(keys)))}
            parsed, problems = parse_delivery_settings(raw)
            if parsed is None:
                self.assertTrue(problems, raw)
            else:
                self.assertEqual(problems, [])
                self.assertTrue(parsed.url.startswith(("http://", "https://")))
                self.assertTrue(parsed.url.startswith("https://") or "127." in parsed.url or "localhost" in parsed.url or "[::1]" in parsed.url, parsed.url)
                self.assertTrue(1 <= parsed.queue_max <= 4096 and 1 <= parsed.timeout_s <= 60)
                self.assertTrue(parsed.kinds and set(parsed.kinds) <= set(KINDS))
                self.assertEqual(len(parsed.kinds), len(set(parsed.kinds)))


if __name__ == "__main__":
    unittest.main()
