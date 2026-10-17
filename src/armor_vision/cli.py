"""Command line: check a configuration, or run the built-in simulation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .config import parse_config
from .pipeline import Pipeline
from .tracker import Detection

EXAMPLE_CONFIG = {
    "cameras": {
        "cam-front": {
            "zones": [
                {"id": "drive", "name": "Driveway", "kind": "alert", "labels": ["person"],
                 "min_frames": 3, "min_seconds": 1.0,
                 "points": [[0.3, 0.6], [0.9, 0.6], [0.9, 1.0], [0.3, 1.0]]},
                {"id": "street", "name": "Street", "kind": "detection", "labels": ["car"],
                 "points": [[0.0, 0.3], [1.0, 0.3], [1.0, 0.55], [0.0, 0.55]]},
            ],
            "masks": [[[0.0, 0.0], [0.2, 0.0], [0.2, 0.4], [0.0, 0.4]]],
        }
    },
    "profiles": {"away": ["drive", "street"], "home": ["street"]},
}


def _no_constants(name: str):
    """json.loads accepts NaN and Infinity, which are not JSON and which no number check would stop: the file is refused."""
    raise ValueError(f"{name} is not allowed in the file")


def simulate(config, mode: str | None) -> tuple[list[dict], dict]:
    """A person crosses the driveway, a car sits in the street and something
    moves behind the masked tree, at five pictures per second for eight seconds."""
    pipeline = Pipeline(config, mode=mode)
    events: list[dict] = []
    for step in range(41):
        t = step * 0.2
        x = 0.35 + 0.5 * t / 8.0
        detections = [
            Detection("person", 0.9, (x, 0.62, x + 0.06, 0.82)),
            Detection("car", 0.95, (0.5, 0.32, 0.7, 0.5)),
            Detection("person", 0.8, (0.05, 0.1, 0.1, 0.3)),   # behind the tree mask
        ]
        events.extend(pipeline.process_detections("cam-front", t, detections))
    return events, vars(pipeline.stats)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armor-vision", description="ARMOR-VISION zones and detection rules")
    parser.add_argument("--version", action="version", version=f"armor-vision {__version__}")
    sub = parser.add_subparsers(dest="action")
    check = sub.add_parser("check-config", help="validate a configuration file")
    check.add_argument("file")
    sim = sub.add_parser("simulate", help="run the built-in scenario through the rules")
    sim.add_argument("--config", help="configuration file (default: the built-in example)")
    sim.add_argument("--mode", help="arming mode, e.g. away or home")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:] or ["simulate"])
    if args.action == "check-config":
        try:
            raw = json.loads(Path(args.file).read_text(encoding="utf-8"), parse_constant=_no_constants)
        except (OSError, ValueError) as exc:
            print(f"cannot read {args.file}: {exc}", file=sys.stderr)
            return 2
        config, errors = parse_config(raw)
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        if config is None:
            return 1
        print(f"ok: {len(config.cameras)} camera(s), {sum(len(c.zones) for c in config.cameras.values())} zone(s)")
        return 0
    raw = EXAMPLE_CONFIG
    if getattr(args, "config", None):
        try:
            raw = json.loads(Path(args.config).read_text(encoding="utf-8"), parse_constant=_no_constants)
        except (OSError, ValueError) as exc:
            print(f"cannot read {args.config}: {exc}", file=sys.stderr)
            return 2
    config, errors = parse_config(raw)
    if config is None:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    events, stats = simulate(config, args.mode)
    for event in events:
        print(json.dumps(event, sort_keys=True))
    print(json.dumps({"stats": stats}, sort_keys=True))
    return 0
