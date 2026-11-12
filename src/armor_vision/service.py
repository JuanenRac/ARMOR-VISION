"""A live service that keeps the activity engine in memory and serves the heat map: `python -m armor_vision serve ...`.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The detections come in as they happen (`POST /ingest`, one observation per request, from a camera pipeline or from a simulator) and are fed to the same `ActivityEngine` the command
line uses; `GET /heatmap?camera=&format=&scale=` answers from that memory instead of replaying a file for every request. Nothing but positions is kept (see `heatmap.py`): no picture,
no box, no track leaves the engine, and the service stores nothing on disk.

Everything that can be tuned is in a settings file (`service.json`, see `SERVICE_EXAMPLE`); unknown fields and values out of range are an error and an error means the service does
not start (fail closed). The service has NO secret and no sign-in: it listens on the loopback address unless the file says `"allow_remote": true`, and the server that mounts the route
(ARMOR-SERVER) owns the sign-in, the switch and the roles. The memory is bounded: the grid of each map and its time slices are capped by the activity configuration, a request body is
capped by `max_body_bytes`, an observation by `max_detections`, and the number of cameras is the number of cameras of the configuration.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import math
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .activity import ActivityEngine, HeatmapPlan, heatmap_draw, heatmap_plan
from .activity_config import ActivityConfig
from .context_detection import parse_context_detection
from .context_lines import parse_context_lines
from .config import VisionConfig
from .sources import FileSource, SourceError, SyntheticSource

SERVICE_SCHEMA = "armor.vision.service/v1"
COUNTS_SCHEMA = "armor.vision.counts/v1"
MAX_BODY_HARD = 1024 * 1024
MAX_DETECTIONS_HARD = 256
SERVICE_EXAMPLE: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "allow_remote": False,
    "max_body_bytes": 65536,
    "max_detections": 64,
    "max_query_bytes": 512,
    "request_timeout_s": 15,
    "max_connections": 64,
    "render_cache_entries": 16,
    "token_file": None,
    "simulate": None,
}
_SIMULATE_KEYS = {"camera_id", "seed", "objects", "duration", "fps"}


class ServiceConfigError(ValueError):
    """The settings file is wrong: the service does not start."""


@dataclass(frozen=True)
class SimulateSettings:
    camera_id: str
    seed: int = 1
    objects: int = 3
    duration: float = 60.0
    fps: float = 5.0


@dataclass(frozen=True)
class ServiceSettings:
    host: str = "127.0.0.1"
    port: int = 8765
    allow_remote: bool = False
    max_body_bytes: int = 65536
    max_detections: int = 64
    max_query_bytes: int = 512
    request_timeout_s: int = 15
    max_connections: int = 64
    render_cache_entries: int = 16
    token_file: str | None = None
    simulate: SimulateSettings | None = None


TOKEN_ENV = "ARMOR_VISION_SERVICE_TOKEN"
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{24,200}$")


def load_token(settings: "ServiceSettings", environ: dict[str, str] | None = None) -> str | None:
    """The token the service asks for, from the file the settings name or from the environment (never from the settings file itself, so it is never in a repository), or None when there is none.
    A token that is too short or has odd characters, a file that cannot be read, and both sources at once are errors. Nothing here ever prints the token."""
    env = os.environ if environ is None else environ
    from_env = env.get(TOKEN_ENV, "").strip()
    if settings.token_file is not None and from_env:
        raise ServiceConfigError(f"the token is given twice: by token_file and by {TOKEN_ENV}")
    token = from_env
    if settings.token_file is not None:
        try:
            token = Path(settings.token_file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise ServiceConfigError(f"cannot read the token file {settings.token_file}: {type(exc).__name__}") from None
    if not token:
        if settings.allow_remote:
            raise ServiceConfigError("allow_remote needs a token (token_file or the environment variable): the service does not start without one")
        return None
    if not _TOKEN.match(token):
        raise ServiceConfigError("the token must be 24 to 200 characters of letters, digits and . _ ~ + / = -")
    return token


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def parse_service_settings(raw: object) -> tuple[ServiceSettings | None, list[str]]:
    """(settings, problems): any problem means no settings at all."""
    if raw is None:
        raw = {}
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["the settings must be an object"]
    unknown = sorted(set(raw) - set(SERVICE_EXAMPLE))
    if unknown:
        errors.append(f"unknown field(s): {', '.join(unknown)}")
    d = ServiceSettings()
    host = raw.get("host", d.host)
    port = raw.get("port", d.port)
    remote = raw.get("allow_remote", d.allow_remote)
    body = raw.get("max_body_bytes", d.max_body_bytes)
    detections = raw.get("max_detections", d.max_detections)
    query = raw.get("max_query_bytes", d.max_query_bytes)
    timeout = raw.get("request_timeout_s", d.request_timeout_s)
    connections = raw.get("max_connections", d.max_connections)
    cache = raw.get("render_cache_entries", d.render_cache_entries)
    token_file = raw.get("token_file", d.token_file)
    if not isinstance(host, str) or not host:
        errors.append("host must be an address")
        host = d.host
    if not _whole(port) or not 1 <= port <= 65535:
        errors.append("port must be a whole number from 1 to 65535")
        port = d.port
    if not isinstance(remote, bool):
        errors.append("allow_remote must be true or false")
        remote = False
    if isinstance(host, str) and not remote and not _is_loopback(host):
        errors.append("host is not a loopback address: the service listens only on this machine unless allow_remote is true")
    if not _whole(body) or not 256 <= body <= MAX_BODY_HARD:
        errors.append(f"max_body_bytes must be a whole number from 256 to {MAX_BODY_HARD}")
        body = d.max_body_bytes
    if not _whole(detections) or not 1 <= detections <= MAX_DETECTIONS_HARD:
        errors.append(f"max_detections must be a whole number from 1 to {MAX_DETECTIONS_HARD}")
        detections = d.max_detections
    if not _whole(query) or not 64 <= query <= 4096:
        errors.append("max_query_bytes must be a whole number from 64 to 4096")
        query = d.max_query_bytes
    if not _whole(timeout) or not 1 <= timeout <= 300:
        errors.append("request_timeout_s must be a whole number of seconds from 1 to 300")
        timeout = d.request_timeout_s
    if not _whole(connections) or not 1 <= connections <= 1024:
        errors.append("max_connections must be a whole number from 1 to 1024")
        connections = d.max_connections
    if not _whole(cache) or not 0 <= cache <= 256:
        errors.append("render_cache_entries must be a whole number from 0 (no cache) to 256")
        cache = d.render_cache_entries
    if token_file is not None and (not isinstance(token_file, str) or not token_file or len(token_file) > 1024):
        errors.append("token_file must be null or the path of a file that holds the token")
        token_file = None
    simulate = None
    sim_raw = raw.get("simulate")
    if sim_raw is not None:
        if not isinstance(sim_raw, dict) or set(sim_raw) - _SIMULATE_KEYS or not isinstance(sim_raw.get("camera_id"), str) or not sim_raw.get("camera_id"):
            errors.append(f"simulate must be null or an object with camera_id and, optionally, {', '.join(sorted(_SIMULATE_KEYS - {'camera_id'}))}")
        else:
            try:
                SyntheticSource(**sim_raw)
                simulate = SimulateSettings(**sim_raw)
            except (SourceError, TypeError) as exc:
                errors.append(f"simulate: {exc}")
    if errors:
        return None, errors
    return ServiceSettings(str(host), int(port), bool(remote), int(body), int(detections), int(query), int(timeout), int(connections), int(cache), token_file, simulate), []


class LiveService:
    """The engine in memory behind a lock; the HTTP part below only moves bytes in and out of it."""

    def __init__(self, vision: VisionConfig, activity: ActivityConfig, settings: ServiceSettings, token: str | None = None) -> None:
        self.settings = settings
        self._token = token
        if settings.allow_remote and token is None:
            raise ServiceConfigError("allow_remote needs a token: the service does not start without one")
        self._lock = threading.Lock()
        self._count_lock = threading.Lock()
        self._cache: dict[tuple[object, ...], tuple[int, str, bytes]] = {}
        self._cache_lock = threading.Lock()
        self._engine: ActivityEngine | None = ActivityEngine(vision, activity) if activity.enabled else None
        self._last: dict[str, float] = {}
        self.accepted_posts = 0
        self.refused_posts = 0
        if settings.simulate is not None and self._engine is not None:
            sim = settings.simulate
            self._engine.run(SyntheticSource(sim.camera_id, sim.seed, sim.objects, sim.duration, sim.fps))

    @property
    def enabled(self) -> bool:
        return self._engine is not None

    def ingest(self, record: object) -> tuple[int, dict[str, object]]:
        """One observation. 200 with the number of events, 400 for a bad one, 404 for a camera that is not in the configuration, 409 when time goes backwards, 503 when the pipeline is off."""
        def refuse(status: int, why: str) -> tuple[int, dict[str, object]]:
            self.refuse()
            return status, {"error": why}
        if self._engine is None:
            return refuse(503, "activity_off")
        try:
            observation = FileSource._observation(record, 1)
        except SourceError as exc:
            return refuse(400, str(exc).replace("line 1: ", ""))
        if len(observation.detections) > self.settings.max_detections:
            return refuse(400, f"at most {self.settings.max_detections} detections in one observation")
        with self._lock:
            if observation.camera_id not in self._engine.camera_ids:
                return refuse(404, "unknown camera")
            if observation.timestamp < self._last.get(observation.camera_id, -math.inf):
                return refuse(409, "time goes backwards for this camera")
            events = self._engine.process(observation.camera_id, observation.timestamp, list(observation.detections))
            self._last[observation.camera_id] = observation.timestamp
        with self._count_lock:
            self.accepted_posts += 1
        return 200, {"schema": SERVICE_SCHEMA, "events": len(events)}

    def apply_context(self, context: object) -> tuple[int, dict[str, object]]:
        """The context of the server (`cameras[].lines` and `cameras[].detection`): the counting lines and the detection zones of each camera replace the ones held. A camera with invalid lines loses only its own; the answer counts what was taken and what was left out. 503 when the pipeline is off, 400 when the context is not usable."""
        if self._engine is None:
            self.refuse()
            return 503, {"error": "activity_off"}
        lines, problems = parse_context_lines(context)
        detection, mode, detection_problems = parse_context_detection(context)
        problems = problems + [p for p in detection_problems if p not in problems]
        if not isinstance(context, dict) or not isinstance(context.get("cameras", []), list):
            self.refuse()
            return 400, {"error": problems[0]}
        with self._lock:
            unknown = self._engine.set_camera_lines(lines)
            unknown_zones = self._engine.set_camera_detection(detection, mode)
        taken = len(set(lines) | set(detection)) - len(set(unknown) | set(unknown_zones))
        return 200, {"schema": SERVICE_SCHEMA, "cameras": taken, "ignored": len(problems) + len(set(unknown) | set(unknown_zones))}

    def counts(self) -> tuple[int, dict[str, object]]:
        """The crossings of the counting lines, per camera and line. 404 while the pipeline is off, as if the route did not exist."""
        with self._lock:
            engine = self._engine
            if engine is None:
                return 404, {"error": "not found"}
            return 200, {"schema": COUNTS_SCHEMA, "cameras": engine.line_counts()}

    def refuse(self) -> None:
        """One more request refused (counted under its own lock: the handlers run in many threads)."""
        with self._count_lock:
            self.refused_posts += 1

    def heatmap(self, query: dict[str, str]) -> tuple[int, str, bytes]:
        """The engine is read under the lock and let go of before the picture is drawn, so a PNG at a large scale never holds up the detections that come in. The drawing of a map that has not
        changed (same camera, format and scale, and no observation counted since) is kept, a few at a time (`render_cache_entries`), and handed out again."""
        with self._lock:
            planned = heatmap_plan(self._engine, query)
        if not isinstance(planned, HeatmapPlan):
            return planned
        snapshot = planned.snapshot
        limit = self.settings.render_cache_entries
        key = (planned.camera_id, planned.fmt, planned.scale, snapshot.accepted, snapshot.rejected, snapshot.at)
        if limit > 0:
            with self._cache_lock:
                hit = self._cache.get(key)
            if hit is not None:
                return hit
        answer = heatmap_draw(planned)
        if limit > 0:
            with self._cache_lock:
                if len(self._cache) >= limit:
                    self._cache.pop(next(iter(self._cache)))
                self._cache[key] = answer
        return answer

    def authorized(self, header: str | None) -> bool:
        """True when no token is set, or when the request carries it (`Authorization: Bearer ...`), compared in constant time."""
        if self._token is None:
            return True
        if not isinstance(header, str) or not header.startswith("Bearer "):
            return False
        return hmac.compare_digest(header[7:].strip().encode("utf-8"), self._token.encode("utf-8"))

    def health(self) -> dict[str, object]:
        with self._lock:
            engine = self._engine
            return {"schema": SERVICE_SCHEMA, "status": "ok", "activity": engine is not None, "cameras": [] if engine is None else engine.camera_ids,
                    "accepted": self.accepted_posts, "refused": self.refused_posts,
                    "dropped_detections": 0 if engine is None else engine.dropped_detections}


def _handler(service: LiveService) -> type[BaseHTTPRequestHandler]:
    settings = service.settings

    class Handler(BaseHTTPRequestHandler):
        server_version = "armor-vision"
        sys_version = ""
        timeout = settings.request_timeout_s   # a client that goes quiet in the middle of a request is dropped: a thread is not held for ever

        def log_message(self, format: str, *args: object) -> None:   # nothing about a request is written anywhere
            return

        def _send(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict[str, object]) -> None:
            self._send(status, "application/json", (json.dumps(payload, sort_keys=True) + "\n").encode())

        def _denied(self) -> bool:
            if service.authorized(self.headers.get("Authorization")):
                return False
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Bearer")
            self.send_header("Content-Length", "0")
            self.end_headers()
            service.refuse()
            return True

        def do_GET(self) -> None:
            if self._denied():
                return
            if len(self.path) > settings.max_query_bytes:
                return self._json(414, {"error": "request too long"})
            parts = urlsplit(self.path)
            if parts.path == "/health":
                return self._json(200, service.health())
            if parts.path == "/counts":
                if parts.query:
                    return self._json(400, {"error": "no parameters"})
                return self._json(*service.counts())
            if parts.path != "/heatmap":
                return self._json(404, {"error": "not found"})
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            if len({key for key, _ in pairs}) != len(pairs):
                return self._send(400, "text/plain; charset=utf-8", b"a parameter is repeated\n")
            self._send(*service.heatmap(dict(pairs)))

        def do_POST(self) -> None:
            if self._denied():
                return
            route = urlsplit(self.path).path
            if route not in ("/ingest", "/context"):
                return self._json(404, {"error": "not found"})
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                return self._json(411, {"error": "Content-Length is required"})
            if length < 0 or length > settings.max_body_bytes:
                return self._json(413, {"error": f"the body is over {settings.max_body_bytes} bytes"})
            data = self.rfile.read(length)
            try:
                record = json.loads(data.decode("utf-8"), parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
            except (ValueError, UnicodeDecodeError):
                service.refuse()
                return self._json(400, {"error": "not JSON"})
            status, payload = service.apply_context(record) if route == "/context" else service.ingest(record)
            self._json(status, payload)

        def do_PUT(self) -> None:
            if self._denied():
                return
            self._json(405, {"error": "method not allowed"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


class _Server(ThreadingHTTPServer):
    """One thread per request, at most `max_connections` at the same time: the next one is told to come back (503) instead of starting yet another thread."""
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], max_connections: int) -> None:
        super().__init__(address, handler)
        self._slots = threading.BoundedSemaphore(max_connections)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nRetry-After: 1\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            try:   # what the client already sent is read (without waiting) so that closing does not turn the answer into a reset
                request.setblocking(False)
                request.recv(4096)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(service: LiveService) -> ThreadingHTTPServer:
    return _Server((service.settings.host, service.settings.port), _handler(service), service.settings.max_connections)
