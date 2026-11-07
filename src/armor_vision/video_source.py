"""Grey frames from a video stream or file, read through ffmpeg.

A camera (or a recorded clip served as one) is read by `ffmpeg`, which scales every picture to a small grey frame and writes the bytes on its standard output; this module cuts
that stream into `motion.Frame`s, the form the movement model takes. It is a read-only source: it opens one stream, never writes to it and never sends a command to a camera.

Only `rtsp://` and `rtsps://` addresses and existing files are accepted, and an address that carries a user name or a password is refused: the credentials of a camera belong to
the proxy or the server that holds them, not to a command line that every process of the machine can read. ffmpeg is started without a shell and without reading its
standard input. Nothing here has been tried on a real camera: the bench plays a recorded clip through a test RTSP server.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from urllib.parse import urlparse

from .motion import Frame

MAX_WIDTH, MAX_HEIGHT = 1920, 1080
MAX_FPS = 30.0
SCHEMES = ("rtsp", "rtsps")


class VideoSourceError(ValueError):
    """The stream cannot be opened or stopped delivering pictures."""


def check_source(source: str) -> str:
    """The source as ffmpeg is given it: an rtsp(s) address without credentials, or the path of an existing file."""
    if not isinstance(source, str) or not source or any(ord(c) < 33 or ord(c) == 127 for c in source):
        raise VideoSourceError("the source is an address or a file name, with no spaces or control characters")
    parsed = urlparse(source)
    if parsed.scheme.lower() in SCHEMES:
        if parsed.username or parsed.password or "@" in parsed.netloc:
            raise VideoSourceError("the address carries a user name or a password: keep the credentials in the proxy or the server that holds them")
        if not parsed.hostname:
            raise VideoSourceError("the address has no host")
        return source
    if parsed.scheme and len(parsed.scheme) > 1:       # a one-letter scheme is a Windows drive
        raise VideoSourceError(f"only rtsp, rtsps and files are read, not {parsed.scheme}")
    if source.startswith("-") or not Path(source).is_file():
        raise VideoSourceError("the file does not exist")
    return str(Path(source).resolve())


def ffmpeg_command(source: str, width: int, height: int, fps: float, ffmpeg: str = "ffmpeg", transport: str = "tcp") -> list[str]:
    """The ffmpeg command line that writes `fps` grey pictures of `width` x `height` per second on its standard output."""
    for name, value, high in (("width", width, MAX_WIDTH), ("height", height, MAX_HEIGHT)):
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= high:
            raise VideoSourceError(f"{name} is a whole number from 1 to {high}")
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 0 < fps <= MAX_FPS:
        raise VideoSourceError(f"fps is a number above 0 and up to {MAX_FPS:g}")
    if transport not in ("tcp", "udp"):
        raise VideoSourceError("the RTSP transport is tcp or udp")
    checked = check_source(source)
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error"]
    if urlparse(checked).scheme.lower() in SCHEMES:
        command += ["-rtsp_transport", transport]
    return command + ["-i", checked, "-an", "-vf", f"fps={fps:g},scale={width}:{height},format=gray", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"]


def read_frames(source: str, width: int = 320, height: int = 180, fps: float = 5.0, max_frames: int | None = None, idle_timeout: float = 20.0,
                ffmpeg: str = "ffmpeg", transport: str = "tcp", command: Sequence[str] | None = None) -> Iterator[Frame]:
    """Yields grey frames until the stream ends, `max_frames` have been read or no picture arrives for `idle_timeout` seconds (then VideoSourceError).

    `command` replaces the ffmpeg command line (tests use a program that writes known pictures); it must write the same raw grey pictures."""
    if max_frames is not None and (isinstance(max_frames, bool) or not isinstance(max_frames, int) or max_frames < 1):
        raise VideoSourceError("max_frames is a whole number above 0")
    if not isinstance(idle_timeout, (int, float)) or isinstance(idle_timeout, bool) or idle_timeout <= 0:
        raise VideoSourceError("idle_timeout is a number of seconds above 0")
    line = list(command) if command is not None else ffmpeg_command(source, width, height, fps, ffmpeg, transport)
    size = width * height
    try:
        process = subprocess.Popen(line, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ))  # noqa: S603
    except OSError as error:
        raise VideoSourceError(f"{line[0]} could not be started: {error}") from None
    pictures: queue.Queue = queue.Queue(maxsize=8)
    stop = threading.Event()

    def pump() -> None:
        assert process.stdout is not None
        try:
            while not stop.is_set():
                data = process.stdout.read(size)
                if len(data) < size:
                    pictures.put(None)
                    return
                pictures.put(data)
        except (OSError, ValueError):
            pictures.put(None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    count = 0
    try:
        while max_frames is None or count < max_frames:
            try:
                data = pictures.get(timeout=idle_timeout)
            except queue.Empty:
                raise VideoSourceError(f"no picture for {idle_timeout:g} s") from None
            if data is None:
                break
            count += 1
            yield Frame(width, height, data)
        if count == 0:
            try:
                status = process.wait(3)
            except subprocess.TimeoutExpired:
                status = 0
            if status != 0:
                detail = (process.stderr.read(400) if process.stderr else b"").decode("utf-8", "replace").strip()
                raise VideoSourceError(f"the stream gave no picture ({detail or 'status ' + str(status)})")
    finally:
        stop.set()
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()
