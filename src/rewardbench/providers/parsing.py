"""Parse a model reply into a controller object. Does not score the flight."""

from __future__ import annotations

import json
import math
import re
from typing import Any

MAX_RESPONSE_CHARS = 100_000

# Keys that only make sense if a later stage executed model-authored code.
FORBIDDEN_KEYS = frozenset(
    {
        "code",
        "python",
        "exec",
        "eval",
        "script",
        "source",
        "command",
        "shell",
        "pickle",
        "lambda",
        "import",
        "__import__",
        "builtins",
        "globals",
        "locals",
        "compile",
        "function",
        "callable",
    }
)

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


def parse_controller(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(parameters, parse_error)``. A parse failure is not an exception."""

    if len(text) > MAX_RESPONSE_CHARS:
        return None, f"response exceeds {MAX_RESPONSE_CHARS} characters"
    try:
        candidate = _extract_object(text)
    except ValueError as exc:
        return None, str(exc)
    if candidate is None:
        return None, "response did not contain a JSON object"
    try:
        _reject_unsafe(candidate)
    except ValueError as exc:
        return None, str(exc)
    return candidate, None


def _extract_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    fenced = _FENCE.fullmatch(stripped)
    body = fenced.group(1).strip() if fenced else stripped
    if not body.startswith("{"):
        if body.startswith("["):
            raise ValueError("controller JSON must be an object")
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(body)
    except json.JSONDecodeError:
        return None
    if body[end:].strip():
        raise ValueError("controller JSON must be the only value in the response")
    if not isinstance(value, dict):
        raise ValueError("controller JSON must be an object")
    return value


def _reject_unsafe(value: Any, depth: int = 0) -> None:
    if depth > 8:
        raise ValueError("controller JSON is nested too deeply")
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("controller keys must be strings")
            lowered = key.lower()
            if key.startswith("_") or lowered in FORBIDDEN_KEYS:
                raise ValueError(f"forbidden controller field {key!r}")
            _reject_unsafe(nested, depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise ValueError("controller list is too long")
        for nested in value:
            _reject_unsafe(nested, depth + 1)
        return
    if isinstance(value, str):
        if len(value) > 200:
            raise ValueError("controller string is too long")
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("controller contains a non-finite number")
        return
    raise ValueError(f"controller contains unsupported value type {type(value).__name__}")
