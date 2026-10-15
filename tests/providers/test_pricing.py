"""Catalog math from the 14 October 2026 planning prices."""

from __future__ import annotations

from rewardbench.providers.pricing import load_catalog

# One call at 5,000 input and 1,000 output tokens, then 125 calls.
CASES = {
    "openai:gpt-5.4-mini": 0.00825,
    "google:gemini-3.1-flash-lite": 0.00275,
    "anthropic:claude-haiku-5-5": 0.001,
    "xai:grok-4.3": 0.00875,
}


def test_planning_snapshot_matches_master_plan_formula():
    catalog = load_catalog()
    assert catalog.version == "2026-10-14"
    totals = {}
    for key, per_call in CASES.items():
        provider, model_id = key.split(":", 1)
        estimate = catalog.estimate(
            provider,
            model_id,
            prompt_tokens=5_000,
            completion_tokens=1_000,
            reasoning_tokens=0,
        )
        assert estimate.priced
        assert estimate.usd == per_call
        totals[key] = per_call * 125
    assert totals["openai:gpt-5.4-mini"] == 1.03125
    assert totals["google:gemini-3.1-flash-lite"] == 0.34375
    assert totals["anthropic:claude-haiku-5-5"] == 0.125
    assert round(totals["xai:grok-4.3"], 4) == 1.0938


def test_gemini_reasoning_is_priced_separately_and_openai_reasoning_is_not():
    catalog = load_catalog()
    gemini = catalog.estimate(
        "google",
        "gemini-3.1-flash-lite",
        prompt_tokens=0,
        completion_tokens=100,
        reasoning_tokens=50,
    )
    openai = catalog.estimate(
        "openai",
        "gpt-5.4-mini",
        prompt_tokens=0,
        completion_tokens=100,
        reasoning_tokens=50,
    )
    assert gemini.usd == 150 * 1.5 / 1_000_000
    assert openai.usd == 100 * 4.5 / 1_000_000


def test_claude_long_context_is_unpriced_until_a_rate_is_configured():
    catalog = load_catalog()
    estimate = catalog.estimate(
        "anthropic",
        "claude-haiku-5-5",
        prompt_tokens=100_001,
        completion_tokens=10,
        reasoning_tokens=0,
    )
    assert estimate.status == "long_context_rate_unconfigured"
    assert estimate.usd == 0.0


def test_unknown_model_id_is_not_given_a_made_up_price():
    catalog = load_catalog()
    estimate = catalog.estimate(
        "openai",
        "gpt-4.1",
        prompt_tokens=10,
        completion_tokens=10,
        reasoning_tokens=0,
    )
    assert estimate.status == "unpriced"
    assert "gpt-4.1" in estimate.note


def test_retired_grok_fast_slug_is_not_in_the_catalog():
    catalog = load_catalog()
    assert catalog.rate_for("xai", "grok-4.1-fast") is None
    assert catalog.rate_for("xai", "grok-4.3") is not None
