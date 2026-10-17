"""The vision configuration: cameras, zones, masks and profiles.

A zone is where a detection counts; a mask is where movement is ignored
(a tree, a street lamp, the clock burnt into the picture). Profiles say which
zones are watched in each arming mode. All coordinates are normalised (0..1)
so the same drawing works at any resolution.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from .geometry import valid_polygon

ZONE_KINDS = ("alert", "detection")


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    points: tuple[tuple[float, float], ...]
    labels: tuple[str, ...]          # empty = every label counts
    kind: str                        # alert: raises an alert; detection: only recorded
    min_frames: int                  # frames inside before it counts (inertia)
    min_seconds: float               # seconds inside before it counts (loitering)


@dataclass(frozen=True)
class CameraConfig:
    camera_id: str
    zones: tuple[Zone, ...]
    masks: tuple[tuple[tuple[float, float], ...], ...]
    motion_threshold: int            # 0..255 grey difference that counts as change
    motion_min_cells: int            # changed grid cells needed to run the detector


@dataclass(frozen=True)
class VisionConfig:
    cameras: dict[str, CameraConfig] = field(default_factory=dict)
    profiles: dict[str, tuple[str, ...]] = field(default_factory=dict)  # mode -> zone ids watched


def _number(value: Any) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float))


def parse_config(raw: Any) -> tuple[VisionConfig | None, list[str]]:
    """Returns (config, errors). With any error the config is None: a half-read
    configuration would silently watch less than the owner drew."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return None, ["the configuration must be an object"]
    unknown = sorted(set(raw) - {"cameras", "profiles"})
    if unknown:
        errors.append(f"unknown top-level field(s): {', '.join(unknown)}")
    cameras: dict[str, CameraConfig] = {}
    all_zone_ids: set[str] = set()
    raw_cameras = raw.get("cameras", {})
    if not isinstance(raw_cameras, dict):
        errors.append("cameras must be an object keyed by camera id")
        raw_cameras = {}
    for camera_id, entry in raw_cameras.items():
        where = f"camera {camera_id!r}"
        if not isinstance(entry, dict):
            errors.append(f"{where}: must be an object")
            continue
        unknown = sorted(set(entry) - {"zones", "masks", "motion_threshold", "motion_min_cells"})
        if unknown:
            errors.append(f"{where}: unknown field(s): {', '.join(unknown)}")
        threshold = entry.get("motion_threshold", 25)
        min_cells = entry.get("motion_min_cells", 2)
        if not _number(threshold) or isinstance(threshold, float) or not 1 <= threshold <= 255:
            errors.append(f"{where}: motion_threshold must be a whole number from 1 to 255")
            threshold = 25
        if not _number(min_cells) or isinstance(min_cells, float) or min_cells < 1:
            errors.append(f"{where}: motion_min_cells must be a whole number of at least 1")
            min_cells = 2
        zones: list[Zone] = []
        raw_zones = entry.get("zones", [])
        if not isinstance(raw_zones, list):
            errors.append(f"{where}: zones must be a list")
            raw_zones = []
        for index, zone in enumerate(raw_zones):
            zone_where = f"{where} zone #{index + 1}"
            if not isinstance(zone, dict):
                errors.append(f"{zone_where}: must be an object")
                continue
            unknown = sorted(set(zone) - {"id", "name", "points", "labels", "kind", "min_frames", "min_seconds"})
            if unknown:
                errors.append(f"{zone_where}: unknown field(s): {', '.join(unknown)}")
            zone_id = zone.get("id")
            if not isinstance(zone_id, str) or not zone_id:
                errors.append(f"{zone_where}: id is required")
                continue
            if zone_id in all_zone_ids:
                errors.append(f"{zone_where}: id {zone_id!r} is used twice")
            all_zone_ids.add(zone_id)
            problem = valid_polygon(zone.get("points", []))
            if problem:
                errors.append(f"{zone_where} ({zone_id}): {problem}")
                continue
            kind = zone.get("kind", "alert")
            if kind not in ZONE_KINDS:
                errors.append(f"{zone_where} ({zone_id}): kind must be one of {', '.join(ZONE_KINDS)}")
                kind = "alert"
            labels = zone.get("labels", [])
            if not isinstance(labels, list) or not all(isinstance(label, str) and label for label in labels):
                errors.append(f"{zone_where} ({zone_id}): labels must be a list of names")
                labels = []
            min_frames = zone.get("min_frames", 1)
            min_seconds = zone.get("min_seconds", 0)
            if not _number(min_frames) or isinstance(min_frames, float) or min_frames < 1:
                errors.append(f"{zone_where} ({zone_id}): min_frames must be a whole number of at least 1")
                min_frames = 1
            if not _number(min_seconds) or not math.isfinite(min_seconds) or min_seconds < 0:
                errors.append(f"{zone_where} ({zone_id}): min_seconds must be a finite number, not negative")
                min_seconds = 0
            zones.append(Zone(zone_id, str(zone.get("name", zone_id)),
                              tuple((float(x), float(y)) for x, y in zone["points"]),
                              tuple(labels), kind, int(min_frames), float(min_seconds)))
        masks: list[tuple[tuple[float, float], ...]] = []
        raw_masks = entry.get("masks", [])
        if not isinstance(raw_masks, list):
            errors.append(f"{where}: masks must be a list")
            raw_masks = []
        for index, mask in enumerate(raw_masks):
            problem = valid_polygon(mask)
            if problem:
                errors.append(f"{where} mask #{index + 1}: {problem}")
                continue
            masks.append(tuple((float(x), float(y)) for x, y in mask))
        cameras[str(camera_id)] = CameraConfig(str(camera_id), tuple(zones), tuple(masks), int(threshold), int(min_cells))
    profiles: dict[str, tuple[str, ...]] = {}
    raw_profiles = raw.get("profiles", {})
    if not isinstance(raw_profiles, dict):
        errors.append("profiles must be an object keyed by arming mode")
        raw_profiles = {}
    for mode, zone_ids in raw_profiles.items():
        if not isinstance(zone_ids, list) or not all(isinstance(z, str) for z in zone_ids):
            errors.append(f"profile {mode!r}: must be a list of zone ids")
            continue
        for zone_id in zone_ids:
            if zone_id not in all_zone_ids:
                errors.append(f"profile {mode!r}: zone {zone_id!r} does not exist")
        profiles[str(mode)] = tuple(zone_ids)
    if errors:
        return None, errors
    return VisionConfig(cameras, profiles), []
