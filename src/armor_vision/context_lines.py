"""The counting lines of each camera, as the server hands them out in the context of the observation service.

The server keeps up to sixteen lines per camera (drawn in Studio) and lists them under `cameras[].lines` of its
context. This reads that list into the same `CountLine` the activity pipeline uses. Each camera is checked on its
own: a camera whose lines are not valid loses only its own lines (fail closed for that camera) and the problem is
reported, the others are kept. Nothing here talks to a network.
"""
from __future__ import annotations

from typing import Any

from .activity_config import CountLine, parse_events

PER_CAMERA_MAX = 16


def parse_context_lines(context: Any) -> tuple[dict[str, tuple[CountLine, ...]], list[str]]:
    """Returns (lines of each camera, problems). A context that is not an object gives no lines and one problem."""
    if not isinstance(context, dict) or not isinstance(context.get("cameras", []), list):
        return {}, ["the context must be an object with a list of cameras"]
    found: dict[str, tuple[CountLine, ...]] = {}
    problems: list[str] = []
    for index, camera in enumerate(context.get("cameras", [])):
        if not isinstance(camera, dict) or not isinstance(camera.get("id"), str) or not camera["id"]:
            problems.append(f"camera #{index + 1}: it has no id")
            continue
        raw = camera.get("lines")
        if raw is None:
            continue
        if not isinstance(raw, list) or len(raw) > PER_CAMERA_MAX:
            problems.append(f"camera {camera['id']}: lines must be a list of at most {PER_CAMERA_MAX}")
            continue
        errors: list[str] = []
        events = parse_events({"lines": raw}, errors)
        if errors:
            problems.extend(f"camera {camera['id']}: {e}" for e in errors)
            continue
        if events.lines:
            found[camera["id"]] = events.lines
    return found, problems
