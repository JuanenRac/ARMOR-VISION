"""Command line: check a configuration, or run the built-in simulation."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .activity import ActivityEngine
from .activity_config import ACTIVITY_EXAMPLE, parse_activity_config
from .config import parse_config
from .pipeline import Pipeline
from .sources import FileSource, SourceError, SyntheticSource
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


def _read_activity(path: str):
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=_no_constants)
    except (OSError, ValueError) as exc:
        return None, [f"cannot read {path}: {exc}"]
    return parse_activity_config(raw)


def _run_activity(args, config) -> int:
    """The activity pipeline: events and heat map from a synthetic scene or a file of detections. Off unless the
    activity configuration says `enabled`; exit 3 when it is off, 1 for a bad configuration, 2 for a bad source."""
    if not args.activity_config:
        print("the activity pipeline is off: give --activity-config FILE with \"enabled\": true (see activity-example)", file=sys.stderr)
        return 3
    activity, problems = _read_activity(args.activity_config)
    for problem in problems:
        print(f"error: {problem}", file=sys.stderr)
    if activity is None:
        return 2 if problems and problems[0].startswith("cannot read") else 1
    if not activity.enabled:
        print("the activity pipeline is off: \"enabled\" is false in the activity configuration", file=sys.stderr)
        return 3
    source: FileSource | SyntheticSource
    try:
        if args.detections_file:
            source = FileSource(args.detections_file)
        else:
            camera = args.camera or sorted(config.cameras)[0]
            if camera not in config.cameras:
                print(f"error: camera {camera!r} is not in the configuration", file=sys.stderr)
                return 1
            source = SyntheticSource(camera, seed=args.seed, objects=args.objects, duration=args.duration)
        engine = ActivityEngine(config, activity)
        events = engine.run(source)
    except (SourceError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.simulate_events:
        for event in events:
            print(json.dumps(event, sort_keys=True))
        print(json.dumps({"activity": {"events": engine.events, "dropped_detections": engine.dropped_detections}}, sort_keys=True))
    if args.heatmap:
        camera = args.camera or sorted(config.cameras)[0]
        snapshot = engine.heatmap(camera).snapshot()
        out = Path(args.heatmap)
        suffix = out.suffix.lower()
        if suffix not in (".json", ".png", ".svg"):
            print("error: --heatmap file must end in .json, .png or .svg", file=sys.stderr)
            return 1
        data = (snapshot.to_json(camera) + "\n").encode() if suffix == ".json" else snapshot.to_png() if suffix == ".png" else snapshot.to_svg().encode()
        try:
            out.write_bytes(data)
        except OSError as exc:
            print(f"error: cannot write {out}: {exc}", file=sys.stderr)
            return 2
        print(f"heat map written: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="armor-vision", description="ARMOR-VISION zones and detection rules")
    parser.add_argument("--version", action="version", version=f"armor-vision {__version__}")
    sub = parser.add_subparsers(dest="action")
    check = sub.add_parser("check-config", help="validate a configuration file")
    check.add_argument("file")
    sim = sub.add_parser("simulate", help="run the built-in scenario through the rules")
    sim.add_argument("--config", help="configuration file (default: the built-in example)")
    sim.add_argument("--mode", help="arming mode, e.g. away or home")
    sim.add_argument("--simulate-events", action="store_true", help="run the activity pipeline and print its events (needs --activity-config with enabled true)")
    sim.add_argument("--heatmap", metavar="OUT", help="write the activity heat map to OUT (.json, .png or .svg; needs --activity-config with enabled true)")
    sim.add_argument("--activity-config", metavar="FILE", help="activity configuration (events and heat map); off unless it says enabled")
    sim.add_argument("--detections-file", metavar="FILE", help="recorded detections (JSON lines) instead of the synthetic scene")
    sim.add_argument("--camera", help="camera of the synthetic scene (default: the first one of the configuration)")
    sim.add_argument("--seed", type=int, default=1, help="seed of the synthetic scene")
    sim.add_argument("--objects", type=int, default=3, help="people in the synthetic scene")
    sim.add_argument("--duration", type=float, default=60.0, help="seconds of the synthetic scene")
    check_activity = sub.add_parser("check-activity-config", help="validate an activity configuration file")
    check_activity.add_argument("file")
    sub.add_parser("activity-example", help="print an activity configuration to start from")
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
    if args.action == "activity-example":
        print(json.dumps(ACTIVITY_EXAMPLE, indent=2))
        return 0
    if args.action == "check-activity-config":
        activity, problems = _read_activity(args.file)
        for problem in problems:
            print(f"error: {problem}", file=sys.stderr)
        if activity is None:
            return 2 if problems and problems[0].startswith("cannot read") else 1
        print(f"ok: activity pipeline {'on' if activity.enabled else 'off'}")
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
    if args.simulate_events or args.heatmap:
        return _run_activity(args, config)
    events, stats = simulate(config, args.mode)
    for event in events:
        print(json.dumps(event, sort_keys=True))
    print(json.dumps({"stats": stats}, sort_keys=True))
    return 0
