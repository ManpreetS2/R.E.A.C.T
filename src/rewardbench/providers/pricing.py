"""Versioned provider prices. Model ids are catalog keys, not code constants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rewardbench.contracts import ConfigError

DEFAULT_CATALOG_VERSION = "2026-10-14"
DEFAULT_MAX_OUTPUT_TOKENS = 800
# Role labels and protocol tokens beyond the raw system and user bytes.
PROMPT_FRAMING_TOKENS = 64


@dataclass(frozen=True)
class ModelRate:
    """USD per 1,000,000 tokens for one provider model id."""

    provider: str
    model_id: str
    input_per_million: float
    output_per_million: float
    reasoning_included_in_output: bool
    long_context_threshold_tokens: int | None = None
    long_context_input_per_million: float | None = None
    long_context_output_per_million: float | None = None
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None
    note: str = ""


@dataclass(frozen=True)
class CostEstimate:
    """A dollar estimate plus whether the catalog actually covered the call."""

    usd: float
    status: str
    version: str
    note: str = ""

    @property
    def priced(self) -> bool:
        return self.status == "priced"


@dataclass(frozen=True)
class PricingCatalog:
    version: str
    currency: str
    source: str
    rates: Mapping[str, ModelRate]

    def rate_for(self, provider: str, model_id: str) -> ModelRate | None:
        return self.rates.get(f"{provider}:{model_id}")

    def estimate(
        self,
        provider: str,
        model_id: str,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        reasoning_tokens: int,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> CostEstimate:
        rate = self.rate_for(provider, model_id)
        if rate is None:
            return CostEstimate(
                usd=0.0,
                status="unpriced",
                version=self.version,
                note=f"no rate for {provider}:{model_id}",
            )
        input_rate = rate.input_per_million
        output_rate = rate.output_per_million
        threshold = rate.long_context_threshold_tokens
        if threshold is not None and prompt_tokens > threshold:
            if (
                rate.long_context_input_per_million is None
                or rate.long_context_output_per_million is None
            ):
                return CostEstimate(
                    usd=0.0,
                    status="long_context_rate_unconfigured",
                    version=self.version,
                    note=(
                        f"{provider}:{model_id} prompt has {prompt_tokens} tokens; "
                        f"the {self.version} catalog prices prompts only through {threshold}"
                    ),
                )
            input_rate = rate.long_context_input_per_million
            output_rate = rate.long_context_output_per_million
        cache_cost, cache_status, cache_note = _cache_cost(
            rate,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
        )
        billed_output = completion_tokens
        if not rate.reasoning_included_in_output:
            billed_output += reasoning_tokens
        token_usd = _usd(prompt_tokens, input_rate) + _usd(billed_output, output_rate)
        if cache_status != "priced":
            return CostEstimate(
                usd=token_usd,
                status=cache_status,
                version=self.version,
                note=cache_note,
            )
        usd = token_usd + cache_cost
        return CostEstimate(usd=usd, status="priced", version=self.version, note=rate.note)


def default_catalog_path() -> Path:
    return Path(__file__).resolve().parent / "data" / f"pricing_{DEFAULT_CATALOG_VERSION}.json"


def load_catalog(path: str | Path | None = None) -> PricingCatalog:
    catalog_path = Path(path) if path is not None else default_catalog_path()
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"pricing catalog not found: {catalog_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"pricing catalog is not JSON: {catalog_path}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("pricing catalog must be a JSON object")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ConfigError("pricing catalog version must be a non-empty string")
    currency = payload.get("currency", "USD")
    if currency != "USD":
        raise ConfigError("pricing catalog currency must be USD")
    source = payload.get("source", "")
    if not isinstance(source, str):
        raise ConfigError("pricing catalog source must be a string")
    models = payload.get("models")
    if not isinstance(models, dict) or not models:
        raise ConfigError("pricing catalog models must be a non-empty object")
    rates: dict[str, ModelRate] = {}
    for key, raw in models.items():
        if not isinstance(key, str) or ":" not in key:
            raise ConfigError(f"pricing key {key!r} must look like provider:model_id")
        provider, model_id = key.split(":", 1)
        if not provider or not model_id:
            raise ConfigError(f"pricing key {key!r} is missing a provider or model id")
        if not isinstance(raw, dict):
            raise ConfigError(f"pricing entry {key} must be an object")
        rates[key] = ModelRate(
            provider=provider,
            model_id=model_id,
            input_per_million=_price(raw, "input_per_million", key),
            output_per_million=_price(raw, "output_per_million", key),
            reasoning_included_in_output=_bool_field(
                raw, "reasoning_included_in_output", key
            ),
            long_context_threshold_tokens=_optional_int(
                raw, "long_context_threshold_tokens", key
            ),
            long_context_input_per_million=_optional_price(
                raw, "long_context_input_per_million", key
            ),
            long_context_output_per_million=_optional_price(
                raw, "long_context_output_per_million", key
            ),
            cache_read_per_million=_optional_price(raw, "cache_read_per_million", key),
            cache_write_per_million=_optional_price(raw, "cache_write_per_million", key),
            note=raw.get("note", "") if isinstance(raw.get("note", ""), str) else "",
        )
    return PricingCatalog(
        version=version,
        currency=currency,
        source=source,
        rates=rates,
    )


@dataclass(frozen=True)
class PriceQuote:
    """Worst-case dollars for one ``propose`` call, including its HTTP retries.

    ``available`` is false when the catalog cannot bound the bill. A capped
    client must refuse the call in that case instead of sending it.
    """

    available: bool
    usd: float
    status: str
    note: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    attempts: int = 1
    reasoning_separate: bool = False
    input_ceiling: str = "utf8_bytes_plus_framing"

    @property
    def per_attempt_usd(self) -> float:
        if self.attempts <= 0:
            return self.usd
        return self.usd / self.attempts


def prompt_token_ceiling(system_text: str, user_text: str) -> int:
    """Upper bound used for reservation.

    BPE tokenizers used by these providers emit at most one token per UTF-8
    byte for the message text, plus a fixed allowance for role labels. This is
    not a provider invoice. A tokenizer that emits more tokens than bytes makes
    a strict dollar cap unavailable, and the client refuses the call.
    """

    return (
        len(system_text.encode("utf-8"))
        + len(user_text.encode("utf-8"))
        + PROMPT_FRAMING_TOKENS
    )


def configured_max_output(settings: Mapping[str, Any]) -> tuple[int | None, str | None]:
    if "max_output_tokens" not in settings:
        return DEFAULT_MAX_OUTPUT_TOKENS, None
    value = settings.get("max_output_tokens")
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None, "max_output_tokens must be a positive integer"
    return value, None


def configured_reasoning_ceiling(settings: Mapping[str, Any]) -> tuple[int | None, str | None]:
    for key in (
        "max_reasoning_tokens",
        "gemini_thinking_budget",
        "anthropic_thinking_budget_tokens",
    ):
        if key not in settings:
            continue
        value = settings.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None, f"{key} must be a non-negative integer"
        return value, None
    return None, "reasoning is billed separately; set max_reasoning_tokens or a thinking budget"


def configured_cache_ceiling(settings: Mapping[str, Any], name: str) -> tuple[int | None, str | None]:
    if name not in settings:
        return 0, None
    value = settings.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None, f"{name} must be a non-negative integer"
    return value, None


def quote_call(
    catalog: PricingCatalog,
    provider: str,
    model_id: str,
    *,
    system_text: str,
    user_text: str,
    settings: Mapping[str, Any],
    attempts: int,
) -> PriceQuote:
    """Price the worst case of ``attempts`` HTTP tries. Does not call a provider."""

    if attempts < 1:
        return PriceQuote(False, 0.0, "invalid_attempts", "attempts must be >= 1")
    rate = catalog.rate_for(provider, model_id)
    if rate is None:
        return PriceQuote(
            False,
            0.0,
            "unpriced",
            f"no rate for {provider}:{model_id} in catalog {catalog.version}",
        )
    completion_tokens, output_error = configured_max_output(settings)
    if output_error or completion_tokens is None:
        return PriceQuote(False, 0.0, "output_unbounded", output_error or "output is unbounded")
    prompt_tokens = prompt_token_ceiling(system_text, user_text)
    reasoning_tokens = 0
    if not rate.reasoning_included_in_output:
        reasoning_tokens, reasoning_error = configured_reasoning_ceiling(settings)
        if reasoning_error or reasoning_tokens is None:
            return PriceQuote(
                False,
                0.0,
                "reasoning_unbounded",
                reasoning_error or "reasoning is unbounded",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                reasoning_separate=True,
            )
    elif settings.get("anthropic_thinking_budget_tokens") is not None:
        budget = settings.get("anthropic_thinking_budget_tokens")
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            return PriceQuote(
                False,
                0.0,
                "output_unbounded",
                "anthropic_thinking_budget_tokens must be a non-negative integer",
            )
        if budget >= completion_tokens:
            return PriceQuote(
                False,
                0.0,
                "output_unbounded",
                "anthropic_thinking_budget_tokens must be below max_output_tokens "
                "because those tokens share the output cap",
            )
    cache_read, cache_read_error = configured_cache_ceiling(settings, "max_cache_read_tokens")
    cache_write, cache_write_error = configured_cache_ceiling(settings, "max_cache_write_tokens")
    if cache_read_error or cache_write_error or cache_read is None or cache_write is None:
        return PriceQuote(
            False,
            0.0,
            "cache_unbounded",
            cache_read_error or cache_write_error or "cache ceiling is invalid",
        )
    per_attempt = catalog.estimate(
        provider,
        model_id,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
    )
    if not per_attempt.priced:
        return PriceQuote(
            False,
            0.0,
            per_attempt.status,
            per_attempt.note,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            reasoning_tokens=reasoning_tokens,
            attempts=attempts,
            reasoning_separate=not rate.reasoning_included_in_output,
        )
    return PriceQuote(
        True,
        per_attempt.usd * attempts,
        "priced",
        per_attempt.note,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        attempts=attempts,
        reasoning_separate=not rate.reasoning_included_in_output,
    )


def usage_within_quote(attempts: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...], quote: PriceQuote) -> bool:
    for item in attempts:
        if int(item.get("prompt_tokens", 0)) > quote.prompt_tokens:
            return False
        if int(item.get("completion_tokens", 0)) > quote.completion_tokens:
            return False
        if quote.reasoning_separate and int(item.get("reasoning_tokens", 0)) > quote.reasoning_tokens:
            return False
    return True


def estimate_text_tokens(text: str) -> int:
    """Byte ceiling for one string. Prefer :func:`prompt_token_ceiling` for a call."""

    if not text:
        return PROMPT_FRAMING_TOKENS
    return len(text.encode("utf-8")) + PROMPT_FRAMING_TOKENS


def _usd(tokens: int, per_million: float) -> float:
    return tokens * per_million / 1_000_000


def _cache_cost(
    rate: ModelRate,
    *,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> tuple[float, str, str]:
    if cache_read_tokens == 0 and cache_write_tokens == 0:
        return 0.0, "priced", ""
    if cache_read_tokens and rate.cache_read_per_million is None:
        return (
            0.0,
            "cache_rate_unconfigured",
            f"{rate.provider}:{rate.model_id} reported or reserved cache reads "
            "without a cache read price",
        )
    if cache_write_tokens and rate.cache_write_per_million is None:
        return (
            0.0,
            "cache_rate_unconfigured",
            f"{rate.provider}:{rate.model_id} reported or reserved cache writes "
            "without a cache write price",
        )
    read_rate = rate.cache_read_per_million or 0.0
    write_rate = rate.cache_write_per_million or 0.0
    return (
        _usd(cache_read_tokens, read_rate) + _usd(cache_write_tokens, write_rate),
        "priced",
        "",
    )


def _price(raw: Mapping[str, Any], field: str, key: str) -> float:
    value = raw.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ConfigError(f"{key}.{field} must be a non-negative number")
    return float(value)


def _optional_price(raw: Mapping[str, Any], field: str, key: str) -> float | None:
    if field not in raw or raw[field] is None:
        return None
    return _price(raw, field, key)


def _optional_int(raw: Mapping[str, Any], field: str, key: str) -> int | None:
    if field not in raw or raw[field] is None:
        return None
    value = raw[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{key}.{field} must be a positive integer")
    return value


def _bool_field(raw: Mapping[str, Any], field: str, key: str) -> bool:
    value = raw.get(field)
    if not isinstance(value, bool):
        raise ConfigError(f"{key}.{field} must be a boolean")
    return value
