#!/usr/bin/env python3
"""Runs the tests with coverage and fails when a measure falls under the floor in docs/coverage_threshold.json.

The floor is a number per measure (lines, branches), just under what the tests reach; raising it is a change of that file. Needs the `coverage` package
(pip install coverage). Run from the root of the repository:  python tools/coverage_check.py

Copyright (C) 2026 JuanenRac (Electro Hobby 3D). GPL-3.0-or-later.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEASURES = ("lines", "branches")


def read_floor(text: str) -> dict[str, float]:
    data = json.loads(text)
    floor: dict[str, float] = {}
    for key in MEASURES:
        value = data.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError(f"docs/coverage_threshold.json: {key} must be a number from 0 to 100")
        floor[key] = float(value)
    return floor


def below_floor(totals: dict[str, float], floor: dict[str, float]) -> list[str]:
    return [f"{key} {totals[key]:.1f}% is under the floor of {floor[key]}%" for key in floor if totals[key] < floor[key]]


def main() -> int:
    floor = read_floor((ROOT / "docs" / "coverage_threshold.json").read_text(encoding="utf-8"))
    environment = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "COVERAGE_FILE": str(Path(tempfile.gettempdir()) / f"armor-coverage-{os.getpid()}")}
    run = subprocess.run([sys.executable, "-m", "coverage", "run", "--branch", "--source=src", "-m", "unittest", "discover", "-s", "tests"], cwd=ROOT, env=environment, capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write((run.stdout + run.stderr)[-4000:])
        print("COVERAGE=FAIL the tests failed")
        return 1
    report = subprocess.run([sys.executable, "-m", "coverage", "json", "-o", "-"], cwd=ROOT, env=environment, capture_output=True, text=True)
    try:
        totals = json.loads(report.stdout)["totals"]
        measured = {"lines": 100 * totals["covered_lines"] / max(1, totals["num_statements"]), "branches": 100 * totals["covered_branches"] / max(1, totals["num_branches"])}
    except (ValueError, KeyError):
        print("COVERAGE=FAIL the report of coverage has no totals")
        return 1
    finally:
        Path(environment["COVERAGE_FILE"]).unlink(missing_ok=True)
    under = below_floor(measured, floor)
    print(f"COVERAGE lines={measured['lines']:.1f}% branches={measured['branches']:.1f}% floor={floor['lines']}/{floor['branches']}")
    if under:
        print(f"COVERAGE=FAIL {'; '.join(under)}")
        return 1
    print("COVERAGE=PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
