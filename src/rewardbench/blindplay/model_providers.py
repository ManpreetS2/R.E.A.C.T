"""Wire formats for model providers, and the only transport that exists: an offline one.

TRUSTED HOST SIDE. **This file contains no network code, reads no credentials and imports no provider SDK; tests pin
that.** An adapter only translates between the gateway's neutral request and one provider's JSON. A transport carries
that JSON. The only transport here is ``OfflineTransport``, which calls a Python function in this process.

``AnthropicMessagesAdapter`` is written from the documented Messages API format and has **never been exercised against
the real API**. The only code that could send it is ``live_transport.py``, behind a gate that is closed:
``model_gateway.LIVE_CALLS_PERMITTED`` is False, and opening it requires owner approval and pre-registration.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol

MOCK_DISCLAIMER = "MOCK PROVIDER: scripted replies, not a model. Nothing here measures AI ability."


class ProviderProtocolError(ValueError):
    """A provider's reply does not have the documented shape. Treated as a failed call; never interpreted."""


class TransportTimeout(TimeoutError):
    pass


@dataclass(frozen=True)
class TransportResponse:
    status: int
    body: Any
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    is_offline: bool

    def send(self, wire_request: dict[str, Any], timeout: float) -> TransportResponse: ...


class OfflineTransport:
    """Hands the request to a local function. Cannot reach anything else."""
    is_offline = True

    def __init__(self, handler: Callable[[dict[str, Any], float], TransportResponse]) -> None:
        self._handler = handler
        self.requests_sent = 0

    def send(self, wire_request: dict[str, Any], timeout: float) -> TransportResponse:
        self.requests_sent += 1
        return self._handler(wire_request, timeout)


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens


@dataclass(frozen=True)
class ProviderReply:
    """A provider's answer in neutral form. ``stop`` is one of: tool_use, end_turn, max_tokens, refusal, other."""
    text: str
    tool_calls: tuple[dict[str, Any], ...]
    stop: str
    usage: Usage | None                # None: the reply carried no trustworthy usage, so it is charged at worst case
    request_id: str | None = None
    model: str | None = None
    refusal_category: str | None = None
    discarded_blocks: tuple[str, ...] = ()
    thinking_tokens: int | None = None  # billed reasoning inside output_tokens, when the provider reports it


class ProviderAdapter(Protocol):
    provider_id: str
    wire_format: str
    is_model: bool

    def build_request(self, neutral: dict[str, Any]) -> dict[str, Any]: ...

    def parse_response(self, response: TransportResponse) -> ProviderReply: ...


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def parse_usage(raw: Any, *, input_key: str = "input_tokens", output_key: str = "output_tokens") -> Usage | None:
    """``None`` unless every reported number is a real non-negative integer: bad numbers must not lower a charge."""
    if not isinstance(raw, Mapping):
        return None
    tokens = _count(raw.get(input_key)), _count(raw.get(output_key))
    extras = [raw.get(k, 0) or 0 for k in ("cache_creation_input_tokens", "cache_read_input_tokens")]
    if None in tokens or any(_count(v) is None for v in extras):
        return None
    return Usage(tokens[0], tokens[1], extras[0], extras[1])


# ---------------------------------------------------------------------- mock wire format
class MockAdapter:
    """The gateway's neutral format as JSON, for offline verification. Keeps images as base64, as a real request must."""
    provider_id = "offline-mock"
    wire_format = "react.mock.v1"
    is_model = False

    def build_request(self, neutral: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(neutral))

    def parse_response(self, response: TransportResponse) -> ProviderReply:
        body = response.body
        if not isinstance(body, Mapping) or body.get("stop") not in ("tool_use", "end_turn", "max_tokens", "refusal", "other"):
            raise ProviderProtocolError("mock reply has no valid stop")
        text, calls = body.get("text", ""), body.get("tool_calls", [])
        if not isinstance(text, str) or not isinstance(calls, list):
            raise ProviderProtocolError("mock reply text or tool_calls have the wrong type")
        return ProviderReply(text=text, tool_calls=tuple(calls), stop=body["stop"], usage=parse_usage(body.get("usage")),
                             request_id=body.get("id"), model=body.get("model"))


def decode_images(wire: Any) -> list[bytes]:
    """Every image in a mock wire request, decoded. Proves that genuine PNG bytes reach the provider boundary."""
    found: list[bytes] = []
    if isinstance(wire, dict):
        if wire.get("type") == "image":
            found.append(base64.b64decode(wire["base64"]))
        for value in wire.values():
            found.extend(decode_images(value))
    elif isinstance(wire, list):
        for value in wire:
            found.extend(decode_images(value))
    return found


class MockVisionProvider:
    """Replays a fixed script of replies. **Never looks at the screenshots to choose an action**: it only checks that
    they arrived as real PNGs and records their hashes. Not a controller and not a model.

    A script item is a reply dict (``text``, ``tool_calls``, ``stop``; ``usage`` is filled in if absent), a
    ``TransportResponse`` (sent as it is), an exception (raised), or a callable taking the wire request and returning
    any of those. After the script ends, ``default`` is used; without one, the reply has no tool call.
    """

    def __init__(self, script: list[Any], *, model: str = "mock-vision-0", default: Any = None) -> None:
        self.script = list(script)
        self.model = model
        self.default = default
        self.requests: list[dict[str, Any]] = []
        self.images_received: list[list[str]] = []

    def __call__(self, wire: dict[str, Any], timeout: float) -> TransportResponse:
        images = decode_images(wire)
        assert all(p.startswith(b"\x89PNG\r\n\x1a\n") for p in images), "the gateway sent something that is not a PNG"
        self.images_received.append([hashlib.sha256(p).hexdigest() for p in images])
        self.requests.append(wire)
        item = self.script.pop(0) if self.script else self.default
        if callable(item):
            item = item(wire)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, TransportResponse):
            return item
        reply = dict(item or {"text": "", "tool_calls": [], "stop": "end_turn"})
        reply.setdefault("text", "")
        reply.setdefault("tool_calls", [])
        reply.setdefault("stop", "tool_use" if reply["tool_calls"] else "end_turn")
        reply.setdefault("id", f"mock-req-{len(self.requests)}")
        reply.setdefault("model", self.model)
        reply.setdefault("usage", self.usage_for(wire, reply))
        return TransportResponse(200, reply)

    @staticmethod
    def usage_for(wire: dict[str, Any], reply: dict[str, Any]) -> dict[str, int]:
        """Deterministic stand-in token counts: about 4 characters per token, about 1,229 tokens per 1280x720 image."""
        stripped = json.dumps(wire, default=str)
        images = decode_images(wire)
        base64_chars = sum(4 * ((len(p) + 2) // 3) for p in images)
        return {"input_tokens": max(1, (len(stripped) - base64_chars) // 4) + 1229 * len(images),
                "output_tokens": 1 + (len(reply.get("text", "")) + len(json.dumps(reply.get("tool_calls", [])))) // 4}


# ---------------------------------------------------------------------- Claude Messages API format (never called)
_ANTHROPIC_STOPS = {"tool_use": "tool_use", "end_turn": "end_turn", "max_tokens": "max_tokens", "refusal": "refusal"}
_ANTHROPIC_EFFORTS = ("low", "medium", "high", "xhigh", "max")


class AnthropicMessagesAdapter:
    """``POST /v1/messages`` JSON. Disabled in practice: there is no transport that could send it.

    Deliberate choices, each tied to the protocol (docs/OFFLINE_AI_GATEWAY.md):

    * **Thinking blocks are discarded, never replayed.** The last-four-screenshots policy rewrites earlier turns, and
      current Claude models reject replayed thinking blocks after such an edit on enforced accounts. The model keeps its
      visible text and tool calls, as protocol P1 §5 already says. The documentation also tells callers to echo thinking
      blocks during tool use, so dropping them is only safe if none exist: ``thinking="disabled"`` is the setting that
      fits P1 ("hidden reasoning is not requested"), and the only one the live gate accepts. Omitting ``thinking`` means
      adaptive thinking on current models.
    * No ``fallbacks``: a server-side fallback would change the model mid-session, breaking the pre-registered model id.
    * No provider-side tools, no betas, no prompt caching, no sampling parameters, ``tool_choice`` always ``auto``
      (forced tool use is rejected by current models, and steering a model to a tool would be a hint).
    """
    provider_id = "anthropic"
    wire_format = "anthropic.messages.2023-06-01"
    is_model = True

    def __init__(self, *, effort: str | None = None, thinking: str | None = None) -> None:
        if effort is not None and effort not in _ANTHROPIC_EFFORTS:
            raise ValueError(f"unknown effort {effort!r}")
        if thinking not in (None, "adaptive", "disabled"):
            raise ValueError(f"unknown thinking setting {thinking!r}")
        if thinking == "disabled" and effort in ("xhigh", "max"):
            raise ValueError("thinking cannot be disabled at effort xhigh or max")
        self.effort = effort
        self.thinking = thinking

    def settings(self) -> tuple[tuple[str, str], ...]:
        return tuple((k, v) for k, v in (("effort", self.effort), ("thinking", self.thinking)) if v is not None)

    def terminal_error(self, response: TransportResponse) -> str | None:
        """The monthly spend cap is a 429 with no retry-after that keeps failing until access resumes."""
        error = response.body.get("error") if isinstance(response.body, Mapping) else None
        details = error.get("details") if isinstance(error, Mapping) else None
        if response.status == 429 and isinstance(details, Mapping) and details.get("error_code") == "enforced_spend_limit_reached":
            return "provider_spend_cap"
        return None

    @staticmethod
    def _content(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        blocks = []
        for part in parts:
            if part["type"] == "text":
                if part["text"].strip():   # the API rejects empty or whitespace-only text blocks
                    blocks.append({"type": "text", "text": part["text"]})
            else:
                blocks.append({"type": "image", "source": {"type": "base64", "media_type": part["media_type"],
                                                           "data": part["base64"]}})
        return blocks

    def build_request(self, neutral: dict[str, Any]) -> dict[str, Any]:
        messages: list[dict[str, Any]] = []

        def user_blocks() -> list[dict[str, Any]]:
            if not messages or messages[-1]["role"] != "user":
                messages.append({"role": "user", "content": []})
            return messages[-1]["content"]

        for m in neutral["messages"]:
            if m["role"] == "assistant":
                blocks = self._content(m["content"]) + [
                    {"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
                    for c in m.get("tool_calls", [])]
                if blocks:   # an empty assistant turn is not representable; the next user text then simply follows
                    messages.append({"role": "assistant", "content": blocks})
            elif m["role"] == "tool":
                user_blocks().append({"type": "tool_result", "tool_use_id": m["tool_call_id"],
                                      "content": self._content(m["content"]), "is_error": bool(m.get("is_error"))})
            else:
                user_blocks().extend(self._content(m["content"]))
        request: dict[str, Any] = {
            "model": neutral["model"], "max_tokens": neutral["max_output_tokens"], "system": neutral["system"],
            "tools": [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
                      for t in neutral["tools"]],
            "tool_choice": {"type": "auto"}, "messages": messages,
        }
        if self.effort is not None:
            request["output_config"] = {"effort": self.effort}
        if self.thinking is not None:
            request["thinking"] = {"type": self.thinking}
        return request

    def parse_response(self, response: TransportResponse) -> ProviderReply:
        body = response.body
        if not isinstance(body, Mapping) or body.get("type") != "message" or not isinstance(body.get("content"), list):
            raise ProviderProtocolError("not a message object")
        text, calls, discarded = [], [], []
        for block in body["content"]:
            kind = block.get("type") if isinstance(block, Mapping) else None
            if kind == "text" and isinstance(block.get("text"), str):
                text.append(block["text"])
            elif kind == "tool_use":
                calls.append({"id": block.get("id"), "name": block.get("name"), "arguments": block.get("input")})
            elif isinstance(kind, str):
                discarded.append(kind)     # thinking, redacted_thinking, anything newer: never replayed or executed
            else:
                raise ProviderProtocolError("a content block has no type")
        stop_details = body.get("stop_details")
        headers = {k.lower(): v for k, v in response.headers.items()}
        usage = body.get("usage")
        details = usage.get("output_tokens_details") if isinstance(usage, Mapping) else None
        return ProviderReply(thinking_tokens=_count(details.get("thinking_tokens")) if isinstance(details, Mapping) else None,
                             text="\n".join(text), tool_calls=tuple(calls), stop=_ANTHROPIC_STOPS.get(body.get("stop_reason"), "other"),
                             usage=parse_usage(body.get("usage")), request_id=headers.get("request-id") or body.get("id"),
                             model=body.get("model"),
                             refusal_category=stop_details.get("category") if isinstance(stop_details, Mapping) else None,
                             discarded_blocks=tuple(discarded))


def b64_strict(text: str) -> bytes:
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValueError(f"not valid base64: {type(exc).__name__}") from None
