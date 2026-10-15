"""HTTP transport. Tests pass a fake transport and never open a socket."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol

RETRYABLE_STATUS = frozenset({408, 409, 429, 500, 502, 503, 504})


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes
    timeout_s: float


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes
    latency_seconds: float


class Transport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse: ...


class TransportError(Exception):
    """A socket, DNS, or timeout failure before an HTTP status arrived."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class HttpCallError(Exception):
    """The provider responded with an error status or an unreadable body."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None,
        retryable: bool,
        latency_seconds: float = 0.0,
        usage: Mapping[str, int] | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retryable = retryable
        self.latency_seconds = latency_seconds
        self.usage = dict(usage or {})
        self.retry_after_s = retry_after_s


class UrllibTransport:
    """Stdlib client used only when a live adapter is actually called."""

    def send(self, request: HttpRequest) -> HttpResponse:
        outbound = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(outbound, timeout=request.timeout_s) as response:
                body = response.read()
                status = int(response.status)
                headers = {key: value for key, value in response.headers.items()}
        except urllib.error.HTTPError as exc:
            body = exc.read()
            latency = time.perf_counter() - started
            headers = {key: value for key, value in (exc.headers.items() if exc.headers else [])}
            return HttpResponse(status=int(exc.code), headers=headers, body=body, latency_seconds=latency)
        except TimeoutError as exc:
            raise TransportError("provider request timed out", retryable=True) from exc
        except urllib.error.URLError as exc:
            reason = exc.reason
            timed_out = isinstance(reason, TimeoutError) or "timed out" in str(reason).lower()
            message = "provider request timed out" if timed_out else "provider request failed"
            raise TransportError(message, retryable=True) from exc
        latency = time.perf_counter() - started
        return HttpResponse(status=status, headers=headers, body=body, latency_seconds=latency)


def dump_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def read_json_object(body: bytes) -> dict[str, object]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpCallError(
            "provider response was not JSON",
            status=200,
            retryable=False,
        ) from exc
    if not isinstance(parsed, dict):
        raise HttpCallError(
            "provider response JSON must be an object",
            status=200,
            retryable=False,
        )
    return parsed


def error_text(body: bytes) -> str:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body.decode("utf-8", errors="replace")[:300]
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("status") or error
            return str(message)[:300]
        if isinstance(error, str):
            return error[:300]
        message = parsed.get("message")
        if isinstance(message, str):
            return message[:300]
    return body.decode("utf-8", errors="replace")[:300]


def retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw = None
    for key, value in headers.items():
        if key.lower() == "retry-after":
            raw = value
            break
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return seconds


def status_error(response: HttpResponse) -> HttpCallError:
    return HttpCallError(
        f"provider HTTP {response.status}: {error_text(response.body)}",
        status=response.status,
        retryable=response.status in RETRYABLE_STATUS,
        latency_seconds=response.latency_seconds,
        retry_after_s=retry_after_seconds(response.headers),
    )
