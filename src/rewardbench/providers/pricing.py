"""Versioned provider prices. Model ids are catalog keys, not code constants."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rewardbench.contracts import ConfigError

DEFAULT_CATALOG_VERSION = "2026-10-14"


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
        billed_output = completion_tokens
        if not rate.reasoning_included_in_output:
            billed_output += reasoning_tokens
        usd = _usd(prompt_tokens, input_rate) + _usd(billed_output, output_rate)
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
            note=raw.get("note", "") if isinstance(raw.get("note", ""), str) else "",
        )
    return PricingCatalog(
        version=version,
        currency=currency,
        source=source,
        rates=rates,
    )


def estimate_text_tokens(text: str) -> int:
    """Upper-ish reserve used before a call. This is not a provider tokenizer."""

    if not text:
        return 1
    return max(1, (len(text) + 3) // 4)


def _usd(tokens: int, per_million: float) -> float:
    return tokens * per_million / 1_000_000


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
