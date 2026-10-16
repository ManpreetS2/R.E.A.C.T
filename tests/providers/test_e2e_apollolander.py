"""End-to-end provider preflight: mocked HTTP → real runner → Apollo physics → SQLite.

No live API keys. No paid calls. FakeTransport only.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from rewardbench.contracts import (
    BudgetExceeded,
    ExperimentStatus,
    FailurePolicy,
    FeedbackCondition,
    ModelClientError,
)
from rewardbench.core.runner import ExperimentRunner
from rewardbench.providers import build_model_client
from rewardbench.providers.http import TransportError
from rewardbench.providers.pricing import load_catalog, quote_call

from tests.providers.conftest import FakeTransport, http_json, make_request
from tests.providers.e2e_helpers import (
    APOLLO_SCHEMA,
    SECRET,
    anthropic_reply,
    apollo_config,
    apollo_environment,
    assert_no_numeric_reward_leak,
    gemini_reply,
    guidance_controller,
    live_client,
    openai_reply,
    scripted_transport,
    store_for,
    stronger_controller,
    user_text_from_request,
    weak_controller,
)
from tests.providers.test_adapters import _chat


def test_numerical_two_revisions_flow_through_physics_and_sqlite(tmp_path) -> None:
    controllers = [weak_controller(), stronger_controller()]
    transport = scripted_transport("openai", controllers)
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=0)
    config = apollo_config(tmp_path, name="e2e-numerical-two")
    store = store_for(tmp_path)
    env = apollo_environment(max_steps=40)

    summary = ExperimentRunner(config, model, env, store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.revisions_completed == 2
    assert summary.episodes_recorded == 2
    assert len(model.requests) == 2
    assert len(transport.requests) == 2

    assert model.requests[0].history == ()
    assert model.requests[1].history
    prior = model.requests[1].history[0]
    assert prior.feedback is not None
    assert len(prior.feedback) == 1
    assert prior.feedback[0].total_reward == pytest.approx(
        store.fetch_episodes(summary.experiment_id)[0].total_reward
    )
    assert "seed" not in prior.feedback[0].__dict__

    user0 = user_text_from_request(model.requests[0])
    user1 = user_text_from_request(model.requests[1])
    assert APOLLO_SCHEMA["schema"] in user0
    assert '"vx_gain"' in user0
    assert f"reward={json.dumps(prior.feedback[0].total_reward)}" in user1
    assert dict(model.responses[0].parameters) == weak_controller()
    assert dict(model.responses[1].parameters) == stronger_controller()

    attempts = store.fetch_attempts(summary.experiment_id)
    assert len([item for item in attempts if item.selected and item.valid]) == 2
    episodes = store.fetch_episodes(summary.experiment_id)
    assert all(item.error is None for item in episodes)
    assert all(item.steps == 40 for item in episodes)
    assert summary.total_cost_usd > 0
    assert SECRET not in json.dumps([req.url for req in transport.requests])
    store.close()


def test_nofeedback_never_puts_rewards_in_the_next_provider_request(tmp_path) -> None:
    transport = scripted_transport("openai", [weak_controller(), stronger_controller()])
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=0)
    config = apollo_config(
        tmp_path,
        name="e2e-nofeedback",
        feedback=FeedbackCondition.NO_FEEDBACK,
    )
    store = store_for(tmp_path)
    summary = ExperimentRunner(config, model, apollo_environment(), store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert model.requests[1].history[0].feedback is None
    user1 = user_text_from_request(model.requests[1])
    assert_no_numeric_reward_leak(user1)
    assert "Scores were withheld on purpose" in user1
    stored = store.fetch_episodes(summary.experiment_id)
    assert len(stored) == 2
    assert all(item.total_reward is not None for item in stored)
    body = json.loads(transport.requests[1].body)
    assert stored[0].total_reward != 0 or stored[0].total_reward == 0
    assert str(stored[0].total_reward) not in body["messages"][1]["content"]
    store.close()


def test_malformed_wrong_schema_and_missing_fields_are_validated_not_flown(tmp_path) -> None:
    bad_payloads = [
        "not json at all",
        json.dumps({"schema": "rewardbench.lunarlander.controller.v1", "policy": "constant", "thrust": 0.5, "rotation": 0}),
        json.dumps({"schema": "rewardbench.apollolander.controller.v1", "policy": "constant"}),
    ]
    transport = FakeTransport([http_json(_chat(text)) for text in bad_payloads])
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=2)
    config = apollo_config(
        tmp_path,
        name="e2e-invalids",
        num_revisions=1,
        max_model_retries=2,
    )
    store = store_for(tmp_path)
    env = apollo_environment()
    summary = ExperimentRunner(config, model, env, store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.episodes_recorded == 0
    assert summary.invalid_revisions == 1
    assert len(transport.requests) == 3
    attempts = store.fetch_attempts(summary.experiment_id)
    assert len(attempts) == 3
    assert all(not item.valid for item in attempts)
    assert attempts[-1].selected is True
    assert store.fetch_episodes(summary.experiment_id) == []
    store.close()


def test_rate_limit_retries_then_exhaustion_aborts(tmp_path) -> None:
    overloaded = http_json({"error": {"message": "slow down"}}, status=429, headers={"Retry-After": "0"})
    transport = FakeTransport([overloaded, overloaded, overloaded])
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=1)
    config = replace(
        apollo_config(tmp_path, name="e2e-retry-exhaust", num_revisions=1, max_model_retries=0),
        on_model_failure=FailurePolicy.ABORT,
    )
    store = store_for(tmp_path)
    summary = ExperimentRunner(config, model, apollo_environment(), store).run()
    # Runner converts ExperimentAborted into a FAILED summary for the caller.
    assert summary.status is ExperimentStatus.FAILED
    assert summary.error is not None
    assert "slow down" in summary.error.lower() or "429" in summary.error
    assert summary.episodes_recorded == 0
    assert len(transport.requests) == 2  # client max_retries=1 → 2 HTTP tries for one propose
    store.close()


def test_transport_timeout_is_retryable_and_exhausts() -> None:
    transport = FakeTransport(
        [
            TransportError("provider request timed out", retryable=True),
            TransportError("provider request timed out", retryable=True),
        ]
    )
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=1)
    with pytest.raises(ModelClientError) as exc:
        model.propose(make_request(settings={"max_output_tokens": 100}))
    assert exc.value.retryable is True
    assert len(transport.requests) == 2


def test_four_providers_usage_accounting_with_authentic_shapes(tmp_path) -> None:
    controller = weak_controller()
    cases = [
        (
            "openai",
            "gpt-5.4-mini",
            http_json(openai_reply(controller, prompt=200, completion=90, reasoning=25)),
            {"prompt": 200, "completion": 90, "reasoning": 25},
            (200 * 0.75 + 90 * 4.5) / 1_000_000,
        ),
        (
            "google",
            "gemini-3.1-flash-lite",
            http_json(gemini_reply(controller, thoughts=30)),
            {"prompt": 4, "completion": 8, "reasoning": 30},
            (4 * 0.25 + (8 + 30) * 1.5) / 1_000_000,
        ),
        (
            "anthropic",
            "claude-haiku-5-5",
            http_json(anthropic_reply(controller)),
            {"prompt": 15, "completion": 9, "reasoning": 0},
            (15 * 0.10 + 9 * 0.50) / 1_000_000,
        ),
        (
            "xai",
            "grok-4.3",
            http_json(
                _chat(
                    json.dumps(controller),
                    prompt=110,
                    completion=55,
                    reasoning=7,
                    model="grok-4.3",
                )
            ),
            {"prompt": 110, "completion": 55, "reasoning": 7},
            (110 * 1.25 + 55 * 2.5) / 1_000_000,
        ),
    ]
    for provider, model_id, response, tokens, expected_cost in cases:
        transport = FakeTransport([response])
        settings = {"max_output_tokens": 400}
        if provider == "google":
            settings["max_reasoning_tokens"] = 64
        model = live_client(provider, model_id, transport, max_retries=0)
        config = apollo_config(
            tmp_path / provider,
            name=f"e2e-usage-{provider}",
            provider=provider,
            model_id=model_id,
            num_revisions=1,
            model_settings=settings,
        )
        store = store_for(tmp_path / provider)
        summary = ExperimentRunner(config, model, apollo_environment(), store).run()
        assert summary.status is ExperimentStatus.COMPLETED
        response_obj = model.responses[0]
        assert response_obj.prompt_tokens == tokens["prompt"]
        assert response_obj.completion_tokens == tokens["completion"]
        assert response_obj.reasoning_tokens == tokens["reasoning"]
        assert response_obj.estimated_cost_usd == pytest.approx(expected_cost)
        assert response_obj.usage["cost_status"] == "priced"
        if provider == "openai":
            assert response_obj.usage["extra_usage"]["reasoning_included_in_completion_tokens"] is True
        if provider == "google":
            assert response_obj.usage["extra_usage"]["reasoning_billed_separately"] is True
        store.close()


def test_anthropic_cache_charge_fails_closed_and_blocks_followup() -> None:
    payload = anthropic_reply(weak_controller(), cache_read=12)
    transport = FakeTransport([http_json(payload), http_json(payload)])
    model = live_client("anthropic", "claude-haiku-5-5", transport, max_retries=0, max_spend_usd=5)
    with pytest.raises(ModelClientError) as exc:
        model.propose(make_request(settings={"max_output_tokens": 200}))
    assert "cache" in str(exc.value).lower()
    assert "blocked" in str(exc.value).lower()
    with pytest.raises(BudgetExceeded):
        model.propose(make_request(settings={"max_output_tokens": 200}))
    assert len(transport.requests) == 1


def test_unknown_model_and_gemini_without_reasoning_ceiling_fail_before_http() -> None:
    unknown = FakeTransport([http_json(openai_reply(weak_controller()))])
    client = live_client("openai", "gpt-4.1-not-in-catalog", unknown, max_retries=0, max_spend_usd=1)
    with pytest.raises(ModelClientError) as exc:
        client.propose(make_request(settings={"max_output_tokens": 100}))
    assert "gpt-4.1-not-in-catalog" in str(exc.value)
    assert unknown.requests == []

    gemini = FakeTransport([http_json(gemini_reply(weak_controller()))])
    capped = live_client("google", "gemini-3.1-flash-lite", gemini, max_retries=0, max_spend_usd=1)
    with pytest.raises(ModelClientError) as exc2:
        capped.propose(make_request(settings={"max_output_tokens": 200}))
    assert "reasoning" in str(exc2.value).lower()
    assert gemini.requests == []


def test_pilot_quote_for_gpt54mini_is_bounded_before_any_call() -> None:
    from rewardbench.config import load_config

    catalog = load_catalog()
    pilot = load_config("configs/apollolander_pilot_openai_gpt54mini.yaml")
    assert pilot.provider == "openai"
    assert pilot.model_id == "gpt-5.4-mini"
    assert pilot.environment_id == "apollolander"
    assert pilot.model_settings["max_output_tokens"] == 800
    assert pilot.model_settings["reasoning_effort"] == "none"
    assert pilot.max_model_retries == 0
    assert pilot.budget.max_cost_usd == pytest.approx(0.05)
    assert pilot.metadata.get("approval_required") is True

    system = "You are proposing a controller for a closed reward-adaptation experiment."
    user = "Controller schema:\n" + json.dumps(APOLLO_SCHEMA, sort_keys=True)
    quote = quote_call(
        catalog,
        pilot.provider,
        pilot.model_id,
        system_text=system,
        user_text=user,
        settings=dict(pilot.model_settings),
        attempts=pilot.max_model_retries + 1,
    )
    assert quote.available
    assert quote.completion_tokens == 800
    assert quote.attempts == 1
    assert quote.usd > 0
    # One reserved attempt at the pilot output ceiling stays under the $0.05 software target
    # for typical Apollo prompts; this is a reservation estimate, not a billing guarantee.
    assert quote.usd < 0.05


def test_missing_api_key_fails_closed_without_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ModelClientError) as exc:
        build_model_client("openai", "gpt-5.4-mini")
    assert "OPENAI_API_KEY" in str(exc.value)


def test_guidance_controller_from_mocked_provider_can_complete_a_short_episode(tmp_path) -> None:
    """Valid Apollo schema object from the provider reaches real physics."""

    transport = scripted_transport("openai", [guidance_controller()])
    model = live_client("openai", "gpt-5.4-mini", transport, max_retries=0)
    config = apollo_config(
        tmp_path,
        name="e2e-guidance-short",
        num_revisions=1,
        max_episode_steps=80,
    )
    store = store_for(tmp_path)
    summary = ExperimentRunner(config, model, apollo_environment(max_steps=80), store).run()
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.episodes_recorded == 1
    episode = store.fetch_episodes(summary.experiment_id)[0]
    assert episode.error is None
    assert episode.steps <= 80
    assert model.responses[0].parse_error is None
    assert model.responses[0].parameters["policy"] == "guidance"
    store.close()
