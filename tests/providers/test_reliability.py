"""Pricing failures, retry reservations, bad payloads, and feedback isolation."""

from __future__ import annotations

import json
import threading

import pytest

from rewardbench.config import load_config
from rewardbench.contracts import BudgetExceeded, FeedbackCondition, ModelClientError
from rewardbench.prompts import SYSTEM_PROMPT, render_messages
from rewardbench.providers.limits import SpendingGuard
from rewardbench.providers.pricing import load_catalog, quote_call

from tests.providers.conftest import CONTROLLER, FakeTransport, http_json, make_request
from tests.providers.test_adapters import _chat, _client, _gemini


def test_sample_configurations_quote_before_any_call():
    catalog = load_catalog()
    paths = [
        "configs/lunarlander_development_numerical.yaml",
        "configs/lunarlander_development_nofeedback.yaml",
        "configs/lunarlander_heldout_numerical.yaml",
    ]
    seen = set()
    for path in paths:
        config = load_config(path)
        assert config.provider == "openai"
        assert config.model_id == "gpt-5.4-mini"
        assert config.model_settings["max_output_tokens"] == 800
        quote = quote_call(
            catalog,
            config.provider,
            config.model_id,
            system_text=SYSTEM_PROMPT,
            user_text="Land between the flags.",
            settings=dict(config.model_settings),
            attempts=config.max_model_retries + 1,
        )
        assert quote.available, quote.note
        assert quote.usd > 0
        assert quote.completion_tokens == 800
        assert quote.attempts == config.max_model_retries + 1
        seen.add(config.feedback_condition)
    assert seen == {FeedbackCondition.NUMERICAL_REWARD, FeedbackCondition.NO_FEEDBACK}


def test_unpriced_model_is_refused_before_http_even_without_a_cap():
    transport = FakeTransport([http_json(_chat(json.dumps(CONTROLLER)))])
    client = _client("openai", "gpt-4.1", transport)
    with pytest.raises(ModelClientError) as exc:
        client.propose(make_request())
    assert exc.value.retryable is False
    assert "gpt-4.1" in str(exc.value)
    assert transport.requests == []


def test_gemini_without_a_reasoning_ceiling_is_refused():
    transport = FakeTransport([http_json(_gemini(json.dumps(CONTROLLER)))])
    client = _client("google", "gemini-3.1-flash-lite", transport, max_spend_usd=5)
    with pytest.raises(ModelClientError) as exc:
        client.propose(make_request(settings={"max_output_tokens": 200}))
    assert "reasoning" in str(exc.value)
    assert transport.requests == []


def test_provider_retries_are_reserved_before_the_first_request():
    transport = FakeTransport([http_json(_chat(json.dumps(CONTROLLER)))])
    client = _client(
        "openai",
        "gpt-5.4-mini",
        transport,
        max_retries=2,
        max_spend_usd=0.005,
    )
    with pytest.raises(BudgetExceeded):
        client.propose(make_request(settings={"max_output_tokens": 800}))
    assert transport.requests == []


def test_billed_output_above_the_ceiling_is_rejected_when_the_dollar_cap_still_fits():
    transport = FakeTransport(
        [http_json(_chat(json.dumps(CONTROLLER), prompt=1, completion=50, reasoning=0))]
    )
    client = _client("openai", "gpt-5.4-mini", transport, max_spend_usd=50)
    with pytest.raises(ModelClientError) as exc:
        client.propose(make_request(settings={"max_output_tokens": 10}))
    assert exc.value.retryable is False
    assert "ceiling" in str(exc.value)
    assert len(transport.requests) == 1


def test_malformed_payloads_are_rejected_for_every_provider():
    payloads = {
        "openai": _chat("not json"),
        "xai": _chat("[1, 2]"),
        "google": _gemini('{"policy":"heuristic"} trailing'),
        "anthropic": {"id": "msg", "model": "claude", "stop_reason": "end_turn", "content": [{"type": "text", "text": "[]"}], "usage": {"input_tokens": 3, "output_tokens": 2}},
    }
    models = {
        "openai": "gpt-5.4-mini",
        "xai": "grok-4.3",
        "google": "gemini-3.1-flash-lite",
        "anthropic": "claude-haiku-5-5",
    }
    for provider, payload in payloads.items():
        transport = FakeTransport([http_json(payload)])
        settings = {"max_output_tokens": 100}
        if provider == "google":
            settings["max_reasoning_tokens"] = 8
        response = _client(provider, models[provider], transport).propose(make_request(settings=settings))
        assert response.parameters is None
        assert response.parse_error
        assert response.estimated_cost_usd != 999


def test_self_reported_reward_is_not_the_billed_cost_and_feedback_stays_isolated():
    body = json.dumps({**CONTROLLER, "reward": 999999})
    transport = FakeTransport([http_json(_chat(body, prompt=10, completion=12))])
    response = _client("openai", "gpt-5.4-mini", transport).propose(
        make_request(settings={"max_output_tokens": 100})
    )
    assert response.estimated_cost_usd < 1
    assert response.estimated_cost_usd != 999999
    assert dict(response.parameters)["reward"] == 999999

    from rewardbench.contracts import EnvironmentSpec, ModelRequest, PriorAttempt, RewardFeedback, Split

    history = (
        PriorAttempt(
            revision_index=0,
            parameters={"skill": "walk"},
            valid=True,
            validation_error=None,
            feedback=(
                RewardFeedback(
                    revision_index=0,
                    episode_index=0,
                    total_reward=-12.25,
                    success=False,
                    crashed=None,
                    steps=4,
                    metrics={},
                ),
            ),
        ),
    )
    spec = EnvironmentSpec(
        environment_id="minecraft-navigation",
        display_name="Navigation",
        task_description="Reach the checkpoint.",
        controller_schema={"skill": "walk"},
        action_space_summary="walk or wait",
        observation_space_summary="position and health",
    )
    numerical = ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp",
        session_id="ses",
        revision_index=1,
        feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
        split=Split.DEVELOPMENT,
        environment=spec,
        history=history,
        model_settings={},
    )
    hidden = ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp",
        session_id="ses",
        revision_index=1,
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        split=Split.DEVELOPMENT,
        environment=spec,
        history=history,
        model_settings={},
    )
    num_system, num_user = render_messages(numerical)
    hid_system, hid_user = render_messages(hidden)
    assert num_system == hid_system == SYSTEM_PROMPT
    assert "Reach the checkpoint." in num_user and "Reach the checkpoint." in hid_user
    assert "LunarLander" not in num_user
    assert "reward=-12.25" in num_user
    assert "-12.25" not in hid_user


def test_shared_spending_guard_rejects_a_second_concurrent_reservation():
    guard = SpendingGuard(max_spend_usd=0.10)
    started = threading.Barrier(2)
    results: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        started.wait()
        try:
            guard.reserve(0.06)
        except BudgetExceeded:
            outcome = "blocked"
        else:
            outcome = "reserved"
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ["blocked", "reserved"]
    assert guard.held_usd == pytest.approx(0.06)
    assert guard.spent_usd == 0


@pytest.mark.parametrize("failure", ["http", "quote", "budget"])
def test_billed_failures_carry_accounting_response(failure):
    if failure == "http":
        payload = {"error": {"message": "billed failure"},
                   "usage": {"prompt_tokens": 20, "completion_tokens": 11, "total_tokens": 31}}
        transport = FakeTransport([http_json(payload, status=400, latency=.7)])
        settings = {"max_output_tokens": 100}
    else:
        transport = FakeTransport([http_json(_chat(json.dumps(CONTROLLER), prompt=20,
                                                   completion=100000), latency=.7)])
        settings = {"max_output_tokens": 10}
    client = _client("openai", "gpt-5.4-mini", transport, max_retries=0,
                     max_spend_usd=.01 if failure == "budget" else 50)
    expected = BudgetExceeded if failure == "budget" else ModelClientError
    with pytest.raises(expected) as caught:
        client.propose(make_request(settings=settings))
    response = caught.value.response
    assert response is not None
    assert response.prompt_tokens == 20
    assert response.completion_tokens == (11 if failure == "http" else 100000)
    assert response.charged_tokens == response.prompt_tokens + response.completion_tokens
    assert response.latency_seconds == .7
    assert response.estimated_cost_usd > 0
    assert response.estimated_cost_usd == pytest.approx(client._spending.spent_usd)
    assert client._spending.held_usd == 0
    assert response.usage["prompt_template"]
    assert response.usage["pricing_version"]
    assert response.usage["requested_settings"] == settings
    assert response.usage["retry_count"] == 0
    assert response.usage["budget_exceeded"] is (failure == "budget")
    assert len(transport.requests) == 1
    if failure != "http":
        assert response.raw_text == json.dumps(CONTROLLER)
        assert response.usage["request_id"] == "req-1"
        assert response.usage["response_model_id"] == "response-model"
        assert response.usage["applied_settings"]


def test_exhausted_http_retries_carry_aggregate_billed_usage():
    payload = {"error": {"message": "try again"},
               "usage": {"prompt_tokens": 20, "completion_tokens": 11, "total_tokens": 31}}
    transport = FakeTransport([http_json(payload, status=500, latency=.3),
                               http_json(payload, status=500, latency=.7)])
    client = _client("openai", "gpt-5.4-mini", transport, max_retries=1)
    with pytest.raises(ModelClientError) as caught:
        client.propose(make_request())
    response = caught.value.response
    assert (response.prompt_tokens, response.completion_tokens, response.total_tokens) == (40, 22, 62)
    assert response.latency_seconds == 1
    assert response.estimated_cost_usd == pytest.approx(client._spending.spent_usd)
    assert response.usage["retry_count"] == 1
    assert len(response.usage["calls"]) == 2
    assert len(client.invocations) == 1
    assert "HTTP 500" in client.invocations[0]["error"]


@pytest.mark.parametrize('cache_field', ['cache_read_input_tokens', 'cache_creation_input_tokens', 'cache_write_input_tokens'])
def test_billed_http_cache_usage_is_preserved_and_blocks_retries(cache_field):
    usage = {'input_tokens': 20, 'output_tokens': 11, cache_field: 400}
    payload = {'error': {'message': 'billed failure'}, 'usage': usage}
    transport = FakeTransport([
        http_json(payload, status=500, latency=.7),
        http_json(payload, status=500, latency=.7),
    ])
    client = _client('anthropic', 'claude-haiku-5-5', transport, max_retries=1)
    with pytest.raises(ModelClientError) as caught:
        client.propose(make_request(settings={'max_output_tokens': 800}))
    response = caught.value.response
    assert response is not None
    assert response.usage['cost_status'] != 'priced'
    assert response.usage['calls'][0]['extra_usage'][cache_field] == 400
    assert response.usage['extra_usage']['cache_read_input_tokens' if cache_field == 'cache_read_input_tokens' else 'cache_write_input_tokens'] == 400
    assert response.prompt_tokens == 20 and response.completion_tokens == 11
    assert response.latency_seconds == .7
    assert 'cache' in response.usage['pricing_note'].lower()
    assert response.estimated_cost_usd > 0
    assert client._spending.spent_usd == pytest.approx(response.estimated_cost_usd)
    assert client._spending.held_usd == 0
    assert len(transport.requests) == 1  # The internal retry was forbidden.
    with pytest.raises(BudgetExceeded, match='spending is blocked'):
        client.propose(make_request(settings={'max_output_tokens': 800}))
    assert len(transport.requests) == 1  # A subsequent propose is forbidden too.
