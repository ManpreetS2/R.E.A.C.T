"""Provider-independent ModelClient. Rewards stay in the simulator."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from rewardbench.contracts import (
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
from rewardbench.providers.capabilities import PROVIDER_DIFFERENCES
from rewardbench.providers.http import HttpCallError, Transport, TransportError, UrllibTransport
from rewardbench.providers.limits import RateLimiter, RetryPolicy, SpendingGuard
from rewardbench.providers.parsing import parse_controller
from rewardbench.providers.pricing import (
    CostEstimate,
    PricingCatalog,
    estimate_text_tokens,
    load_catalog,
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
        self._refuse_unpriced_when_capped(system_text, user_text, settings)
        self._spending.ensure(self._reserve_usd(system_text, user_text, settings))

        attempts: list[dict[str, Any]] = []
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
                retryable = bool(getattr(exc, "retryable", False))
                if not retryable or attempt >= self._retry.max_retries:
                    self._remember(attempts, error=_redact(str(exc), self._secrets))
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

        prompt_tokens, completion_tokens, reasoning_tokens, total_tokens, latency = _sum_attempts(
            attempts
        )
        cost = self._catalog.estimate(
            self.provider,
            self.model_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
        )
        if cost.priced:
            self._spending.charge(cost.usd)
        elif self._spending.capped:
            self._spending.charge(0.0)
        parameters, parse_error = parse_controller(completion.text)
        usage = _usage_payload(
            provider=self.provider,
            attempts=attempts,
            completion=completion,
            cost=cost,
            prompt_template=PROMPT_TEMPLATE_ID,
            catalog_version=self._catalog.version,
            spent_usd=self._spending.spent_usd,
            cap_usd=self._spending.max_spend_usd,
        )
        self._remember(attempts, error=parse_error)
        return ModelResponse(
            raw_text=completion.text,
            parameters=parameters,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            total_tokens=total_tokens,
            latency_seconds=latency,
            estimated_cost_usd=cost.usd if cost.priced else 0.0,
            model_id=self.model_id,
            provider=self.provider,
            parse_error=parse_error,
            usage=usage,
        )

    def _refuse_unpriced_when_capped(
        self,
        system_text: str,
        user_text: str,
        settings: Mapping[str, Any],
    ) -> None:
        if not self._spending.capped:
            return
        estimate = self._catalog.estimate(
            self.provider,
            self.model_id,
            prompt_tokens=estimate_text_tokens(system_text) + estimate_text_tokens(user_text),
            completion_tokens=_reserve_output_tokens(settings),
            reasoning_tokens=_reserve_reasoning_tokens(settings),
        )
        if estimate.priced:
            return
        raise ModelClientError(
            (
                f"{estimate.note}; refusing the call because a spending cap is set "
                f"on catalog {self._catalog.version}"
            ),
            retryable=False,
        )

    def _reserve_usd(self, system_text: str, user_text: str, settings: Mapping[str, Any]) -> float:
        estimate = self._catalog.estimate(
            self.provider,
            self.model_id,
            prompt_tokens=estimate_text_tokens(system_text) + estimate_text_tokens(user_text),
            completion_tokens=_reserve_output_tokens(settings),
            reasoning_tokens=_reserve_reasoning_tokens(settings),
        )
        return estimate.usd if estimate.priced else 0.0

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
        "request_id": None,
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
) -> dict[str, Any]:
    last = attempts[-1]
    return {
        "prompt_template": prompt_template,
        "pricing_version": catalog_version,
        "cost_status": cost.status,
        "pricing_note": cost.note,
        "retry_count": max(0, len(attempts) - 1),
        "request_id": completion.request_id,
        "response_model_id": completion.response_model_id,
        "finish_reason": completion.finish_reason,
        "applied_settings": dict(completion.applied_settings),
        "ignored_settings": dict(completion.ignored_settings),
        "extra_usage": dict(completion.extra_usage),
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
    }


def _redact(text: str | None, secrets: Sequence[str]) -> str:
    if text is None:
        return ""
    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return redacted
