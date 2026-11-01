"""The live service under light load and with clients that misbehave: settings for the new limits, a client that goes quiet is dropped, the number of requests at once is bounded, the counters
stay exact when many threads write them, the drawing of a map that has not changed is reused (and the memory of that is bounded), and a map being drawn does not stop observations coming in."""
import socket
import threading
import time
import unittest

import armor_vision.service as service_module
from armor_vision.service import ServiceSettings, parse_service_settings
from test_service import Running, record


class NewSettingsTests(unittest.TestCase):
    def test_the_new_limits_have_defaults_and_ranges(self):
        settings, problems = parse_service_settings(None)
        self.assertEqual(problems, [])
        self.assertEqual((settings.request_timeout_s, settings.max_connections, settings.render_cache_entries), (15, 64, 16))
        good, problems = parse_service_settings({"request_timeout_s": 1, "max_connections": 1024, "render_cache_entries": 0})
        self.assertEqual(problems, [])
        self.assertEqual((good.request_timeout_s, good.max_connections, good.render_cache_entries), (1, 1024, 0))
        for raw in ({"request_timeout_s": 0}, {"request_timeout_s": 301}, {"request_timeout_s": 1.5}, {"request_timeout_s": True}, {"max_connections": 0}, {"max_connections": 1025},
                    {"render_cache_entries": -1}, {"render_cache_entries": 257}, {"render_cache_entries": "8"}):
            settings, problems = parse_service_settings(raw)
            self.assertIsNone(settings, raw)
            self.assertTrue(problems, raw)


class MisbehavingClientTests(unittest.TestCase):
    def test_a_client_that_goes_quiet_in_the_middle_of_a_request_is_dropped(self):
        with Running(ServiceSettings(port=0, request_timeout_s=1)) as running:
            quiet = socket.create_connection(("127.0.0.1", running.port), timeout=10)
            try:
                quiet.sendall(b'POST /ingest HTTP/1.1\r\nHost: x\r\nContent-Length: 100\r\n\r\n{"camera')   # promises 100 bytes, sends 8
                started = time.monotonic()
                data = b"x"
                while data:
                    data = quiet.recv(1024)   # whatever the service says, it must then close the connection
                self.assertLess(time.monotonic() - started, 6, "the service held the connection of a client that stopped sending")
            finally:
                quiet.close()
            self.assertEqual(running.call("GET", "/health")[0], 200, "the service did not go on answering")

    def test_the_requests_at_once_are_bounded_and_a_free_place_is_used_again(self):
        with Running(ServiceSettings(port=0, max_connections=2, request_timeout_s=30)) as running:
            held = [socket.create_connection(("127.0.0.1", running.port), timeout=10) for _ in range(2)]
            try:
                for connection in held:
                    connection.sendall(b"GET /health HTTP/1.1\r\n")   # started, not finished: the place is taken
                time.sleep(0.3)
                third = socket.create_connection(("127.0.0.1", running.port), timeout=10)
                try:
                    # the answer comes as soon as the connection is taken, before the client has said anything
                    self.assertTrue(third.recv(1024).startswith(b"HTTP/1.1 503"))
                finally:
                    third.close()
            finally:
                for connection in held:
                    connection.close()
            deadline = time.monotonic() + 5
            status = 0
            while time.monotonic() < deadline and status != 200:
                time.sleep(0.1)
                status = running.call("GET", "/health")[0]
            self.assertEqual(status, 200, "the places were not given back")


class LoadTests(unittest.TestCase):
    def test_many_threads_at_once_keep_the_counters_exact_and_every_answer_valid(self):
        with Running(ServiceSettings(port=0)) as running:
            per_thread = 25
            statuses = []
            problems = []
            guard = threading.Lock()

            def ingest(base):
                for index in range(per_thread):
                    status = running.call("POST", "/ingest", record(base * 1000 + index))[0]
                    with guard:
                        statuses.append(status)

            def draw():
                for index in range(per_thread):
                    status, _kind, body = running.call("GET", "/heatmap?format=%s&scale=4" % ("png" if index % 2 else "json"))
                    with guard:
                        statuses.append(status)
                        if status == 200 and index % 2 and not body.startswith(b"\x89PNG"):
                            problems.append("the picture is not a PNG")

            # one camera: the times of the threads interleave, so some observations are refused with 409 (time goes backwards); that is part of what is checked
            threads = [threading.Thread(target=ingest, args=(n,)) for n in range(4)] + [threading.Thread(target=draw) for _ in range(4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=60)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(problems, [])
            self.assertEqual(len(statuses), 8 * per_thread)
            self.assertEqual(sorted(set(statuses) - {200, 409}), [])
            health = running.service.health()
            self.assertEqual(health["accepted"] + health["refused"], 4 * per_thread, "a counter lost updates when many threads wrote it")

    def test_a_map_that_has_not_changed_is_drawn_once_and_a_new_observation_changes_it(self):
        with Running(ServiceSettings(port=0)) as running:
            self.assertEqual(running.call("POST", "/ingest", record(1))[0], 200)
            first = running.call("GET", "/heatmap?format=json&scale=8")
            again = running.call("GET", "/heatmap?format=json&scale=8")
            self.assertEqual(first, again)
            self.assertEqual(len(running.service._cache), 1)
            self.assertEqual(running.call("POST", "/ingest", record(2))[0], 200)
            changed = running.call("GET", "/heatmap?format=json&scale=8")
            self.assertNotEqual(changed[2], first[2], "a map that changed was served from the old drawing")

    def test_the_memory_of_the_drawings_is_bounded_and_can_be_switched_off(self):
        with Running(ServiceSettings(port=0, render_cache_entries=2)) as running:
            running.call("POST", "/ingest", record(1))
            for scale in range(1, 12):
                self.assertEqual(running.call("GET", "/heatmap?format=svg&scale=%d" % scale)[0], 200)
            self.assertLessEqual(len(running.service._cache), 2)
        with Running(ServiceSettings(port=0, render_cache_entries=0)) as running:
            running.call("POST", "/ingest", record(1))
            self.assertEqual(running.call("GET", "/heatmap?format=json")[0], 200)
            self.assertEqual(len(running.service._cache), 0)

    def test_an_observation_is_not_held_up_by_a_map_being_drawn(self):
        with Running(ServiceSettings(port=0, render_cache_entries=0)) as running:
            running.call("POST", "/ingest", record(1))
            release = threading.Event()
            started = threading.Event()
            real_draw = service_module.heatmap_draw

            def slow_draw(plan):
                started.set()
                release.wait(10)
                return real_draw(plan)

            service_module.heatmap_draw = slow_draw
            try:
                drawer = threading.Thread(target=lambda: running.call("GET", "/heatmap?format=png&scale=8"))
                drawer.start()
                self.assertTrue(started.wait(5))
                begun = time.monotonic()
                self.assertEqual(running.call("POST", "/ingest", record(2))[0], 200)
                self.assertLess(time.monotonic() - begun, 2, "an observation waited for a picture that was being drawn")
                release.set()
                drawer.join(timeout=10)
            finally:
                service_module.heatmap_draw = real_draw
                release.set()


if __name__ == "__main__":
    unittest.main()
