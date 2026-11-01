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

import ipaddress
import json
import math
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from .activity import ActivityEngine, heatmap_route
from .activity_config import ActivityConfig
from .config import VisionConfig
from .sources import FileSource, SourceError, SyntheticSource

SERVICE_SCHEMA = "armor.vision.service/v1"
MAX_BODY_HARD = 1024 * 1024
MAX_DETECTIONS_HARD = 256
SERVICE_EXAMPLE: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8765,
    "allow_remote": False,
    "max_body_bytes": 65536,
    "max_detections": 64,
    "max_query_bytes": 512,
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
    simulate: SimulateSettings | None = None


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
    return ServiceSettings(str(host), int(port), bool(remote), int(body), int(detections), int(query), simulate), []


class LiveService:
    """The engine in memory behind a lock; the HTTP part below only moves bytes in and out of it."""

    def __init__(self, vision: VisionConfig, activity: ActivityConfig, settings: ServiceSettings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
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
            self.refused_posts += 1
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
        self.accepted_posts += 1
        return 200, {"schema": SERVICE_SCHEMA, "events": len(events)}

    def heatmap(self, query: dict[str, str]) -> tuple[int, str, bytes]:
        with self._lock:
            return heatmap_route(self._engine, query)

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

        def do_GET(self) -> None:
            if len(self.path) > settings.max_query_bytes:
                return self._json(414, {"error": "request too long"})
            parts = urlsplit(self.path)
            if parts.path == "/health":
                return self._json(200, service.health())
            if parts.path != "/heatmap":
                return self._json(404, {"error": "not found"})
            pairs = parse_qsl(parts.query, keep_blank_values=True)
            if len({key for key, _ in pairs}) != len(pairs):
                return self._send(400, "text/plain; charset=utf-8", b"a parameter is repeated\n")
            self._send(*service.heatmap(dict(pairs)))

        def do_POST(self) -> None:
            if urlsplit(self.path).path != "/ingest":
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
                service.refused_posts += 1
                return self._json(400, {"error": "not JSON"})
            status, payload = service.ingest(record)
            self._json(status, payload)

        def do_PUT(self) -> None:
            self._json(405, {"error": "method not allowed"})

        do_DELETE = do_PATCH = do_PUT

    return Handler


def make_server(service: LiveService) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((service.settings.host, service.settings.port), _handler(service))
    server.daemon_threads = True
    return server
