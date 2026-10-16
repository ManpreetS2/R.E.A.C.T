"""Offline first-call preflight. No network. No API keys required."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rewardbench.contracts import ConfigError, ModelClientError
from rewardbench.prompts import SYSTEM_PROMPT, render_messages
from rewardbench.providers.pricing import PriceQuote, PricingCatalog, load_catalog, quote_call


@dataclass(frozen=True)
class FirstCallPreflight:
    """Reservation math for one propose() before any provider socket opens."""

    provider: str
    model_id: str
    quote: PriceQuote
    catalog_version: str
    max_spend_usd: float | None
    max_output_tokens: int
    reasoning_effort: object | None
    system_chars: int
    user_chars: int
    notes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.quote.available and (
            self.max_spend_usd is None or self.quote.usd <= self.max_spend_usd + 1e-12
        )


def preflight_first_call(
    *,
    provider: str,
    model_id: str,
    request,
    max_spend_usd: float | None,
    pricing_catalog: str | None = None,
    catalog: PricingCatalog | None = None,
    http_attempts: int | None = None,
) -> FirstCallPreflight:
    """Quote one ModelRequest against the local catalog. Does not call a provider."""

    if provider == "mock":
        raise ModelClientError("preflight_first_call is for live providers", retryable=False)
    loaded = catalog or load_catalog(pricing_catalog)
    rate = loaded.rate_for(provider, model_id)
    if rate is None:
        raise ModelClientError(
            f"no rate for {provider}:{model_id} in catalog {loaded.version}; refusing before network",
            retryable=False,
        )
    system_text, user_text = render_messages(request)
    settings = dict(request.model_settings)
    attempts = http_attempts if http_attempts is not None else 1
    if attempts < 1:
        raise ConfigError("http_attempts must be >= 1")
    quote = quote_call(
        loaded,
        provider,
        model_id,
        system_text=system_text,
        user_text=user_text,
        settings=settings,
        attempts=attempts,
    )
    notes: list[str] = []
    if not quote.available:
        notes.append(quote.note or "quote unavailable")
    if max_spend_usd is not None and quote.available and quote.usd > max_spend_usd + 1e-12:
        notes.append(
            f"reserved {quote.usd:.6f} USD exceeds max_spend_usd {max_spend_usd:.6f} USD; "
            "a capped RewardModelClient would refuse before HTTP"
        )
    max_out = int(settings.get("max_output_tokens") or 800)
    effort = settings.get("reasoning_effort")
    if provider == "openai" and effort not in (None, "none") and max_out < 800:
        notes.append(
            "OpenAI reasoning tokens count against max_completion_tokens; "
            f"reasoning_effort={effort!r} with max_output_tokens={max_out} risks truncating the controller JSON"
        )
    if provider == "openai" and (effort is None or effort == "none") and max_out < 400:
        notes.append(
            "max_output_tokens below 400 is tight even with reasoning_effort none; "
            "prefer at least 400 for compact controllers and 800 for safer guidance objects"
        )
    notes.append(
        "In-process spend caps are not a provider-side billing guarantee. "
        "Concurrent processes and billing discrepancies can exceed the software reserve."
    )
    return FirstCallPreflight(
        provider=provider,
        model_id=model_id,
        quote=quote,
        catalog_version=loaded.version,
        max_spend_usd=max_spend_usd,
        max_output_tokens=max_out,
        reasoning_effort=effort,
        system_chars=len(system_text),
        user_chars=len(user_text),
        notes=tuple(notes),
    )


def require_preflight_ok(result: FirstCallPreflight) -> FirstCallPreflight:
    """Raise before any transport is constructed when the local quote is unsafe."""

    if result.ok:
        return result
    detail = "; ".join(result.notes) if result.notes else result.quote.note
    raise ModelClientError(
        f"first-call preflight refused for {result.provider}:{result.model_id}: {detail}",
        retryable=False,
    )


def compact_system_prompt() -> str:
    """Expose the shared system prompt for dry-run printing."""

    return SYSTEM_PROMPT


def summarize_settings(settings: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "max_output_tokens": settings.get("max_output_tokens"),
        "reasoning_effort": settings.get("reasoning_effort"),
        "json_mode": settings.get("json_mode", True),
        "temperature": settings.get("temperature"),
    }
