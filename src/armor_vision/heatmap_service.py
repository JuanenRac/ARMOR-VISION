"""The heat map as a route that a server mounts: `python -m armor_vision heatmap-route ...` answers one `GET /heatmap` query and prints the answer as one JSON line.

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.

The server that mounts it owns the network, the sign-in and the switch; this module owns the picture. It builds an engine from the activity configuration and a file of recorded
detections (see `FileSource`), calls `heatmap_route` with the query and wraps the answer:

    {"status": 200, "content_type": "image/png", "body_base64": "..."}

The engine exists only when the activity configuration says `"enabled": true`; without it the answer is the 404 of `heatmap_route` for an engine that is off. A file that cannot be read,
or a configuration that is wrong, is an error (the command exits with 1 or 2 and prints nothing on the standard output): the server must not take it for an empty map.
"""
from __future__ import annotations

import base64
from pathlib import Path

from .activity import ActivityEngine, heatmap_route
from .activity_config import parse_activity_config
from .config import VisionConfig
from .sources import FileSource, SourceError

QUERY_KEYS = ("camera", "format", "scale")


class ServiceError(Exception):
    """The map cannot be answered at all (not a 4xx of the route): the message says why."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


def build_engine(vision: VisionConfig, activity_raw: object, detections: str | Path | None) -> ActivityEngine | None:
    """The engine fed with the recorded detections; None when the activity pipeline is switched off."""
    activity, problems = parse_activity_config(activity_raw)
    if activity is None:
        raise ServiceError("; ".join(problems) or "the activity configuration is wrong", 1)
    if not activity.enabled:
        return None
    engine = ActivityEngine(vision, activity)
    if detections is not None:
        try:
            engine.run(FileSource(detections))
        except (SourceError, KeyError, ValueError) as error:
            raise ServiceError(str(error), 2) from error
    return engine


def answer(vision: VisionConfig, activity_raw: object, detections: str | Path | None, query: dict[str, str]) -> dict[str, object]:
    """{"status", "content_type", "body_base64"} for one query of `GET /heatmap`."""
    unknown = sorted(set(query) - set(QUERY_KEYS))
    engine = build_engine(vision, activity_raw, detections) if not unknown else None
    status, content_type, body = heatmap_route(engine, query) if not unknown else (400, "text/plain; charset=utf-8", f"unknown parameter(s): {', '.join(unknown)}\n".encode())
    return {"status": status, "content_type": content_type, "body_base64": base64.b64encode(body).decode("ascii")}
