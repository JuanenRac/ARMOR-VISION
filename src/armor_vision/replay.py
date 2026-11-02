"""Replay recorded detections through the zone rules, to tune zones and inertia offline.

The activity pipeline already reads a file of recorded detections; this runs the same file
through the alert rules (zones, masks, arming mode, `min_frames`, `min_seconds`), so a zone
drawn on a recording shows what it would have raised, with nothing sent anywhere.
"""
from __future__ import annotations

from .config import VisionConfig
from .pipeline import Pipeline
from .sources import DetectionSource


def replay(config: VisionConfig, source: DetectionSource, mode: str | None = None) -> tuple[list[dict], dict, dict[str, int]]:
    """Returns (events, pipeline statistics, events per zone). A camera that is not in the
    configuration raises KeyError: a recording of another house must not look like a quiet one."""
    pipeline = Pipeline(config, mode=mode)
    events: list[dict] = []
    for observation in source.observations():
        events.extend(pipeline.process_detections(observation.camera_id, observation.timestamp, list(observation.detections)))
    per_zone: dict[str, int] = {}
    for event in events:
        per_zone[event["zone_id"]] = per_zone.get(event["zone_id"], 0) + 1
    return events, dict(vars(pipeline.stats)), per_zone
