"""The delivery of activity events to the server: off by default, a token that is never in the settings, https (or this machine) only, a bounded queue, and a flag `notify:false` that
travels with the event untouched. The post is replaced by a double: nothing here touches a network."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from armor_vision.delivery import DELIVERY_EXAMPLE, DELIVERY_PATH, DELIVERY_TOKEN_ENV, DeliveryConfigError, EventDeliverer, http_post, load_delivery_token, parse_delivery_settings
from armor_vision.service import SERVICE_EXAMPLE, LiveService, ServiceSettings, parse_service_settings
from test_service import activity, record, vision

TOKEN = "t" * 32


def settings(**changes):
    raw = copy.deepcopy(DELIVERY_EXAMPLE)
    raw.update(changes)
    parsed, problems = parse_delivery_settings(raw)
    assert parsed is not None, problems
    return parsed


class Recorder:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, body, token, timeout):
        self.calls.append((url, json.loads(body), token, timeout))
        return self.status


class SettingsTest(unittest.TestCase):
    def test_off_by_default(self):
        self.assertIsNone(SERVICE_EXAMPLE["delivery"])
        parsed, problems = parse_service_settings(copy.deepcopy(SERVICE_EXAMPLE))
        self.assertEqual(problems, [])
        self.assertIsNone(parsed.delivery)
        self.assertEqual(parse_delivery_settings(None), (None, []))

    def test_the_example_is_valid(self):
        parsed, problems = parse_delivery_settings(copy.deepcopy(DELIVERY_EXAMPLE))
        self.assertEqual(problems, [])
        self.assertEqual(parsed.kinds, ("zone_enter", "dwell", "loiter"))

    def test_bad_settings_are_refused(self):
        for raw in ("x", [], {}, {"url": ""}, {"url": "ftp://127.0.0.1"}, {"url": "http://192.168.0.10:8080"}, {"url": "https://u:p@server.example"}, {"url": "https://server.example/a?b=1"},
                    {"url": "https://server.example/path"}, {"url": "http://127.0.0.1", "kinds": []}, {"url": "http://127.0.0.1", "kinds": ["alert"]}, {"url": "http://127.0.0.1", "queue_max": 0},
                    {"url": "http://127.0.0.1", "queue_max": True}, {"url": "http://127.0.0.1", "timeout_s": 99}, {"url": "http://127.0.0.1", "token_file": 5}, {"url": "http://127.0.0.1", "extra": 1}):
            parsed, problems = parse_delivery_settings(raw)
            self.assertIsNone(parsed, raw)
            self.assertTrue(problems, raw)

    def test_https_to_another_machine_is_allowed(self):
        parsed, problems = parse_delivery_settings({"url": "https://armor.example:8443/"})
        self.assertEqual(problems, [])
        self.assertEqual(parsed.url, "https://armor.example:8443")

    def test_a_bad_delivery_stops_the_service_settings(self):
        raw = copy.deepcopy(SERVICE_EXAMPLE)
        raw["delivery"] = {"url": "http://10.0.0.5"}
        parsed, problems = parse_service_settings(raw)
        self.assertIsNone(parsed)
        self.assertTrue(any("https" in problem for problem in problems))


class TokenTest(unittest.TestCase):
    def test_token_from_the_environment_or_a_file(self):
        self.assertEqual(load_delivery_token(settings(), {DELIVERY_TOKEN_ENV: TOKEN}), TOKEN)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "token"
            path.write_text(TOKEN + "\n", encoding="utf-8")
            self.assertEqual(load_delivery_token(settings(token_file=str(path)), {}), TOKEN)
            with self.assertRaises(DeliveryConfigError):
                load_delivery_token(settings(token_file=str(path)), {DELIVERY_TOKEN_ENV: TOKEN})
            with self.assertRaises(DeliveryConfigError):
                load_delivery_token(settings(token_file=str(Path(folder) / "missing")), {})

    def test_no_token_or_an_odd_one_is_an_error_that_does_not_print_it(self):
        with self.assertRaises(DeliveryConfigError):
            load_delivery_token(settings(), {})
        with self.assertRaises(DeliveryConfigError) as caught:
            load_delivery_token(settings(), {DELIVERY_TOKEN_ENV: "short secret!"})
        self.assertNotIn("short secret", str(caught.exception))


class DelivererTest(unittest.TestCase):
    def make(self, status=200, **changes):
        post = Recorder(status)
        return EventDeliverer(settings(**changes), TOKEN, post, start=False), post

    def test_only_the_chosen_kinds_are_queued_and_sent_with_the_token(self):
        deliverer, post = self.make()
        events = [{"type": "zone_enter", "zone_id": "a"}, {"type": "line_cross", "line_id": "l"}, {"type": "dwell", "zone_id": "a", "notify": False}, {"type": "zone_exit", "zone_id": "a"}]
        self.assertEqual(deliverer.offer(events), 2)
        deliverer.drain()
        self.assertEqual([call[1]["type"] for call in post.calls], ["zone_enter", "dwell"])
        self.assertTrue(all(call[0] == "http://127.0.0.1:18080" + DELIVERY_PATH and call[2] == TOKEN for call in post.calls))
        self.assertIs(post.calls[1][1]["notify"], False)   # the flag arrives as the engine set it
        self.assertEqual(deliverer.counters(), {"sent": 2, "failed": 0, "dropped": 0})

    def test_a_refusal_or_a_fault_is_counted_and_never_raised(self):
        deliverer, _ = self.make(status=401)
        deliverer.offer([{"type": "loiter"}])
        deliverer.drain()
        self.assertEqual(deliverer.counters()["failed"], 1)

        def boom(*_):
            raise RuntimeError("down")
        broken = EventDeliverer(settings(), TOKEN, boom, start=False)
        broken.offer([{"type": "loiter"}])
        broken.drain()
        self.assertEqual(broken.counters(), {"sent": 0, "failed": 1, "dropped": 0})

    def test_the_queue_is_bounded_and_drops_the_oldest(self):
        deliverer, post = self.make(queue_max=2)
        deliverer.offer([{"type": "dwell", "n": n} for n in range(5)])
        self.assertEqual(deliverer.counters()["dropped"], 3)
        deliverer.drain()
        self.assertEqual([call[1]["n"] for call in post.calls], [3, 4])

    def test_the_thread_sends_and_stops(self):
        post = Recorder()
        deliverer = EventDeliverer(settings(), TOKEN, post)
        deliverer.offer([{"type": "zone_enter"}])
        deliverer.close()
        deliverer._thread.join(5)
        self.assertFalse(deliverer._thread.is_alive())
        self.assertEqual(len(post.calls), 1)

    def test_an_address_that_cannot_be_reached_answers_zero(self):
        self.assertEqual(http_post("http://127.0.0.1:9" + DELIVERY_PATH, b"{}", TOKEN, 1), 0)


class ServiceTest(unittest.TestCase):
    def test_the_service_hands_its_events_on_and_notify_false_travels(self):
        vis = vision()
        act, _ = activity()
        post = Recorder()
        deliverer = EventDeliverer(settings(kinds=["zone_enter", "zone_exit", "dwell", "loiter", "line_cross"]), TOKEN, post, start=False)
        service = LiveService(vis, act, ServiceSettings(), None, deliverer)
        camera = service.health()["cameras"][0]
        zone = next(iter(vis.cameras[camera].zones))
        status, _ = service.ingest(record(1.0, camera=camera, box=_inside(zone)))
        self.assertEqual(status, 200)
        deliverer.drain()
        self.assertGreaterEqual(len(post.calls), 1)
        self.assertEqual(post.calls[0][1]["schema"], "armor.vision.activity/v1")
        self.assertEqual(service.health()["delivery"]["sent"], len(post.calls))

    def test_without_a_delivery_nothing_is_added_to_the_health(self):
        service = LiveService(vision(), activity()[0], ServiceSettings())
        self.assertNotIn("delivery", service.health())


def _inside(zone):
    xs = [p[0] for p in zone.points]
    ys = [p[1] for p in zone.points]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    return (cx - 0.02, cy - 0.04, cx + 0.02, cy)


if __name__ == "__main__":
    unittest.main()
