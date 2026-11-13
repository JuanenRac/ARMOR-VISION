"""The delivery of activity events to the server (ARMOR-SERVER): `POST /api/v1/ai/activity-events`, one event at a time, with the bearer token of the observation service.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

It is OFF unless the service settings carry a `delivery` object (the default is null: nothing leaves the machine). The token is read from the file the settings name or from
`ARMOR_VISION_DELIVERY_TOKEN`, never from the settings file itself. The address must be https, or http on the loopback address (a token is never sent in clear over a network).
A delivery never holds up a detection: the events go to a bounded queue (the oldest is dropped when it is full and counted) and one daemon thread sends them. A refused or failed
event is counted and not retried forever: the server is the one that decides what is worth an alarm, this only tells it what the engine saw. Only the event the engine made is sent
(no picture, no box). Whether the people the alarms go to are told is the `notify` flag of the event, set by the engine from the profile of the arming mode.
"""
from __future__ import annotations

import ipaddress
import json
import os
import queue
import re
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

DELIVERY_TOKEN_ENV = "ARMOR_VISION_DELIVERY_TOKEN"
DELIVERY_PATH = "/api/v1/ai/activity-events"
KINDS = ("zone_enter", "zone_exit", "dwell", "loiter", "line_cross")
DELIVERY_EXAMPLE: dict[str, Any] = {
    "url": "http://127.0.0.1:18080",
    "token_file": None,
    "kinds": ["zone_enter", "dwell", "loiter"],
    "queue_max": 256,
    "timeout_s": 5,
}
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{24,200}$")


class DeliveryConfigError(ValueError):
    """The delivery settings are wrong: the service does not start."""


@dataclass(frozen=True)
class DeliverySettings:
    url: str
    token_file: str | None = None
    kinds: tuple[str, ...] = ("zone_enter", "dwell", "loiter")
    queue_max: int = 256
    timeout_s: int = 5


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _port_ok(parts: Any) -> bool:
    try:
        port = parts.port
    except ValueError:
        return False
    return port is None or 1 <= port <= 65535


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_delivery_settings(raw: object) -> tuple[DeliverySettings | None, list[str]]:
    """(settings, problems). None for `raw` means the delivery is off and is not a problem; any problem means no settings at all."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["delivery must be null or an object"]
    errors: list[str] = []
    unknown = sorted(set(raw) - set(DELIVERY_EXAMPLE))
    if unknown:
        errors.append(f"delivery: unknown field(s): {', '.join(unknown)}")
    url = raw.get("url")
    parts = None
    if not isinstance(url, str) or not url or len(url) > 200 or re.search(r"\s", url):
        errors.append("delivery.url must be the address of the server")
    else:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
            errors.append("delivery.url must be an origin (scheme, host, optional port) and nothing else")
        elif not _port_ok(parts):
            errors.append("delivery.url has a port that is not a number from 1 to 65535")
        elif parts.scheme == "http" and not _loopback(parts.hostname):
            errors.append("delivery.url must be https unless it is this machine: the token would travel in clear")
    token_file = raw.get("token_file", DELIVERY_EXAMPLE["token_file"])
    if token_file is not None and (not isinstance(token_file, str) or not token_file or len(token_file) > 1024):
        errors.append("delivery.token_file must be null or the path of a file that holds the token")
        token_file = None
    kinds = raw.get("kinds", list(DELIVERY_EXAMPLE["kinds"]))
    if not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) and k in KINDS for k in kinds):
        errors.append(f"delivery.kinds must be a list of {', '.join(KINDS)}")
        kinds = list(DELIVERY_EXAMPLE["kinds"])
    queue_max = raw.get("queue_max", DELIVERY_EXAMPLE["queue_max"])
    if not _whole(queue_max) or not 1 <= queue_max <= 4096:
        errors.append("delivery.queue_max must be a whole number from 1 to 4096")
        queue_max = DELIVERY_EXAMPLE["queue_max"]
    timeout = raw.get("timeout_s", DELIVERY_EXAMPLE["timeout_s"])
    if not _whole(timeout) or not 1 <= timeout <= 60:
        errors.append("delivery.timeout_s must be a whole number of seconds from 1 to 60")
        timeout = DELIVERY_EXAMPLE["timeout_s"]
    if errors:
        return None, errors
    return DeliverySettings(str(url).rstrip("/"), token_file, tuple(dict.fromkeys(kinds)), int(queue_max), int(timeout)), []


def load_delivery_token(settings: DeliverySettings, environ: dict[str, str] | None = None) -> str:
    """The token of the observation service, from the file the settings name or from the environment. A missing, odd or doubly given token is an error; it is never printed."""
    env = os.environ if environ is None else environ
    from_env = env.get(DELIVERY_TOKEN_ENV, "").strip()
    if settings.token_file is not None and from_env:
        raise DeliveryConfigError(f"the delivery token is given twice: by token_file and by {DELIVERY_TOKEN_ENV}")
    token = from_env
    if settings.token_file is not None:
        try:
            token = Path(settings.token_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise DeliveryConfigError(f"cannot read the delivery token file: {type(exc).__name__}") from None
    if not token:
        raise DeliveryConfigError("the delivery needs a token (token_file or the environment variable)")
    if not _TOKEN.match(token):
        raise DeliveryConfigError("the delivery token must be 24 to 200 characters of letters, digits and . _ ~ + / = -")
    return token


Post = Callable[[str, bytes, str, int], int]


def http_post(url: str, body: bytes, token: str, timeout: int) -> int:
    """One POST; the status the server answered, or 0 when it could not be reached. Redirects are not followed (the token goes to the address in the settings and to nobody else)."""
    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:   # noqa: ANN401
            return None
    request = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as answer:   # noqa: S310 - http(s) only, checked by the settings
            return int(answer.status)
    except urllib.error.HTTPError as exc:
        code = int(exc.code)
        exc.close()
        return code
    except (urllib.error.URLError, OSError, ValueError):
        return 0


class EventDeliverer:
    """A bounded queue and one thread that posts the events of the chosen kinds. `offer` never blocks and never raises."""

    def __init__(self, settings: DeliverySettings, token: str, post: Post = http_post, start: bool = True) -> None:
        self.settings = settings
        self._token = token
        self._post = post
        self._queue: queue.Queue[dict | None] = queue.Queue(maxsize=settings.queue_max)
        self._lock = threading.Lock()
        self.sent = 0
        self.failed = 0
        self.dropped = 0
        self._thread: threading.Thread | None = None
        if start:
            self._thread = threading.Thread(target=self._run, name="armor-vision-delivery", daemon=True)
            self._thread.start()

    def offer(self, events: list[dict]) -> int:
        """Queue the events of the kinds the settings name; the number queued. When the queue is full the oldest waiting event goes (counted in `dropped`)."""
        taken = 0
        for event in events:
            if event.get("type") not in self.settings.kinds:
                continue
            while True:
                try:
                    self._queue.put_nowait(event)
                    taken += 1
                    break
                except queue.Full:
                    try:
                        self._queue.get_nowait()
                        with self._lock:
                            self.dropped += 1
                    except queue.Empty:
                        pass
        return taken

    def deliver_one(self, event: dict) -> bool:
        try:
            body = json.dumps(event, separators=(",", ":")).encode("utf-8")
            status = self._post(self.settings.url + DELIVERY_PATH, body, self._token, self.settings.timeout_s)
        except Exception:   # noqa: BLE001 - a delivery fault never reaches the detections
            status = 0
        ok = 200 <= status < 300
        with self._lock:
            if ok:
                self.sent += 1
            else:
                self.failed += 1
        return ok

    def drain(self) -> None:
        """Send what is waiting now, on the calling thread (for tests and for a clean stop)."""
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                return
            if event is not None:
                self.deliver_one(event)

    def _run(self) -> None:
        while True:
            event = self._queue.get()
            if event is None:
                return
            self.deliver_one(event)

    def close(self) -> None:
        if self._thread is not None:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass

    def counters(self) -> dict[str, int]:
        with self._lock:
            return {"sent": self.sent, "failed": self.failed, "dropped": self.dropped}
