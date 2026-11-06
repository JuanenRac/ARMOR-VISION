"""The client that carries the context of the server to the live service.

The server (ARMOR-SERVER) keeps the counting lines of each camera and lists them under `cameras[].lines` of `GET /api/v1/ai/context`; the live service takes them with `POST /context`.
Nothing connected the two, so this does: it asks the server for its context (with the token of the observation service), checks that what came back is a JSON object of a bounded size
and hands it to the service (with the token of the service). It never follows a redirect (a token is not sent to another address), never prints a token, and runs only when it is told to
(the `sync-context` command): the service itself still does not know where the server is.
"""
from __future__ import annotations

import json
import os
import re
import ssl
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

AI_TOKEN_ENV = "ARMOR_AI_TOKEN"
_TOKEN = re.compile(r"^[A-Za-z0-9._~+/=-]{24,200}$")
CONTEXT_ROUTE = "/api/v1/ai/context"


class SyncError(Exception):
    """One round could not be done; the message never holds a token."""


@dataclass(frozen=True)
class SyncSettings:
    server_url: str
    service_url: str
    ai_token: str
    service_token: str | None
    timeout_s: float = 10.0
    max_bytes: int = 262_144
    ca_file: str | None = None


def read_token(file: str | None, env_name: str, environ: dict[str, str] | None = None) -> str | None:
    """A token from a file or from the environment (both at once is an error), or None when there is none. Too short or odd characters is an error; nothing here prints it."""
    env = os.environ if environ is None else environ
    from_env = env.get(env_name, "").strip()
    if file is not None and from_env:
        raise SyncError(f"the token is given twice: by the file and by {env_name}")
    token = from_env
    if file is not None:
        try:
            token = Path(file).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            raise SyncError(f"cannot read the token file {file}: {type(exc).__name__}") from None
    if not token:
        return None
    if not _TOKEN.match(token):
        raise SyncError("a token must be 24 to 200 characters of letters, digits and . _ ~ + / = -")
    return token


def check_url(url: str, what: str) -> str:
    """An http or https address with a host, no sign-in inside it, no query and no fragment; returned without a trailing slash."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise SyncError(f"{what} must be an http or https address with a host and nothing else")
    return url.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:   # a token is never sent on to an address nobody configured
        return None


def _opener(settings: SyncSettings) -> urllib.request.OpenerDirector:
    handlers: list[Any] = [_NoRedirect()]
    if settings.ca_file:
        try:
            handlers.append(urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=settings.ca_file)))
        except (OSError, ssl.SSLError) as exc:
            raise SyncError(f"cannot use the certificate file: {type(exc).__name__}") from None
    return urllib.request.build_opener(*handlers)


def _call(opener: urllib.request.OpenerDirector, request: urllib.request.Request, settings: SyncSettings) -> tuple[int, bytes]:
    try:
        with opener.open(request, timeout=settings.timeout_s) as response:
            body = response.read(settings.max_bytes + 1)
            status = response.status
    except urllib.error.HTTPError as error:
        try:
            body, status = error.read(settings.max_bytes + 1), error.code
        finally:
            error.close()
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SyncError(f"cannot reach {request.host}: {type(reason).__name__}") from None
    if len(body) > settings.max_bytes:
        raise SyncError(f"the answer of {request.host} is over {settings.max_bytes} bytes")
    return status, body


def fetch_context(settings: SyncSettings, opener: urllib.request.OpenerDirector | None = None) -> dict[str, Any]:
    """The context of the server: 200 and a JSON object, or an error."""
    request = urllib.request.Request(settings.server_url + CONTEXT_ROUTE, headers={"Authorization": f"Bearer {settings.ai_token}", "Accept": "application/json"})
    status, body = _call(opener or _opener(settings), request, settings)
    if status != 200:
        raise SyncError(f"the server answered {status} to the context request")
    try:
        context = json.loads(body.decode("utf-8"), parse_constant=lambda name: (_ for _ in ()).throw(ValueError(name)))
    except (ValueError, UnicodeDecodeError):
        raise SyncError("the context of the server is not JSON") from None
    if not isinstance(context, dict) or not isinstance(context.get("cameras", []), list):
        raise SyncError("the context of the server has no list of cameras")
    return context


def push_context(settings: SyncSettings, context: dict[str, Any], opener: urllib.request.OpenerDirector | None = None) -> dict[str, Any]:
    """Hands the context to the service; its answer ({"cameras": n, "ignored": m}) or an error (503 means the pipeline is off)."""
    data = json.dumps(context, sort_keys=True).encode("utf-8")
    headers = {"Content-Type": "application/json", "Content-Length": str(len(data))}
    if settings.service_token:
        headers["Authorization"] = f"Bearer {settings.service_token}"
    status, body = _call(opener or _opener(settings), urllib.request.Request(settings.service_url + "/context", data=data, headers=headers, method="POST"), settings)
    if status != 200:
        raise SyncError(f"the service answered {status} to the context")
    try:
        answer = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise SyncError("the answer of the service is not JSON") from None
    return answer if isinstance(answer, dict) else {}


def sync_once(settings: SyncSettings) -> dict[str, Any]:
    """One round: ask the server, give the service. The answer of the service."""
    opener = _opener(settings)
    return push_context(settings, fetch_context(settings, opener), opener)


def run_forever(settings: SyncSettings, interval_s: float, stop: threading.Event, say: Callable[[str], None] = print) -> int:
    """Repeats the round every `interval_s` seconds until `stop` is set. It says the first round that works and the first one after a failure, and the first failure of a series; the rest is silent."""
    state = ""
    while not stop.is_set():
        try:
            answer = sync_once(settings)
            if state != "ok":
                say(f"context handed to the service: {answer.get('cameras', 0)} camera(s), {answer.get('ignored', 0)} left out")
            state = "ok"
        except SyncError as exc:
            if state != "failing":
                say(f"error: {exc}")
            state = "failing"
        stop.wait(interval_s)
    return 0
