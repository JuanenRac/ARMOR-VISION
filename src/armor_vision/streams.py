"""Two streams from one camera: a small one to analyse and the main one to record.

Cameras give a main stream (full resolution, for the recording) and a sub stream (low resolution, cheap to analyse). Reading the
sub stream for the movement model and the detector and recording the main one without touching its pixels (`-c copy`, cut into
segments) is what keeps the load low. This module only builds and supervises the two ffmpeg commands: the analysis frames come from
`video_source.read_frames` and the recording is a child process of its own. Both sources follow the rules of `video_source`
(`rtsp(s)` without credentials, or a file), which makes the whole thing testable with two recorded clips; nothing here has been tried
on a real camera.
"""
from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .motion import Frame
from .video_source import MAX_FPS, MAX_HEIGHT, MAX_WIDTH, VideoSourceError, check_source, read_frames

PAIR_FIELDS = {"analysis", "record", "width", "height", "fps", "segment_seconds", "transport"}
MIN_SEGMENT_SECONDS, MAX_SEGMENT_SECONDS = 2, 3600
SEGMENT_NAME = "%Y%m%d-%H%M%S.mkv"


@dataclass(frozen=True)
class StreamPair:
    analysis: str                  # the low resolution stream that the movement model and the detector read
    record: str                    # the main stream that is recorded as it comes
    width: int = 320               # size of the grey frames cut from the analysis stream
    height: int = 180
    fps: float = 5.0
    segment_seconds: int = 10      # length of each recorded file: the unit of the pre and post capture
    transport: str = "tcp"


def parse_stream_pair(raw: Any) -> tuple[StreamPair | None, list[str]]:
    """Returns (pair, errors); with any error the pair is None."""
    if not isinstance(raw, dict):
        return None, ["the streams must be an object with analysis and record"]
    errors = [f"unknown field(s): {', '.join(sorted(set(raw) - PAIR_FIELDS))}"] if set(raw) - PAIR_FIELDS else []
    sources: dict[str, str] = {}
    for name in ("analysis", "record"):
        try:
            sources[name] = check_source(raw.get(name))
        except VideoSourceError as error:
            errors.append(f"{name}: {error}")
    if len(sources) == 2 and sources["analysis"] == sources["record"]:
        errors.append("analysis and record are the same address: the point of two streams is a small one to analyse and the main one to record")
    values: dict[str, Any] = {}
    for name, default, high in (("width", 320, MAX_WIDTH), ("height", 180, MAX_HEIGHT), ("segment_seconds", 10, MAX_SEGMENT_SECONDS)):
        value = raw.get(name, default)
        low = MIN_SEGMENT_SECONDS if name == "segment_seconds" else 1
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            errors.append(f"{name} must be a whole number from {low} to {high}")
        values[name] = value
    fps = raw.get("fps", 5.0)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 0 < fps <= MAX_FPS:
        errors.append(f"fps must be a number above 0 and up to {MAX_FPS:g}")
    transport = raw.get("transport", "tcp")
    if transport not in ("tcp", "udp"):
        errors.append("transport is tcp or udp")
    if errors:
        return None, errors
    return StreamPair(sources["analysis"], sources["record"], values["width"], values["height"], float(fps), values["segment_seconds"], transport), []


def analysis_frames(pair: StreamPair, **options: Any) -> Iterator[Frame]:
    """The grey frames of the sub stream (same options as `video_source.read_frames`)."""
    return read_frames(pair.analysis, pair.width, pair.height, pair.fps, transport=pair.transport, **options)


def record_command(pair: StreamPair, out_dir: str, ffmpeg: str = "ffmpeg") -> list[str]:
    """The ffmpeg command line that copies the main stream, without decoding it, into files of `segment_seconds` named by their start time."""
    folder = str(out_dir)
    if not folder or folder.startswith("-") or any(ord(c) < 32 for c in folder):
        raise VideoSourceError("the folder of the recording is a path")
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if pair.record.lower().startswith(("rtsp://", "rtsps://")):
        command += ["-rtsp_transport", pair.transport]
    return command + ["-i", pair.record, "-map", "0:v", "-c", "copy", "-f", "segment", "-segment_time", str(pair.segment_seconds), "-reset_timestamps", "1",
                      "-strftime", "1", str(Path(folder) / SEGMENT_NAME)]


class SegmentRecorder:
    """Runs the recording command as a child process: start, check, stop. It never writes anywhere but the folder it is given."""

    def __init__(self, pair: StreamPair, out_dir: str, ffmpeg: str = "ffmpeg", command: Sequence[str] | None = None) -> None:
        self._line = list(command) if command is not None else record_command(pair, out_dir, ffmpeg)
        self._folder = Path(out_dir)
        self._process: subprocess.Popen | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self) -> None:
        if self.running:
            return
        self._folder.mkdir(parents=True, exist_ok=True)
        try:
            self._process = subprocess.Popen(self._line, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))  # noqa: S603
        except OSError as error:
            raise VideoSourceError(f"{self._line[0]} could not be started: {error}") from None

    def stop(self, timeout: float = 5.0) -> int | None:
        """Ends the recording (a polite stop first, then a kill) and returns the exit status."""
        process = self._process
        if process is None:
            return None
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        self._process = None
        return process.returncode
