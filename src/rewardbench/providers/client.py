"""Provider-independent ModelClient. Rewards stay in the simulator."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import replace
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from rewardbench.contracts import (
    BudgetExceeded,
    FeedbackCondition,
    ModelClient,
    ModelClientError,
    ModelRequest,
    ModelResponse,
)
from rewardbench.prompts import PROMPT_TEMPLATE_ID, render_messages
from rewardbench.providers.backends import (
    ANTHROPIC_URL,
    GEMINI_ROOT,
    OPENAI_URL,
    XAI_URL,
    AnthropicBackend,
    Completion,
    GeminiBackend,
    GrokBackend,
    MockBackend,
    OpenAIBackend,
    resolve_api_key,
)
from rewardbench.providers.capabilities import PROVIDER_DIFFERENCES, SPENDING_LIMITS
from rewardbench.providers.http import HttpCallError, Transport, TransportError, UrllibTransport
from rewardbench.providers.limits import RateLimiter, RetryPolicy, SpendingGuard
from rewardbench.providers.parsing import parse_controller
from rewardbench.providers.pricing import (
    CostEstimate,
    PriceQuote,
    PricingCatalog,
    load_catalog,
    quote_call,
    usage_within_quote,
)

LOGGER = logging.getLogger("rewardbench.providers")

_PROVIDERS = ("openai", "google", "anthropic", "xai", "mock")


class RewardModelClient:
    """One configured model. ``propose`` implements :class:`ModelClient`."""

    def __init__(
        self,
        *,
        provider: str,
        model_id: str,
        backend: Any,
        catalog: PricingCatalog,
        spending: SpendingGuard | None = None,
        retry: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        secrets: Sequence[str] = (),
    ) -> None:
        if not isinstance(provider, str) or not provider.strip():
            raise ModelClientError("provider must be a non-empty string", retryable=False)
        if not isinstance(model_id, str) or not model_id.strip():
            raise ModelClientError("model_id must be a non-empty string", retryable=False)
        self._provider = provider
        self._model_id = model_id
        self._backend = backend
        self._catalog = catalog
        self._spending = spending or SpendingGuard()
        self._retry = retry or RetryPolicy()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._sleep = sleeper
        self._rng = rng or random.Random()
        self._secrets = tuple(secret for secret in secrets if secret)
        self.invocations: list[dict[str, Any]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    def propose(self, request: ModelRequest) -> ModelResponse:
        if request.feedback_condition not in (
            FeedbackCondition.NO_FEEDBACK,
            FeedbackCondition.NUMERICAL_REWARD,
        ):
            raise ModelClientError(
                f"unsupported feedback condition {request.feedback_condition!r}",
                retryable=False,
            )
        system_text, user_text = render_messages(request)
        settings = dict(request.model_settings)
        if self.provider != "mock":
            self._spending.ensure_open()
        quote = self._quote(system_text, user_text, settings)
        if self.provider != "mock" and not quote.available:
            raise ModelClientError(
                f"{quote.note}; refusing the call before any provider request",
                retryable=False,
            )
        reserved = 0.0
        if self._spending.capped:
            reserved = self._spending.reserve(quote.usd if quote.available else 0.0)
        attempts: list[dict[str, Any]] = []
        completion: Completion | None = None
        try:
            completion = self._complete_with_retries(settings, system_text, user_text, attempts)
            response = self._response_from_completion(
                completion,
                attempts,
                quote,
            )
        except Exception as exc:
            if not attempts:
                if reserved:
                    self._spending.release(reserved)
                raise
            # Even a failed HTTP response may report billed usage. Preserve it
            # independently of whether settling the charge itself raises.
            response = self._response_from_completion(
                Completion("", None, None, 0, 0, 0, 0, 0.0, None, {}, {}, {}),
                attempts, quote, failure=_redact(str(exc), self._secrets),
            )
            response = self._prepare_accounting(response, settings, reserved)
            try:
                self._settle_or_release(reserved, response, quote, attempts)
            except (ModelClientError, BudgetExceeded) as settlement_error:
                settlement_error.response = self._annotate(response, quote)
                raise settlement_error from exc
            if isinstance(exc, (ModelClientError, BudgetExceeded)):
                exc.response = self._annotate(response, quote)
            raise
        response = self._prepare_accounting(response, settings, reserved)
        try:
            self._settle_or_release(reserved, response, quote, attempts)
        except (ModelClientError, BudgetExceeded) as exc:
            exc.response = self._annotate(response, quote)
            raise
        return self._annotate(response, quote)

    def _complete_with_retries(
        self,
        settings: Mapping[str, Any],
        system_text: str,
        user_text: str,
        attempts: list[dict[str, Any]],
    ) -> Completion:
        completion: Completion | None = None
        for attempt in range(self._retry.max_retries + 1):
            self._rate_limiter.acquire()
            try:
                completion = self._backend.complete(
                    model_id=self.model_id,
                    system_text=system_text,
                    user_text=user_text,
                    settings=settings,
                )
            except (HttpCallError, TransportError) as exc:
                failed = _failed_attempt(attempt, exc)
                failed["error"] = _redact(str(failed["error"]), self._secrets)
                attempts.append(failed)
                self._log_attempt(attempts[-1])
                cache_read, cache_write = _cache_tokens(attempts)
                if cache_read or cache_write:
                    prompt, output, reasoning, _, _ = _sum_attempts(attempts)
                    priced = self._catalog.estimate(
                        self.provider, self.model_id, prompt_tokens=prompt,
                        completion_tokens=output, reasoning_tokens=reasoning,
                        cache_read_tokens=cache_read, cache_write_tokens=cache_write,
                    )
                    if priced.status != "priced":
                        # Settle the failed call in propose(), but never buy a
                        # retry after usage has escaped the configured pricing.
                        raise ModelClientError(priced.note or priced.status, retryable=False)
                retryable = bool(getattr(exc, "retryable", False))
                if not retryable or attempt >= self._retry.max_retries:
                    raise ModelClientError(
                        _redact(str(exc), self._secrets),
                        retryable=retryable,
                    ) from None
                delay = self._retry.delay(
                    attempt,
                    self._rng,
                    getattr(exc, "retry_after_s", None),
                )
                self._sleep(delay)
                continue
            attempts.append(_successful_attempt(attempt, completion))
            self._log_attempt(attempts[-1])
            break

        if completion is None:
            raise ModelClientError("provider did not return a response", retryable=True)
        return completion

    def _response_from_completion(
        self,
        completion: Completion,
        attempts: list[dict[str, Any]],
        quote: PriceQuote,
        *,
        failure: str | None = None,
    ) -> ModelResponse:
        prompt_tokens, completion_tokens, reasoning_tokens, total_tokens, latency = _sum_attempts(
            attempts
        )
        cache_read, cache_write = _cache_tokens(attempts)
        cost = self._catalog.estimate(
            self.provider,
            self.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        parameters, parse_error = (None, failure) if failure else parse_controller(completion.text)
        truncated = _is_truncated(completion.finish_reason)
        if truncated and parse_error:
            parse_error = (
                f"{parse_error}; response finish_reason={completion.finish_reason!r} "
                "(output may have been cut by max_output_tokens or reasoning budget)"
            )
        elif truncated and parameters is None:
            parse_error = (
                f"response finish_reason={completion.finish_reason!r} with no controller JSON; "
                "output may have been cut by max_output_tokens or reasoning budget"
            )
        usage = _usage_payload(
            provider=self.provider,
            attempts=attempts,
            completion=completion,
            cost=cost,
            prompt_template=PROMPT_TEMPLATE_ID,
            catalog_version=self._catalog.version,
            spent_usd=self._spending.spent_usd,
            cap_usd=self._spending.max_spend_usd,
            quote=quote,
        )
        usage = dict(usage)
        usage["truncated"] = truncated
        self._remember(attempts, error=parse_error)
        return ModelResponse(
            raw_text=completion.text,
            parameters=parameters,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            latency_seconds=latency,
            estimated_cost_usd=cost.usd,
            model_id=self.model_id,
            provider=self.provider,
            parse_error=parse_error,
            usage=usage,
        )

    def _quote(self, system_text: str, user_text: str, settings: Mapping[str, Any]) -> PriceQuote:
        if self.provider == "mock":
            return PriceQuote(True, 0.0, "offline", "mock calls are not billed", attempts=1)
        return quote_call(
            self._catalog,
            self.provider,
            self.model_id,
            system_text=system_text,
            user_text=user_text,
            settings=settings,
            attempts=self._retry.max_retries + 1,
        )

    def _prepare_accounting(
        self, response: ModelResponse, settings: Mapping[str, Any], reserved: float,
    ) -> ModelResponse:
        usage = dict(response.usage)
        usage["requested_settings"] = dict(settings)
        charge = response.estimated_cost_usd
        if self.provider != "mock" and usage.get("cost_status") != "priced" and charge <= 0:
            charge = reserved
            usage["charge_basis"] = "reservation_fallback"
        return replace(response, usage=usage, estimated_cost_usd=charge)

    def _settle_or_release(
        self,
        reserved: float,
        response: ModelResponse,
        quote: PriceQuote,
        attempts: list[dict[str, Any]],
    ) -> None:
        if self.provider == "mock":
            if reserved:
                self._spending.release(reserved)
            return
        status = str(response.usage.get("cost_status") or "")
        note = str(response.usage.get("pricing_note") or "provider usage is not covered by the catalog")
        actual = response.estimated_cost_usd
        if status != "priced":
            charge = actual if actual > 0 else reserved
            self._charge(reserved, charge, status, note)
            self._spending.stop(note)
            raise ModelClientError(
                f"{note}; recorded {charge:.6f} USD and blocked further provider calls in this process",
                retryable=False,
            )
        self._charge(reserved, actual, status, note)
        if not usage_within_quote(attempts, quote):
            overrun = ""
            if actual > reserved + 1e-12:
                overrun = (
                    f"; billed {actual:.6f} USD exceeded the reserved {reserved:.6f} USD "
                    "and was recorded"
                )
            raise ModelClientError(
                "billed tokens exceeded the reserved input, output, or reasoning ceiling" + overrun,
                retryable=False,
            )

    def _charge(self, reserved: float, actual: float, status: str, note: str) -> None:
        try:
            self._spending.settle(reserved, actual)
        except BudgetExceeded:
            if status != "priced":
                self._spending.stop(note)
            raise

    def _annotate(self, response: ModelResponse, quote: PriceQuote) -> ModelResponse:
        usage = dict(response.usage)
        actual = response.estimated_cost_usd
        usage["spent_usd"] = self._spending.spent_usd
        usage["held_usd"] = self._spending.held_usd
        usage["budget_exceeded"] = bool(
            self._spending.max_spend_usd is not None
            and self._spending.spent_usd > self._spending.max_spend_usd + 1e-9
        )
        usage["reservation_exceeded"] = bool(quote.available and actual > quote.usd + 1e-12)
        usage["spending_scope"] = "in_process_only"
        return replace(response, usage=usage)

    def _log_attempt(self, record: Mapping[str, Any]) -> None:
        LOGGER.info(
            "provider_call provider=%s model_id=%s latency_seconds=%s prompt_tokens=%s "
            "completion_tokens=%s reasoning_tokens=%s error=%s",
            self.provider,
            self.model_id,
            record.get("latency_seconds"),
            record.get("prompt_tokens"),
            record.get("completion_tokens"),
            record.get("reasoning_tokens"),
            _redact(str(record.get("error")), self._secrets) if record.get("error") else None,
        )

    def _remember(self, attempts: Sequence[Mapping[str, Any]], *, error: str | None) -> None:
        self.invocations.append(
            {
                "provider": self.provider,
                "model_id": self.model_id,
                "attempts": [dict(item) for item in attempts],
                "error": _redact(error, self._secrets) if error else None,
            }
        )


def build_model_client(
    provider: str,
    model_id: str,
    *,
    transport: Transport | None = None,
    api_key: str | None = None,
    pricing_catalog: str | None = None,
    max_spend_usd: float | None = None,
    min_interval_s: float = 0.0,
    max_requests_per_window: int | None = None,
    window_s: float = 60.0,
    max_retries: int = 2,
    timeout_s: float = 60.0,
    base_url: str | None = None,
    mock_script: Sequence[object] | None = None,
    clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
    rng: random.Random | None = None,
) -> ModelClient:
    """Build an OpenAI, Gemini, Claude, Grok, or offline mock client.

    ``model_id`` is whatever the caller configures. Live calls read keys from
    the environment unless ``api_key`` is passed. This function does not make
    a request.
    """

    if provider not in _PROVIDERS:
        raise ModelClientError(
            f"unknown provider {provider!r}; expected one of {', '.join(_PROVIDERS)}",
            retryable=False,
        )
    catalog = load_catalog(pricing_catalog)
    sleep = sleeper or time.sleep
    limiter = RateLimiter(
        min_interval_s=min_interval_s,
        max_per_window=max_requests_per_window,
        window_s=window_s,
        clock=clock or time.monotonic,
        sleep=sleep,
    )
    secrets: list[str] = []
    if provider == "mock":
        backend: Any = MockBackend(mock_script)
    else:
        try:
            key = resolve_api_key(provider, api_key)
        except LookupError as exc:
            raise ModelClientError(
                f"{provider} API key is not set; expected {exc}",
                retryable=False,
            ) from exc
        secrets.append(key)
        http = transport or UrllibTransport()
        backend = _live_backend(
            provider,
            transport=http,
            api_key=key,
            timeout_s=timeout_s,
            base_url=base_url,
        )
    client = RewardModelClient(
        provider=provider,
        model_id=model_id,
        backend=backend,
        catalog=catalog,
        spending=SpendingGuard(max_spend_usd=max_spend_usd),
        retry=RetryPolicy(max_retries=max_retries),
        rate_limiter=limiter,
        sleeper=sleep,
        rng=rng,
        secrets=secrets,
    )
    return client


def _live_backend(
    provider: str,
    *,
    transport: Transport,
    api_key: str,
    timeout_s: float,
    base_url: str | None,
) -> Any:
    if provider == "openai":
        return OpenAIBackend(
            transport=transport,
            api_key=api_key,
            timeout_s=timeout_s,
            endpoint=base_url or OPENAI_URL,
        )
    if provider == "google":
        return GeminiBackend(
            transport=transport,
            api_key=api_key,
            timeout_s=timeout_s,
            root=base_url or GEMINI_ROOT,
        )
    if provider == "anthropic":
        return AnthropicBackend(
            transport=transport,
            api_key=api_key,
            timeout_s=timeout_s,
            endpoint=base_url or ANTHROPIC_URL,
        )
    if provider == "xai":
        return GrokBackend(
            transport=transport,
            api_key=api_key,
            timeout_s=timeout_s,
            endpoint=base_url or XAI_URL,
        )
    raise ModelClientError(f"no live backend for {provider}", retryable=False)


def _reserve_output_tokens(settings: Mapping[str, Any]) -> int:
    value = settings.get("max_output_tokens", 800)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return 800
    return value


def _reserve_reasoning_tokens(settings: Mapping[str, Any]) -> int:
    for key in ("gemini_thinking_budget", "anthropic_thinking_budget_tokens"):
        value = settings.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
    return 0


def _failed_attempt(index: int, exc: Exception) -> dict[str, Any]:
    usage = getattr(exc, "usage", {}) or {}
    return {
        "index": index,
        "ok": False,
        "error": str(exc),
        "status": getattr(exc, "status", None),
        "latency_seconds": float(getattr(exc, "latency_seconds", 0.0) or 0.0),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "reasoning_tokens": int(usage.get("reasoning_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "request_id": getattr(exc, "request_id", None),
        "extra_usage": {
            key: int(usage.get(key, 0) or 0) for key in (
                "cache_read_input_tokens", "cache_creation_input_tokens", "cache_write_input_tokens"
            ) if usage.get(key)
        },
    }


def _successful_attempt(index: int, completion: Completion) -> dict[str, Any]:
    return {
        "index": index,
        "ok": True,
        "error": None,
        "status": 200,
        "latency_seconds": completion.latency_seconds,
        "prompt_tokens": completion.prompt_tokens,
        "completion_tokens": completion.completion_tokens,
        "reasoning_tokens": completion.reasoning_tokens,
        "total_tokens": completion.total_tokens,
        "request_id": completion.request_id,
        "response_model_id": completion.response_model_id,
        "finish_reason": completion.finish_reason,
        "applied_settings": completion.applied_settings,
        "ignored_settings": completion.ignored_settings,
        "extra_usage": completion.extra_usage,
    }


def _sum_attempts(
    attempts: Sequence[Mapping[str, Any]],
) -> tuple[int, int, int, int, float]:
    prompt = completion = reasoning = total = 0
    latency = 0.0
    for item in attempts:
        prompt += int(item["prompt_tokens"])
        completion += int(item["completion_tokens"])
        reasoning += int(item["reasoning_tokens"])
        reported = int(item["total_tokens"])
        total += reported or int(item["prompt_tokens"]) + int(item["completion_tokens"])
        latency += float(item["latency_seconds"])
    if total == 0:
        total = prompt + completion
    return prompt, completion, reasoning, total, latency


def _cache_tokens(attempts: Sequence[Mapping[str, Any]]) -> tuple[int, int]:
    read = write = 0
    for attempt in attempts:
        extra = attempt.get("extra_usage", {})
        read += int(extra.get("cache_read_input_tokens") or 0)
        write += int(extra.get("cache_write_input_tokens") or extra.get("cache_creation_input_tokens") or 0)
    return read, write


def _usage_payload(
    *,
    provider: str,
    attempts: Sequence[Mapping[str, Any]],
    completion: Completion,
    cost: CostEstimate,
    prompt_template: str,
    catalog_version: str,
    spent_usd: float,
    cap_usd: float | None,
    quote: PriceQuote,
) -> dict[str, Any]:
    last = attempts[-1]
    extra_usage = dict(completion.extra_usage)
    read, write = _cache_tokens(attempts)
    if read:
        extra_usage["cache_read_input_tokens"] = read
    if write:
        extra_usage["cache_write_input_tokens"] = write
    return {
        "prompt_template": prompt_template,
        "pricing_version": catalog_version,
        "cost_status": cost.status,
        "pricing_note": cost.note,
        "reservation_usd": quote.usd,
        "reservation_attempts": quote.attempts,
        "prompt_token_ceiling": quote.prompt_tokens,
        "max_output_tokens": quote.completion_tokens,
        "reasoning_token_ceiling": quote.reasoning_tokens,
        "input_ceiling": quote.input_ceiling,
        "spending_limits": list(SPENDING_LIMITS),
        "retry_count": max(0, len(attempts) - 1),
        "request_id": completion.request_id,
        "response_model_id": completion.response_model_id,
        "finish_reason": completion.finish_reason,
        "applied_settings": dict(completion.applied_settings),
        "ignored_settings": dict(completion.ignored_settings),
        "extra_usage": extra_usage,
        "provider_differences": list(PROVIDER_DIFFERENCES.get(provider, ())),
        "calls": [_public_call(item) for item in attempts],
        "spent_usd": spent_usd,
        "spending_cap_usd": cap_usd,
        "last_request_id": last.get("request_id"),
    }


def _public_call(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index": item["index"],
        "ok": item["ok"],
        "status": item["status"],
        "latency_seconds": item["latency_seconds"],
        "prompt_tokens": item["prompt_tokens"],
        "completion_tokens": item["completion_tokens"],
        "reasoning_tokens": item["reasoning_tokens"],
        "error": item["error"],
        "total_tokens": item["total_tokens"],
        "request_id": item.get("request_id"),
        "response_model_id": item.get("response_model_id"),
        "applied_settings": dict(item.get("applied_settings", {})),
        "ignored_settings": dict(item.get("ignored_settings", {})),
        "extra_usage": dict(item.get("extra_usage", {})),
    }


def _redact(text: str | None, secrets: Sequence[str]) -> str:
    if text is None:
        return ""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted


def _is_truncated(finish_reason: str | None) -> bool:
    if not finish_reason:
        return False
    return finish_reason.lower() in {"length", "max_tokens", "max_output_tokens"}
