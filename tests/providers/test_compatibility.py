"""Both environments share one client, and provider bills are not dropped."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from rewardbench.contracts import (
    BudgetExceeded,
    EnvironmentSpec,
    FeedbackCondition,
    ModelClientError,
    ModelRequest,
    Split,
)
from rewardbench.prompts import SYSTEM_PROMPT, render_messages
from rewardbench.providers.capabilities import SPENDING_LIMITS
from rewardbench.providers.pricing import load_catalog, quote_call

from tests.providers.conftest import FakeTransport, http_json
from tests.providers.test_adapters import _anthropic, _chat, _client, _gemini

_SETTINGS = {"max_output_tokens": 400, "max_reasoning_tokens": 16}
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_APOLLO_SCHEMA = json.loads(
    (_FIXTURES / "apollolander_controller_schema.json").read_text(encoding="utf-8")
)
_APOLLO_CONSTANT = json.loads(
    (_FIXTURES / "apollolander_constant_controller.json").read_text(encoding="utf-8")
)

_ENVIRONMENTS = {
    "lunarlander-v3": EnvironmentSpec(
        environment_id="lunarlander-v3",
        display_name="LunarLander-v3",
        task_description="Land the craft between the flag poles using discrete engine actions.",
        controller_schema={
            "schema": "rewardbench.lunarlander.controller.v1",
            "policies": ["heuristic", "linear", "random"],
            "actions": ["idle", "left engine", "main engine", "right engine"],
        },
        action_space_summary="discrete idle, left engine, main engine, or right engine",
        observation_space_summary="x, y, vx, vy, angle, angular velocity, and two leg contacts",
    ),
    "apollolander": EnvironmentSpec(
        environment_id="apollolander",
        display_name="ApolloLander",
        task_description=(
            "Land the Apollo lander upright on the single designated pad of one "
            "fixed lunar map. Every controlled trial starts at the same position, "
            "velocity, rotation, and fuel. Episode seeds name the trial and do not "
            "move the terrain, the pad, or the ship. Submit a controller object, "
            "not JavaScript."
        ),
        controller_schema=_APOLLO_SCHEMA,
        action_space_summary="thrust from 0 to 1 and rotation in 10 degree steps from -90 to 90",
        observation_space_summary=(
            "x, y, vx, vy, rotation, fuel, altitude, and horizontal offset from the pad center"
        ),
    ),
}

_PROPOSALS = {
    "lunarlander-v3": {
        "schema": "rewardbench.lunarlander.controller.v1",
        "policy": "linear",
        "parameters": {"weights": [0.1, -0.2]},
    },
    "apollolander": dict(_APOLLO_CONSTANT),
}

_MODELS = (
    ("openai", "gpt-5.4-mini"),
    ("google", "gemini-3.1-flash-lite"),
    ("anthropic", "claude-haiku-5-5"),
    ("xai", "grok-4.3"),
)


def _request(environment_id: str) -> ModelRequest:
    return ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp_env",
        session_id="ses_env",
        revision_index=0,
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        split=Split.DEVELOPMENT,
        environment=_ENVIRONMENTS[environment_id],
        history=(),
        model_settings=dict(_SETTINGS),
    )


def _payload(provider: str, text: str) -> dict:
    if provider == "google":
        return _gemini(text)
    if provider == "anthropic":
        return _anthropic(text)
    return _chat(text)


def _instruction(provider: str, body: dict) -> tuple[str, str]:
    if provider in {"openai", "xai"}:
        return body["messages"][0]["content"], body["messages"][1]["content"]
    if provider == "anthropic":
        return body["system"], body["messages"][0]["content"]
    return (
        body["systemInstruction"]["parts"][0]["text"],
        body["contents"][0]["parts"][0]["text"],
    )


def test_provider_package_does_not_hardcode_either_controller():
    roots = (
        Path("src/rewardbench/providers"),
        Path("src/rewardbench/prompts"),
    )
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for root in roots
        for path in root.rglob("*.py")
    )
    for needle in (
        "rewardbench.environments",
        "angle_target",
        "main_engine",
        "leg contact",
        "vx_gain",
        "LunarLander",
        "ApolloLander",
        "Gymnasium",
    ):
        assert needle not in text
    assert "in-process only" in text
    joined = " ".join(SPENDING_LIMITS).lower()
    assert "not cross-process" in joined
    assert "not a provider-side spending cap" in joined


def test_actual_apollolander_schema_fixture_matches_environment_document():
    assert _APOLLO_SCHEMA["schema"] == "rewardbench.apollolander.controller.v1"
    assert set(_APOLLO_SCHEMA["policies"]) == {"guidance", "constant"}
    assert "vx_gain" in _APOLLO_SCHEMA["policies"]["guidance"]["parameters"]
    assert _APOLLO_SCHEMA["commands"]["rotation"]["step"] == 10
    assert _APOLLO_CONSTANT["policy"] == "constant"
    assert 0 <= _APOLLO_CONSTANT["thrust"] <= 1


def test_four_providers_propose_either_environment_without_validating_it():
    seen: dict[str, set[str]] = {environment_id: set() for environment_id in _ENVIRONMENTS}
    for environment_id in _ENVIRONMENTS:
        request = _request(environment_id)
        expected_system, expected_user = render_messages(request)
        assert expected_system == SYSTEM_PROMPT
        other = "apollolander" if environment_id == "lunarlander-v3" else "lunarlander"
        assert _ENVIRONMENTS[environment_id].controller_schema["schema"] in expected_user
        assert other not in expected_user.lower()
        if environment_id == "apollolander":
            assert '"vx_gain"' in expected_user
            assert '"guidance"' in expected_user
            assert "not JavaScript" in expected_user
        proposal = _PROPOSALS[environment_id]
        for provider, model_id in _MODELS:
            transport = FakeTransport([http_json(_payload(provider, json.dumps(proposal)))])
            response = _client(provider, model_id, transport).propose(request)
            assert response.parse_error is None
            assert dict(response.parameters) == proposal
            if environment_id == "apollolander":
                assert response.parameters["thrust"] == 0.4
                assert response.parameters["rotation"] == -20
            else:
                assert response.parameters["parameters"]["weights"] == [0.1, -0.2]
            system, user = _instruction(provider, json.loads(transport.requests[0].body))
            assert (system, user) == (expected_system, expected_user)
            assert len(transport.requests) == 1
            seen[environment_id].add(provider)
    assert seen["lunarlander-v3"] == seen["apollolander"] == {"openai", "google", "anthropic", "xai"}


def test_uncapped_call_still_records_the_provider_bill():
    transport = FakeTransport([http_json(_chat(json.dumps(_PROPOSALS["apollolander"]), prompt=10, completion=12))])
    client = _client("openai", "gpt-5.4-mini", transport)
    response = client.propose(_request("apollolander"))
    expected = (10 * 0.75 + 12 * 4.5) / 1_000_000
    assert response.estimated_cost_usd == pytest.approx(expected)
    assert response.usage["spent_usd"] == pytest.approx(expected)
    assert response.usage["budget_exceeded"] is False
    assert response.usage["reservation_exceeded"] is False
    assert response.usage["spending_scope"] == "in_process_only"
    assert client._spending.spent_usd == pytest.approx(expected)
    assert client._spending.held_usd == 0


def test_over_cap_bill_is_kept_and_the_next_call_stops():
    over = FakeTransport(
        [
            http_json(_chat(json.dumps(_PROPOSALS["lunarlander-v3"]), prompt=1, completion=3000)),
            http_json(_chat(json.dumps(_PROPOSALS["lunarlander-v3"]))),
        ]
    )
    client = _client("openai", "gpt-5.4-mini", over, max_spend_usd=0.01)
    with pytest.raises(BudgetExceeded) as exc:
        client.propose(_request("lunarlander-v3"))
    assert exc.value.resource == "provider_cost_usd"
    assert exc.value.spent == pytest.approx((1 * 0.75 + 3000 * 4.5) / 1_000_000)
    assert "over the cap" in str(exc.value)
    assert client._spending.spent_usd == pytest.approx(exc.value.spent)
    assert client._spending.held_usd == 0
    with pytest.raises(BudgetExceeded):
        client.propose(_request("apollolander"))
    assert len(over.requests) == 1


def test_failed_retry_usage_is_added_to_the_successful_bill():
    error_body = {
        "error": {"message": "overloaded"},
        "usage": {
            "prompt_tokens": 40,
            "completion_tokens": 25,
            "total_tokens": 65,
            "completion_tokens_details": {"reasoning_tokens": 7},
        },
    }
    transport = FakeTransport(
        [
            http_json(error_body, status=500),
            http_json(_chat(json.dumps(_PROPOSALS["apollolander"]), prompt=10, completion=12, reasoning=2)),
        ]
    )
    client = _client("openai", "gpt-5.4-mini", transport, max_retries=1, max_spend_usd=20)
    response = client.propose(_request("apollolander"))
    expected = ((40 + 10) * 0.75 + (25 + 12) * 4.5) / 1_000_000
    assert response.prompt_tokens == 50
    assert response.completion_tokens == 37
    assert response.reasoning_tokens == 9
    assert response.usage["spent_usd"] == pytest.approx(expected)
    assert client._spending.spent_usd == pytest.approx(expected)


def test_billed_failure_over_the_cap_stops_the_following_call():
    error_body = {
        "error": {"message": "overloaded"},
        "usage": {"prompt_tokens": 1, "completion_tokens": 3000, "total_tokens": 3001},
    }
    transport = FakeTransport(
        [
            http_json(error_body, status=500),
            http_json(_chat("{}")),
        ]
    )
    client = _client("openai", "gpt-5.4-mini", transport, max_retries=0, max_spend_usd=0.01)
    with pytest.raises(BudgetExceeded) as exc:
        client.propose(_request("lunarlander-v3"))
    assert exc.value.spent == pytest.approx((1 * 0.75 + 3000 * 4.5) / 1_000_000)
    with pytest.raises(BudgetExceeded):
        client.propose(_request("lunarlander-v3"))
    assert len(transport.requests) == 1


def test_gemini_reasoning_above_the_ceiling_is_still_charged():
    transport = FakeTransport(
        [http_json(_gemini(json.dumps(_PROPOSALS["apollolander"]), thoughts=400))]
    )
    client = _client("google", "gemini-3.1-flash-lite", transport, max_spend_usd=5)
    with pytest.raises(ModelClientError) as exc:
        client.propose(_request("apollolander"))
    assert exc.value.retryable is False
    assert "ceiling" in str(exc.value)
    expected = (4 * 0.25 + (8 + 400) * 1.50) / 1_000_000
    assert client._spending.spent_usd == pytest.approx(expected)
    assert client._spending.held_usd == 0


def test_unpriced_cache_charge_is_recorded_and_blocks_later_calls():
    payload = _anthropic(json.dumps(_PROPOSALS["apollolander"]), cache_read=4)
    transport = FakeTransport([http_json(payload), http_json(payload)])
    client = _client("anthropic", "claude-haiku-5-5", transport, max_spend_usd=5)
    with pytest.raises(ModelClientError) as exc:
        client.propose(_request("apollolander"))
    assert "cache" in str(exc.value).lower()
    assert "blocked" in str(exc.value).lower()
    known = (15 * 0.10 + 9 * 0.50) / 1_000_000
    assert client._spending.spent_usd == pytest.approx(known)
    with pytest.raises(BudgetExceeded) as blocked:
        client.propose(_request("apollolander"))
    assert "blocked in this process" in str(blocked.value)
    assert len(transport.requests) == 1


def test_one_in_process_reservation_cannot_be_spent_twice_concurrently():
    request = _request("apollolander")
    system, user = render_messages(request)
    quote = quote_call(
        load_catalog(),
        "openai",
        "gpt-5.4-mini",
        system_text=system,
        user_text=user,
        settings=dict(_SETTINGS),
        attempts=1,
    )
    assert quote.available
    entered = threading.Event()
    release = threading.Event()

    class _Gate(FakeTransport):
        def send(self, request):
            entered.set()
            assert release.wait(5)
            return super().send(request)

    transport = _Gate([http_json(_chat(json.dumps(_PROPOSALS["apollolander"])))])
    client = _client("openai", "gpt-5.4-mini", transport, max_spend_usd=quote.usd)
    outcomes: list[str] = []
    lock = threading.Lock()

    def first() -> None:
        try:
            client.propose(request)
        except BudgetExceeded:
            outcome = "blocked"
        else:
            outcome = "ok"
        with lock:
            outcomes.append(outcome)

    def second() -> None:
        try:
            assert entered.wait(5)
            try:
                client.propose(request)
            except BudgetExceeded:
                outcome = "blocked"
            else:
                outcome = "ok"
            with lock:
                outcomes.append(outcome)
        finally:
            release.set()

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["blocked", "ok"]
    assert len(transport.requests) == 1
    assert client._spending.held_usd == 0
    assert client._spending.spent_usd > 0
    assert client._spending.spent_usd <= quote.usd + 1e-12
