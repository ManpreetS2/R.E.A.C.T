"""Provider-neutral model gateway: everything between a vision model and the isolated player.

TRUSTED HOST SIDE; never imported or reachable from inside the sandbox. The gateway owns the conversation. The player
sends only ``{"tool": "model"}`` and gets back validated tool calls, and the host forwards a game action only if it is
exactly the next call the model made. So a compromised player cannot put words in the model's mouth or press a key the
model did not ask for.

    model call:  stop checks -> build request from the host's own history -> last-N-screenshots window -> outbound guard
                 -> token estimate -> context limit -> worst-case cost -> durable reservation (or refuse, no call)
                 -> transport (with a hard timeout) -> classify -> settle -> validate tool calls -> transcript

What it can see is limited by construction: this module imports nothing from ``referee``, ``session``, ``serve`` or
``replay`` and receives only player-contract messages, whose exact field set it re-checks. **It holds no credentials,
and it refuses any transport that is not offline while ``LIVE_CALLS_PERMITTED`` is False.**

Every call attempt is one hash-chained transcript record: exactly what was sent (images by sha256), the reservation,
the outcome and the charge. Provider error text and anything resembling a credential are redacted before logging, and
the player only ever sees fixed messages.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import zlib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Mapping

from rewardbench.blindplay import contract, model_providers as providers, spend_ledger

# Flipping this is the owner-approved act that makes real calls possible. It stays False until a first model session
# is explicitly authorized; a test pins it, and a live transport does not exist either.
LIVE_CALLS_PERMITTED = False

GATEWAY_SCHEMA = "react.blindplay.gateway.v1"
TOOL_RESULT_COUNTERS = ("episode", "episode_frame", "episode_frame_budget", "max_episodes", "frames_advanced",
                        "episode_ended", "session_over")
OMITTED_IMAGE_NOTE = "[earlier screenshot omitted]"
NO_TOOL_NOTE = "Use a tool to continue."
ENDED_MESSAGE = "the model session has ended"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CALL_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_SECRET = re.compile(r"(sk-|sk_|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|AKIA|ASIA|AIza|xox[abposr]-|hf_|r8_|eyJ)"
                     r"[A-Za-z0-9_\-.]{6,}|(?i:bearer\s+)[A-Za-z0-9_\-.]{6,}")
# Status codes that the provider documents as "not processed": nothing to pay for.
_NOT_BILLED_RETRYABLE = {429, 529}
_UNCERTAIN_RETRYABLE = {408, 409, 500, 502, 503, 504}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def redact(text: Any, limit: int = 500) -> str:
    return _SECRET.sub("[redacted]", str(text))[:limit]


class GatewayStopped(RuntimeError):
    """The model session is over; ``reason`` is recorded. No provider call was or will be made after this."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GatewayRejected(ValueError):
    """A player request out of sequence. The session goes on; the player gets the fixed message."""


class InvalidScreenshot(ValueError):
    pass


class LiveCallsDisabled(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelPricing:
    """USD per million tokens. ``source`` says where the numbers came from; prices are never assumed current."""
    input_per_mtok: Decimal
    output_per_mtok: Decimal
    source: str
    # Above this many input tokens some models charge a higher rate for the whole call.
    threshold_input_tokens: int | None = None
    over_threshold_input_per_mtok: Decimal | None = None
    over_threshold_output_per_mtok: Decimal | None = None
    cache_write_multiplier: Decimal = Decimal(2)    # upper bound; the gateway does not enable caching

    def __post_init__(self) -> None:
        for name in ("input_per_mtok", "output_per_mtok", "over_threshold_input_per_mtok",
                     "over_threshold_output_per_mtok", "cache_write_multiplier"):
            if getattr(self, name) is not None:
                object.__setattr__(self, name, spend_ledger.usd(getattr(self, name)))
        if (self.threshold_input_tokens is None) != (self.over_threshold_input_per_mtok is None) or \
                (self.threshold_input_tokens is None) != (self.over_threshold_output_per_mtok is None):
            raise ValueError("a price threshold needs both over-threshold rates")

    def cost(self, usage: providers.Usage) -> Decimal:
        over = self.threshold_input_tokens is not None and usage.total_input_tokens > self.threshold_input_tokens
        rate_in = self.over_threshold_input_per_mtok if over else self.input_per_mtok
        rate_out = self.over_threshold_output_per_mtok if over else self.output_per_mtok
        billable_input = usage.input_tokens + usage.cache_read_tokens + \
            Decimal(usage.cache_write_tokens) * self.cache_write_multiplier
        return spend_ledger.usd((Decimal(billable_input) * rate_in + Decimal(usage.output_tokens) * rate_out) / 1_000_000)


@dataclass(frozen=True)
class GatewayConfig:
    """Everything a session is allowed to do. Fixed for the session and hashed into its records.

    The spend caps have no defaults: nobody gets a budget by forgetting to set one.
    """
    provider_id: str
    model_id: str
    pricing: ModelPricing
    session_cap_usd: Decimal
    cumulative_cap_usd: Decimal
    keyset: str = contract.V2.keyset
    # protocol P1 proposals (docs/BLIND_PLAY_PROTOCOL_V1_DRAFT.md section 3)
    max_episodes: int = 10
    episode_frame_budget: int = 8000
    max_model_calls: int = 150
    max_game_requests: int = 1000
    max_tool_calls_per_reply: int = 8
    max_images_per_call: int = 4
    max_wall_seconds: float = 7200.0
    max_consecutive_provider_errors: int = 3
    max_consecutive_invalid_replies: int = 10
    # output and context limits
    max_output_tokens: int = 2048
    max_reply_text_chars: int = 20000
    max_tool_argument_bytes: int = 1024
    max_context_tokens: int = 90000
    max_request_bytes: int = 20 * 1024 * 1024
    # image checks and the cost of one image, as an upper bound for the pre-call estimate
    image_width: int = 1280
    image_height: int = 720
    max_image_bytes: int = 5 * 1024 * 1024
    image_tokens_upper_bound: int = 1600
    # transport behaviour
    provider_timeout_seconds: float = 120.0
    max_retry_wait_seconds: float = 60.0

    def __post_init__(self) -> None:
        session, cumulative = spend_ledger.usd(self.session_cap_usd), spend_ledger.usd(self.cumulative_cap_usd)
        if session <= 0 or cumulative <= 0 or session > cumulative:
            raise ValueError("spend caps must be positive and the session cap must not exceed the cumulative cap")
        contract.version_for(self.keyset)
        if self.keyset == contract.V1.keyset:
            raise ValueError("keyset.v1 holds the undocumented 4x speed key and stays for replaying old sessions; "
                             "offering it to a model would need its own owner approval and a code change here")
        for name in ("max_episodes", "episode_frame_budget", "max_model_calls", "max_game_requests", "max_tool_calls_per_reply",
                     "max_images_per_call", "max_output_tokens", "max_context_tokens", "max_consecutive_provider_errors",
                     "max_consecutive_invalid_replies"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        threshold = self.pricing.threshold_input_tokens
        if threshold is not None and self.max_context_tokens > threshold:
            raise ValueError(f"max_context_tokens {self.max_context_tokens} is above the {threshold}-token price threshold")

    def canonical(self) -> dict[str, Any]:
        return json.loads(json.dumps(asdict(self), default=str, sort_keys=True))

    def sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.canonical(), sort_keys=True).encode()).hexdigest()


def validate_screenshot(image: Any, *, width: int, height: int, max_bytes: int) -> bytes:
    """A complete structural check of a screenshot about to be sent to a paid API. Returns the PNG bytes."""
    if not isinstance(image, Mapping) or set(image) != contract.IMAGE_FIELDS:
        raise InvalidScreenshot("image fields differ from the contract")
    if image["media_type"] != "image/png" or image["width"] != width or image["height"] != height:
        raise InvalidScreenshot("declared type or size differs")
    try:
        png = providers.b64_strict(image["base64"])
    except ValueError as exc:
        raise InvalidScreenshot(str(exc)) from None
    if len(png) > max_bytes:
        raise InvalidScreenshot(f"larger than {max_bytes} bytes")
    if hashlib.sha256(png).hexdigest() != image["sha256"]:
        raise InvalidScreenshot("sha256 mismatch")
    if not png.startswith(PNG_SIGNATURE):
        raise InvalidScreenshot("not a PNG")
    pos, first, ended = len(PNG_SIGNATURE), True, False
    while pos < len(png):
        if ended or pos + 12 > len(png):
            raise InvalidScreenshot("data after IEND or a truncated chunk")
        length = int.from_bytes(png[pos:pos + 4], "big")
        kind = png[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(png) or zlib.crc32(png[pos + 4:pos + 8 + length]) != int.from_bytes(png[pos + 8 + length:end], "big"):
            raise InvalidScreenshot("bad chunk length or CRC")
        if first:
            if kind != b"IHDR" or (int.from_bytes(png[pos + 8:pos + 12], "big"),
                                   int.from_bytes(png[pos + 12:pos + 16], "big")) != (width, height):
                raise InvalidScreenshot("IHDR differs from the declared size")
            first = False
        ended = kind == b"IEND"
        pos = end
    if not ended:
        raise InvalidScreenshot("no IEND")
    return png


@dataclass
class _BatchEntry:
    call: dict[str, Any]
    executable: bool
    canonical: tuple[str, contract.Act | None] | None = None
    result: dict[str, Any] | None = None


class VisionGateway:
    """One model session. ``turn`` is one model reply; ``authorize_game``/``record_game`` tie the game to that reply."""
    owns_history = True

    def __init__(self, config: GatewayConfig, adapter: providers.ProviderAdapter, transport: providers.Transport,
                 ledger: spend_ledger.SpendLedger, *, session_id: str, sink: Callable[[dict[str, Any]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        if not getattr(transport, "is_offline", False) and not LIVE_CALLS_PERMITTED:
            raise LiveCallsDisabled("live model calls are disabled: only an offline transport may be used")
        if transport.is_offline and ledger.mode != spend_ledger.MODE_OFFLINE_MOCK:
            raise LiveCallsDisabled("an offline transport must not write to a live ledger")
        if adapter.provider_id != config.provider_id:
            raise ValueError("adapter and configuration name different providers")
        self.config = config
        self.adapter = adapter
        self.transport = transport
        self.ledger = ledger
        self.session_id = session_id
        self.version = contract.version_for(config.keyset)
        self.tools = [dict(t) for t in self.version.tools]
        self.tools_sha256 = hashlib.sha256(json.dumps(self.tools, sort_keys=True).encode()).hexdigest()
        self.is_model = bool(adapter.is_model and not transport.is_offline)
        self.name = f"{adapter.wire_format}:{config.model_id}" if self.is_model else f"offline:{adapter.provider_id}:{config.model_id} (NOT A MODEL)"
        self._sink = sink or (lambda record: None)
        self._clock, self._sleep = clock, sleep
        self._started = clock()
        self._messages: list[dict[str, Any]] = []
        self._images: dict[int, str] = {}             # seq -> base64, only those still inside the window
        self._batch: list[_BatchEntry] = []
        self._seen_call_ids: set[str] = set()
        self._batch_closed = False                    # the episode ended, so the rest of the batch is not executed
        self.stop_reason: str | None = None
        self.counts = {"model_calls": 0, "provider_errors": 0, "invalid_replies": 0, "tool_calls_requested": 0,
                       "tool_calls_rejected": 0, "tool_calls_executed": 0, "game_requests_refused": 0,
                       "screenshots_received": 0, "budget_refusals": 0}
        self._consecutive_errors = 0
        self._consecutive_invalid = 0
        self._charged = Decimal(0)
        self._chain = "0" * 64
        self._records = 0

    # ------------------------------------------------------------------ records
    def bind_sink(self, sink: Callable[[dict[str, Any]], None]) -> None:
        self._sink = sink

    def _record(self, record: dict[str, Any]) -> None:
        self._records += 1
        body = dict(record, schema=GATEWAY_SCHEMA, index=self._records, utc=_now(), prev_sha256=self._chain)
        self._chain = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        self._sink(dict(body, sha256=self._chain))

    def manifest(self) -> dict[str, Any]:
        """Provenance for the session record. Contains no secrets: this object never holds any."""
        return {"schema": GATEWAY_SCHEMA, "name": self.name, "is_model": self.is_model, "provider_id": self.config.provider_id,
                "wire_format": self.adapter.wire_format, "model_id": self.config.model_id, "transport_offline": bool(self.transport.is_offline),
                "live_calls_permitted": LIVE_CALLS_PERMITTED, "config": self.config.canonical(), "config_sha256": self.config.sha256(),
                "contract": {"protocol": self.version.protocol, "keyset": self.version.keyset, "tools_sha256": self.tools_sha256},
                "session_id": self.session_id, "stop_reason": self.stop_reason, "counts": dict(self.counts),
                "charged_usd": str(self._charged), "ledger_mode": self.ledger.mode, "transcript_records": self._records,
                "transcript_tip_sha256": self._chain,
                "disclaimer": providers.MOCK_DISCLAIMER if not self.adapter.is_model else None}

    def stop(self, reason: str) -> GatewayStopped:
        if self.stop_reason is None:
            self.stop_reason = reason
            self._record({"event": "stop", "reason": reason, "counts": dict(self.counts), "charged_usd": str(self._charged)})
        return GatewayStopped(self.stop_reason)

    # ------------------------------------------------------------------ the game side
    def authorize_game(self, tool: str, act: contract.Act | None) -> None:
        """Raise ``GatewayRejected`` unless this game request is the opening observe or the model's next tool call."""
        if tool == "brief":
            return
        if self.stop_reason is not None:
            raise self._refuse("the model session has ended")
        if not self._messages:
            if tool == "observe":
                return
            raise self._refuse("the session starts with an observe")
        entry = self._next_executable()
        if entry is None or self._batch_closed:
            raise self._refuse("no tool call is waiting to be executed")
        if entry.canonical != (tool, act):
            raise self._refuse("this is not the tool call the model made")

    def _refuse(self, message: str) -> GatewayRejected:
        self.counts["game_requests_refused"] += 1
        self._record({"event": "game_request_refused", "reason": message})
        return GatewayRejected(message)

    def _next_executable(self) -> _BatchEntry | None:
        return next((e for e in self._batch if e.executable and e.result is None), None)

    def record_game(self, response: Mapping[str, Any]) -> None:
        """Take the referee's reply to an authorized request. Fails closed on anything outside the player contract."""
        fields = set(response)
        if fields == contract.BRIEF_FIELDS:
            return
        if fields == contract.ERROR_FIELDS:
            parts = [{"type": "text", "text": json.dumps({"error": redact(response["error"])})}]
            self._attach_result(parts, is_error=True, ended=True, session_over=False)
            return
        if fields != contract.OBSERVATION_FIELDS:
            raise self.stop("contract_violation")   # never forward a reply with extra (possibly privileged) fields
        try:
            validate_screenshot(response["image"], width=self.config.image_width, height=self.config.image_height,
                                max_bytes=self.config.max_image_bytes)
        except InvalidScreenshot as exc:
            self._record({"event": "invalid_screenshot", "seq": response.get("seq"), "detail": str(exc)})
            raise self.stop("invalid_screenshot") from None
        seq, image = response["seq"], response["image"]
        if type(seq) is not int or seq in self._images or \
                not all(type(response[k]) in (int, bool) for k in TOOL_RESULT_COUNTERS):
            raise self.stop("contract_violation")
        self.counts["screenshots_received"] += 1
        self._images[seq] = image["base64"]
        counters = {k: response[k] for k in TOOL_RESULT_COUNTERS}
        image_part = {"type": "image", "media_type": image["media_type"], "seq": seq, "sha256": image["sha256"]}
        if not self._messages:
            self._messages.append({"role": "user", "content": [{"type": "text", "text": contract.OBJECTIVE}, image_part]})
        else:
            self._attach_result([{"type": "text", "text": json.dumps(counters)}, image_part], is_error=False,
                                ended=bool(response["episode_ended"]), session_over=bool(response["session_over"]))
        if response["session_over"]:
            self.stop("session_over")
        self._trim_images()

    def _attach_result(self, parts: list[dict[str, Any]], *, is_error: bool, ended: bool, session_over: bool) -> None:
        entry = self._next_executable()
        if entry is None:
            raise self.stop("contract_violation")
        entry.result = {"parts": parts, "is_error": is_error}
        self.counts["tool_calls_executed"] += 1
        if ended or session_over:
            self._batch_closed = True

    def _trim_images(self) -> None:
        for seq in sorted(self._images)[:-self.config.max_images_per_call]:
            del self._images[seq]

    def _flush_batch(self) -> None:
        """Add tool results to the history, in the model's call order. Calls cut off by the end of an episode get a fixed
        note, so a key meant for the previous episode can never land in the next one."""
        for entry in self._batch:
            result = entry.result or {"parts": [{"type": "text", "text": json.dumps({"error": "not executed: the episode ended"})}],
                                      "is_error": True}
            self._messages.append({"role": "tool", "tool_call_id": entry.call["id"], "content": result["parts"],
                                   "is_error": result["is_error"]})
        self._batch = []
        self._batch_closed = False

    # ------------------------------------------------------------------ request
    def _request(self) -> dict[str, Any]:
        """The neutral request, built only from the host's history. Older screenshots become a text note."""
        keep = set(sorted(self._images)[-self.config.max_images_per_call:])
        messages = []
        for m in self._messages:
            parts = []
            for part in m["content"]:
                if part["type"] != "image":
                    parts.append(dict(part))
                elif part["seq"] in keep:
                    parts.append(dict(part, base64=self._images[part["seq"]]))
                else:
                    parts.append({"type": "text", "text": OMITTED_IMAGE_NOTE})
            messages.append(dict(m, content=parts))
        return {"model": self.config.model_id, "system": contract.OBJECTIVE, "tools": self.tools,
                "max_output_tokens": self.config.max_output_tokens, "messages": messages}

    def _guard(self, request: dict[str, Any]) -> None:
        """Last check before anything can leave: the invariants hold whatever the code above did."""
        images = [p for m in request["messages"] for p in m["content"] if p["type"] == "image"]
        if len(images) > self.config.max_images_per_call:
            raise self.stop("outbound_guard_too_many_images")
        if request["system"] != contract.OBJECTIVE or request["tools"] != list(self.version.tools):
            raise self.stop("outbound_guard_prompt_changed")
        if request["model"] != self.config.model_id or request["max_output_tokens"] != self.config.max_output_tokens:
            raise self.stop("outbound_guard_parameters_changed")
        for m in request["messages"]:
            if set(m) - {"role", "content", "tool_calls", "tool_call_id", "is_error"}:
                raise self.stop("outbound_guard_message_fields")
            for part in m["content"]:
                allowed = {"type", "text"} if part["type"] == "text" else {"type", "media_type", "seq", "sha256", "base64"}
                if set(part) != allowed:
                    raise self.stop("outbound_guard_part_fields")

    def estimate_input_tokens(self, request: dict[str, Any]) -> int:
        """A deliberate overestimate: about 2 characters per token for text and schemas, an upper bound per image."""
        images = 0
        text = len(json.dumps(request["tools"])) + len(request["system"])
        for m in request["messages"]:
            text += 32 + len(json.dumps(m.get("tool_calls", [])))
            for part in m["content"]:
                if part["type"] == "image":
                    images += 1
                else:
                    text += len(part["text"].encode("utf-8"))
        return text // 2 + 256 + images * self.config.image_tokens_upper_bound

    def _worst_case(self, estimate: int) -> Decimal:
        return self.config.pricing.cost(providers.Usage(estimate, self.config.max_output_tokens))

    # ------------------------------------------------------------------ turn
    def turn(self) -> dict[str, Any]:
        """One model reply. Returns only the tool calls the player must execute. Raises ``GatewayStopped`` at the end."""
        if self.stop_reason is not None:
            raise GatewayStopped(self.stop_reason)
        if not self._messages:
            raise GatewayRejected("the session starts with an observe")
        if self._next_executable() is not None and not self._batch_closed:
            raise GatewayRejected("tool calls are still waiting to be executed")
        self._flush_batch()
        while True:
            reply = self._attempt()
            if reply is not None:
                return self._accept(reply)

    def _check_limits(self) -> None:
        if self._clock() - self._started > self.config.max_wall_seconds:
            raise self.stop("wall_clock_limit")
        if self.counts["model_calls"] >= self.config.max_model_calls:
            raise self.stop("model_call_limit")
        if self._consecutive_errors >= self.config.max_consecutive_provider_errors:
            raise self.stop("consecutive_provider_errors")
        if self._consecutive_invalid >= self.config.max_consecutive_invalid_replies:
            raise self.stop("consecutive_invalid_replies")

    def _send(self, wire: dict[str, Any]) -> providers.TransportResponse:
        """Runs the transport under a hard timeout: a provider that hangs cannot hang the session."""
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["response"] = self.transport.send(wire, self.config.provider_timeout_seconds)
            except BaseException as exc:  # noqa: BLE001 - passed to the caller's thread below
                outcome["error"] = exc

        thread = threading.Thread(target=run, daemon=True, name="gateway-transport")
        thread.start()
        thread.join(self.config.provider_timeout_seconds)
        if thread.is_alive():
            raise providers.TransportTimeout("provider did not answer in time")
        if "error" in outcome:
            raise outcome["error"]
        return outcome["response"]

    def _attempt(self) -> providers.ProviderReply | None:
        """One provider call with its budget gate. Returns ``None`` when the turn should be retried."""
        self._check_limits()
        request = self._request()
        self._guard(request)
        estimate = self.estimate_input_tokens(request)
        if estimate > self.config.max_context_tokens:
            raise self.stop("context_limit")
        wire = self.adapter.build_request(request)
        wire_bytes = json.dumps(wire, sort_keys=True).encode("utf-8")
        if len(wire_bytes) > self.config.max_request_bytes:
            raise self.stop("request_size_limit")
        worst = self._worst_case(estimate)
        call = self.counts["model_calls"] + 1
        shown = [{**{k: v for k, v in m.items() if k != "content"},
                  "content": [{k: v for k, v in p.items() if k != "base64"} for p in m["content"]]} for m in request["messages"]]
        record: dict[str, Any] = {"event": "model_call", "call": call, "model_id": self.config.model_id,
                                  "system": request["system"], "tools": [t["name"] for t in self.tools],
                                  "tools_sha256": self.tools_sha256, "messages": shown,
                                  "wire_sha256": hashlib.sha256(wire_bytes).hexdigest(), "wire_bytes": len(wire_bytes),
                                  "estimated_input_tokens": estimate, "worst_case_usd": str(worst)}
        try:
            reservation = self.ledger.reserve(session=self.session_id, call=call, worst_case=worst,
                                              session_cap=self.config.session_cap_usd,
                                              cumulative_cap=self.config.cumulative_cap_usd,
                                              detail={"wire_sha256": record["wire_sha256"], "estimated_input_tokens": estimate,
                                                      "max_output_tokens": self.config.max_output_tokens})
        except spend_ledger.BudgetExceeded as exc:
            self.counts["budget_refusals"] += 1
            self._record(dict(record, outcome={"kind": "refused_before_call", "scope": exc.scope, "detail": str(exc)}))
            raise self.stop(f"budget_exhausted_{exc.scope}") from None
        self.counts["model_calls"] = call
        record["reservation"] = reservation
        try:
            response = self._send(wire)
        except providers.TransportTimeout:
            return self._failed(record, reservation, worst, kind="timeout", detail="timed out")
        except Exception as exc:  # noqa: BLE001 - connection failures: the request may or may not have been processed
            return self._failed(record, reservation, worst, kind="transport_error", detail=type(exc).__name__)
        status = response.status
        if status != 200:
            return self._status_failure(record, reservation, worst, response)
        try:
            reply = self.adapter.parse_response(response)
        except providers.ProviderProtocolError as exc:
            return self._failed(record, reservation, worst, kind="malformed_reply", detail=redact(exc), status=status)
        return self._settle_reply(record, reservation, worst, reply)

    def _failed(self, record: dict[str, Any], reservation: str, worst: Decimal, *, kind: str, detail: str,
                status: int | None = None, retry_after: Any = None, charge_worst: bool = True) -> None:
        """A failed call. If the provider may have processed it, it stays charged at worst case until reconciled."""
        charged = worst if charge_worst else Decimal(0)
        self.ledger.settle(reservation, charged=charged, basis=f"{kind}:worst_case_unverified" if charge_worst else f"{kind}:not_billed",
                           detail={"status": status})
        self._charged += charged
        self.counts["provider_errors"] += 1
        self._consecutive_errors += 1
        self._record(dict(record, outcome={"kind": kind, "status": status, "detail": redact(detail), "charged_usd": str(charged)}))
        if self._consecutive_errors < self.config.max_consecutive_provider_errors:
            self._sleep(self._backoff(retry_after))
        return None

    def _backoff(self, retry_after: Any) -> float:
        try:
            wait = float(retry_after)
        except (TypeError, ValueError):
            wait = 2.0 ** self._consecutive_errors
        if wait != wait or wait < 0:
            wait = 2.0 ** self._consecutive_errors
        return min(wait, self.config.max_retry_wait_seconds)

    def _status_failure(self, record: dict[str, Any], reservation: str, worst: Decimal,
                        response: providers.TransportResponse) -> None:
        status = response.status
        headers = {str(k).lower(): v for k, v in response.headers.items()}
        detail = redact(response.body)
        if status in _NOT_BILLED_RETRYABLE:
            return self._failed(record, reservation, worst, kind="rate_limited" if status == 429 else "overloaded", detail=detail,
                                status=status, retry_after=headers.get("retry-after"), charge_worst=False)
        if status in _UNCERTAIN_RETRYABLE:
            return self._failed(record, reservation, worst, kind="server_error", detail=detail, status=status,
                                retry_after=headers.get("retry-after"))
        # 400, 401, 402, 403, 404, 413, ...: a retry would fail the same way. A rejected request is not billed.
        self.ledger.settle(reservation, charged=0, basis="rejected_by_provider:not_billed", detail={"status": status})
        self.counts["provider_errors"] += 1
        self._record(dict(record, outcome={"kind": "rejected_by_provider", "status": status, "detail": detail, "charged_usd": "0"}))
        raise self.stop(f"provider_rejected_{status}")

    def _settle_reply(self, record: dict[str, Any], reservation: str, worst: Decimal, reply: providers.ProviderReply):
        usage = reply.usage
        charged = self.config.pricing.cost(usage) if usage is not None else worst
        basis = "provider_usage" if usage is not None else "worst_case_usage_missing"
        self.ledger.settle(reservation, charged=charged, basis=basis,
                           detail={"usage": asdict(usage) if usage else None, "request_id": redact(reply.request_id, 128)})
        self._charged += charged
        outcome = {"kind": "reply", "stop": reply.stop, "request_id": redact(reply.request_id, 128), "provider_model": redact(reply.model, 128),
                   "usage": asdict(usage) if usage else None, "charged_usd": str(charged), "charge_basis": basis,
                   "discarded_blocks": list(reply.discarded_blocks), "refusal_category": redact(reply.refusal_category, 64) if reply.refusal_category else None,
                   "text": redact(reply.text, self.config.max_reply_text_chars),
                   "tool_calls": json.loads(redact_json(list(reply.tool_calls), 16384))}
        self._record(dict(record, outcome=outcome))
        if usage is None:
            raise self.stop("usage_missing")
        if reply.model != self.config.model_id:
            raise self.stop("model_mismatch")
        if usage.output_tokens > self.config.max_output_tokens:
            raise self.stop("output_limit_violated")
        if usage.total_input_tokens > self.config.max_context_tokens:
            raise self.stop("context_limit_exceeded_by_provider_count")
        if reply.stop == "refusal":
            raise self.stop("provider_refusal")
        self._consecutive_errors = 0
        return reply

    # ------------------------------------------------------------------ reply
    def _accept(self, reply: providers.ProviderReply) -> dict[str, Any]:
        calls, entries = self._validate_calls(reply)
        if calls is None:   # ids that cannot be answered: the reply cannot go into the history at all
            self.counts["invalid_replies"] += 1
            self._consecutive_invalid += 1
            self._messages.append({"role": "user", "content": [{"type": "text", "text": NO_TOOL_NOTE}]})
            self._check_limits()
            return {"protocol": self.version.protocol, "text": "", "tool_calls": []}
        text = reply.text[:self.config.max_reply_text_chars]
        message: dict[str, Any] = {"role": "assistant", "content": [{"type": "text", "text": text}] if text else []}
        if calls:
            message["tool_calls"] = calls
        self._messages.append(message)
        self._batch, self._batch_closed = entries, False
        executable = [e for e in entries if e.executable]
        if executable:
            self._consecutive_invalid = 0
        else:
            self.counts["invalid_replies"] += 1
            self._consecutive_invalid += 1
            if not entries:
                self._messages.append({"role": "user", "content": [{"type": "text", "text": NO_TOOL_NOTE}]})
            self._flush_batch()
            self._check_limits()
        return {"protocol": self.version.protocol, "text": "",
                "tool_calls": [{"id": e.call["id"], "name": e.call["name"], "arguments": e.call["arguments"]} for e in executable]}

    def _validate_calls(self, reply: providers.ProviderReply) -> tuple[list[dict[str, Any]] | None, list[_BatchEntry]]:
        """Decide call by call. Every call gets an answer in the history, because providers require one for each."""
        raw_calls = reply.tool_calls
        self.counts["tool_calls_requested"] += len(raw_calls)
        ids: set[str] = set()
        for raw in raw_calls:
            call_id = raw.get("id") if isinstance(raw, Mapping) else None
            if not isinstance(call_id, str) or not _CALL_ID.match(call_id) or call_id in ids or call_id in self._seen_call_ids:
                self.counts["tool_calls_rejected"] += len(raw_calls)
                self._record({"event": "reply_rejected", "reason": "unusable tool call id"})
                return None, []
            ids.add(call_id)
        self._seen_call_ids |= ids
        calls, entries = [], []
        accepted = 0
        for raw in raw_calls:
            error, canonical, arguments = self._check_call(raw, accepted, reply.stop)
            name = raw.get("name")
            call = {"id": raw["id"], "name": name if isinstance(name, str) and len(name) <= 64 else "invalid", "arguments": arguments}
            calls.append(call)
            if error is None:
                accepted += 1
                entries.append(_BatchEntry(call=call, executable=True, canonical=canonical))
            else:
                self.counts["tool_calls_rejected"] += 1
                self._record({"event": "tool_call_rejected", "id": raw["id"], "reason": error})
                entries.append(_BatchEntry(call=call, executable=False, result={
                    "parts": [{"type": "text", "text": json.dumps({"error": error})}], "is_error": True}))
        return calls, entries

    def _check_call(self, raw: Mapping[str, Any], accepted: int, stop: str):
        arguments = raw.get("arguments")
        try:
            safe_arguments = arguments if isinstance(arguments, dict) and \
                len(json.dumps(arguments)) <= self.config.max_tool_argument_bytes else {}
        except (TypeError, ValueError, RecursionError):
            safe_arguments = {}
        if stop == "max_tokens":
            return "the reply was cut off by the output limit; this call was not executed", None, safe_arguments
        name = raw.get("name")
        # "brief" is a valid player request but is not a model tool
        if not isinstance(name, str) or name not in {t["name"] for t in self.tools}:
            return "unknown tool", None, safe_arguments
        if accepted >= self.config.max_tool_calls_per_reply:
            return f"not executed: at most {self.config.max_tool_calls_per_reply} tool calls per reply", None, safe_arguments
        if not isinstance(arguments, dict) or safe_arguments is not arguments:
            return "invalid arguments", None, safe_arguments
        allowed = {"keys", "frames"} if name == "act" else set()
        if set(arguments) - allowed:
            return "unexpected arguments", None, safe_arguments
        try:
            return None, contract.parse_request({"tool": name, **arguments}, self.version), safe_arguments
        except contract.ActionRejected as exc:
            return redact(exc), None, safe_arguments


def redact_json(value: Any, limit: int) -> str:
    """JSON for the log, with credential-shaped strings removed; too-long values are replaced, never cut mid-token."""
    text = _SECRET.sub("[redacted]", json.dumps(value, default=str))
    return text if len(text) <= limit else json.dumps({"omitted_bytes": len(text)})


def verify_transcript(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute the hash chain of a gateway transcript and summarize it. Used by the audit and by tests."""
    tip, charged = "0" * 64, Decimal(0)
    for number, record in enumerate(records, 1):
        body = {k: v for k, v in record.items() if k != "sha256"}
        if record.get("prev_sha256") != tip or record.get("index") != number:
            return {"valid": False, "first_bad_record": number}
        tip = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        if tip != record.get("sha256"):
            return {"valid": False, "first_bad_record": number}
        outcome = record.get("outcome") or {}
        charged += Decimal(outcome.get("charged_usd", "0"))
    return {"valid": True, "records": len(records), "tip_sha256": tip, "charged_usd": str(charged)}

