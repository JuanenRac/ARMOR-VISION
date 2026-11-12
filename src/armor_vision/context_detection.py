"""The detection zones of each camera, as the server hands them out in the context of the observation service.

The server keeps up to sixteen detection zones per camera (drawn in Studio) and one profile per arming mode (which zones are watched, how sensitive, whether to tell). It lists them under
`cameras[].detection` of its context, in the same shape as the zones of the configuration of this service. This reads that object into the same `Zone` the activity pipeline uses and picks,
for the mode the context names, the zones that are watched. A mode with no profile watches every zone (an unknown mode never watches less). Each camera is checked on its own: a camera
whose zones are not valid loses only its own zones (fail closed for that camera) and the problem is reported, the others are kept. The sensitivity and the notify flag of a profile are read
and checked but not applied here. Nothing here talks to a network.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import Zone, parse_config

PER_CAMERA_MAX = 16
MODES = ("away", "home", "night", "disarmed")
SENSITIVITIES = ("low", "normal", "high")


@dataclass(frozen=True)
class ModeProfile:
    watch: tuple[str, ...]
    sensitivity: str = "normal"
    notify: bool = True


@dataclass(frozen=True)
class CameraDetection:
    zones: tuple[Zone, ...]
    profiles: dict[str, ModeProfile]

    def watched(self, mode: str | None) -> tuple[Zone, ...]:
        """The zones that count in a mode: all of them when the mode is unknown or has no profile, else the ones its profile lists."""
        profile = self.profiles.get(mode) if mode else None
        if profile is None:
            return self.zones
        wanted = set(profile.watch)
        return tuple(zone for zone in self.zones if zone.zone_id in wanted)


def _profiles(raw: Any, zone_ids: set[str], where: str, problems: list[str]) -> dict[str, ModeProfile] | None:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        problems.append(f"{where}: profiles must be an object")
        return None
    found: dict[str, ModeProfile] = {}
    for mode, entry in raw.items():
        if mode not in MODES or not isinstance(entry, dict) or set(entry) - {"watch", "sensitivity", "notify"}:
            problems.append(f"{where}: profile {str(mode)[:20]!r} is not valid")
            return None
        watch, sensitivity, notify = entry.get("watch"), entry.get("sensitivity", "normal"), entry.get("notify", True)
        if (not isinstance(watch, list) or not all(isinstance(z, str) and z in zone_ids for z in watch)
                or sensitivity not in SENSITIVITIES or not isinstance(notify, bool)):
            problems.append(f"{where}: profile {mode} must list zones of this camera, a known sensitivity and a true or false notify")
            return None
        found[mode] = ModeProfile(tuple(dict.fromkeys(watch)), sensitivity, notify)
    return found


def parse_context_detection(context: Any) -> tuple[dict[str, CameraDetection], str | None, list[str]]:
    """Returns (detection of each camera, the mode of the context or None, problems). A context that is not an object gives nothing and one problem."""
    if not isinstance(context, dict) or not isinstance(context.get("cameras", []), list):
        return {}, None, ["the context must be an object with a list of cameras"]
    mode = context.get("mode") if isinstance(context.get("mode"), str) else None
    found: dict[str, CameraDetection] = {}
    problems: list[str] = []
    for index, camera in enumerate(context.get("cameras", [])):
        if not isinstance(camera, dict) or not isinstance(camera.get("id"), str) or not camera["id"]:
            problems.append(f"camera #{index + 1}: it has no id")
            continue
        raw = camera.get("detection")
        if raw is None:
            continue
        where = f"camera {camera['id']}"
        if not isinstance(raw, dict) or set(raw) - {"zones", "profiles"} or not isinstance(raw.get("zones", []), list) or len(raw.get("zones", [])) > PER_CAMERA_MAX:
            problems.append(f"{where}: detection must be an object with at most {PER_CAMERA_MAX} zones and profiles")
            continue
        config, errors = parse_config({"cameras": {camera["id"]: {"zones": raw.get("zones", [])}}})
        if config is None:
            problems.extend(f"{where}: {error}" for error in errors)
            continue
        zones = config.cameras[camera["id"]].zones
        profiles = _profiles(raw.get("profiles"), {zone.zone_id for zone in zones}, where, problems)
        if profiles is None:
            continue
        if zones:
            found[camera["id"]] = CameraDetection(zones, profiles)
    return found, mode, problems
