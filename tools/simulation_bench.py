#!/usr/bin/env python3
# =============================================================================
# ARMOR-VISION - tools/simulation_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D)
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Runs the command line of the service end to end against its simulated camera scenes, as a person would, and checks what comes out.

There is no camera, no detector model and no network involved: the scenes are the synthetic ones the service ships with (people and a car that move about, always the same for the
same seed) and the detections are the ones they produce. What it checks:

    arming        the built-in scene raises an alert for the person in the driveway while the arming mode is 'away' and only a detection for the car while it is 'home'
    repeatable    the same run twice prints the same events, byte for byte
    activity      the dwell, loitering and line events and the heat map of a scene (the heat map is written as a picture that is valid XML)
    refusals      a configuration that is not one, and a scene with more objects than the limit, are refused with a non-zero status and a message

    python tools/simulation_bench.py            # prints one line per check and SIMULATION_BENCH=PASS or FAIL

A green run says the rules (zones, masks, dwell, arming) behave as described on simulated scenes. It says nothing about a real camera, the lighting, the detector model or the speed of
the hardware that will run it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FAILED: list[str] = []


def run(*args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    return subprocess.run([sys.executable, "-m", "armor_vision", *args], capture_output=True, text=True, env=env, timeout=120, check=False)  # noqa: S603


def check(name: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'} {name}{' - ' + detail if detail and not passed else ''}")
    if not passed:
        FAILED.append(name)


def events(out: str) -> list[dict]:
    return [json.loads(line) for line in out.splitlines() if line.startswith("{")]


def main() -> int:
    away, home = run("simulate", "--mode", "away"), run("simulate", "--mode", "home")
    check("the scenes run", away.returncode == 0 and home.returncode == 0, away.stderr + home.stderr)
    away_events, home_events = events(away.stdout), events(home.stdout)
    check("away: the person in the driveway raises an alert", any(e.get("type") == "alert" and e.get("zone_id") == "drive" and e.get("label") == "person" for e in away_events))
    check("home: the driveway is not defended", not any(e.get("type") == "alert" for e in home_events))
    check("home: the car in the street is still a detection", any(e.get("type") == "detection" and e.get("label") == "car" for e in home_events))
    check("no event authorises an action", all(e.get("authorizes_action") is False for e in away_events if "authorizes_action" in e))
    check("the same run twice prints the same events", run("simulate", "--mode", "away").stdout == away.stdout)

    with tempfile.TemporaryDirectory() as folder:
        work = Path(folder)
        example = run("activity-example")
        config = work / "activity.json"
        config.write_text(example.stdout, encoding="utf-8")
        check("the example activity configuration is accepted", example.returncode == 0 and run("check-activity-config", str(config)).returncode == 0)
        scene = ("simulate", "--simulate-events", "--activity-config", str(config), "--seed", "3", "--duration", "60", "--objects", "3")
        first, second = run(*scene), run(*scene)
        kinds = {str(e.get("type")) for e in events(first.stdout) if e.get("type")}
        check("activity events are produced for a scene", first.returncode == 0 and bool(kinds & {"dwell", "loiter", "line_cross"}), f"types: {sorted(kinds)}")
        check("activity events are repeatable", first.stdout == second.stdout)
        picture = work / "heat.svg"
        made = run(*scene, "--heatmap", str(picture))
        valid = False
        if made.returncode == 0 and picture.is_file():
            try:
                valid = ET.parse(picture).getroot().tag.endswith("svg")
            except Exception:  # noqa: BLE001 - any parse error is a failed check
                valid = False
        check("the heat map is written as a valid picture", valid, made.stderr)
        broken = work / "broken.json"
        broken.write_text('{"cameras": 5}', encoding="utf-8")
        refused = run("check-config", str(broken))
        check("a configuration that is not one is refused", refused.returncode != 0 and bool(refused.stderr.strip()))
        flood = run(*scene[:-2], "--objects", "100000")
        check("a scene with more objects than the limit is refused", flood.returncode != 0)
    print(f"SIMULATION_BENCH={'FAIL' if FAILED else 'PASS'} failed={len(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
