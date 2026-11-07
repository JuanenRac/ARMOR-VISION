#!/usr/bin/env python3
# =============================================================================
# ARMOR-VISION - tools/video_bench.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D)
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Reads a recorded clip as a video stream and checks what the movement model makes of it.

The clip is made here with ffmpeg and shows no person: a dark scene that stays still for four seconds and then a white block that crosses it from left to right in eight. The
workflow "Video bench" serves it as an RTSP stream (a test server in a container, the clip played in a loop) and reads it back through ffmpeg exactly as a camera would be read.
What it checks:

    still       the seconds without anything moving give no moved cell
    crossing    the block crossing the scene is movement, in one place that goes from the left to the right
    gone        a stream that is not there is reported at once instead of hanging

    python tools/video_bench.py --make-clip clip.mp4             # writes the clip (needs ffmpeg)
    python tools/video_bench.py --source clip.mp4                # reads a file, or an rtsp:// address, and prints SIMULATION_VIDEO=PASS or FAIL

A green run says the video path (ffmpeg, the frames, the movement model) works on a recorded clip. It says nothing about a real camera, its compression, its lighting or the speed of
the hardware that will run it.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from armor_vision import motion, video_source  # noqa: E402

WIDTH, HEIGHT, FPS = 320, 180, 5
CLIP_SECONDS, STILL_SECONDS = 12, 4
PIXEL_THRESHOLD = 25
FAILED: list[str] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    print(f"{'PASS' if passed else 'FAIL'} {name}{' - ' + detail if detail and not passed else ''}", flush=True)
    if not passed:
        FAILED.append(name)


def make_clip(path: Path, ffmpeg: str = "ffmpeg") -> None:
    graph = (f"color=c=0x202020:s={WIDTH}x{HEIGHT}:r=10:d={CLIP_SECONDS}[scene];color=c=white:s=40x60:r=10:d={CLIP_SECONDS}[block];"
             f"[scene][block]overlay=x='if(lt(t,{STILL_SECONDS}),-100,(t-{STILL_SECONDS})*35)':y=60:eval=frame")
    subprocess.run([ffmpeg, "-y", "-nostdin", "-hide_banner", "-loglevel", "error", "-filter_complex", graph, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-g", "10",
                    "-movflags", "+faststart", str(path)], check=True, timeout=120)  # noqa: S603


def runs(flags: list[bool], wanted: bool) -> int:
    """The longest run of consecutive entries equal to `wanted`."""
    best = current = 0
    for flag in flags:
        current = current + 1 if flag == wanted else 0
        best = max(best, current)
    return best


def play(source: str, seconds: float) -> None:
    frames = list(video_source.read_frames(source, WIDTH, HEIGHT, FPS, max_frames=int(seconds * FPS), idle_timeout=30.0))
    check("the stream gives pictures", len(frames) >= int(min(seconds, CLIP_SECONDS) * FPS) - 2, f"{len(frames)} pictures")
    moved: list[bool] = []
    centres: list[float | None] = []
    for before, after in zip(frames, frames[1:], strict=False):
        cells = motion.moved_cells(before, after, PIXEL_THRESHOLD)
        moved.append(bool(cells))
        rects = motion.region_rects(cells)
        centres.append(rects[0]["x"] + rects[0]["w"] / 2 if rects else None)
    still_needed = (STILL_SECONDS - 1) * FPS
    check("still: the seconds without movement give no moved cell", runs(moved, False) >= still_needed, f"longest quiet run {runs(moved, False)} of {len(moved)} (wanted {still_needed})")
    crossing_needed = (CLIP_SECONDS - STILL_SECONDS - 2) * FPS
    check("crossing: the block is movement for most of its trip", runs(moved, True) >= crossing_needed, f"longest moving run {runs(moved, True)} of {len(moved)} (wanted {crossing_needed})")
    best: list[float] = []
    segment: list[float] = []
    for centre in centres + [None]:
        if centre is None:
            best = segment if len(segment) > len(best) else best
            segment = []
        else:
            segment.append(centre)
    rising = sum(1 for a, b in zip(best, best[1:], strict=False) if b >= a)
    check("crossing: the place of the movement goes from the left to the right", len(best) >= 2 and rising >= 0.8 * (len(best) - 1) and best[-1] - best[0] > 0.3,
          f"{len(best)} places, {rising} rising, from {best[0] if best else 0:.2f} to {best[-1] if best else 0:.2f}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--make-clip", type=Path, metavar="FILE", help="write the test clip there and stop")
    parser.add_argument("--source", help="an rtsp:// address or the clip file")
    parser.add_argument("--seconds", type=float, default=float(CLIP_SECONDS + 2), help="how much of the stream to read (a little more than the clip, so that both halves are in it)")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)
    if args.make_clip:
        make_clip(args.make_clip, args.ffmpeg)
        print(f"wrote {args.make_clip}")
        return 0
    if not args.source:
        parser.error("--source or --make-clip is needed")
    play(args.source, args.seconds)
    try:
        list(video_source.read_frames("rtsp://127.0.0.1:9/none", WIDTH, HEIGHT, FPS, max_frames=3, idle_timeout=15.0))
        check("gone: a stream that is not there is reported", False, "pictures came from nowhere")
    except video_source.VideoSourceError:
        check("gone: a stream that is not there is reported", True)
    print(f"SIMULATION_VIDEO={'FAIL' if FAILED else 'PASS'}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
