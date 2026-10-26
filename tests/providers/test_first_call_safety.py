"""First-call safety: ceilings, truncation, budget mismatch, dry-run preflight."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rewardbench.config import load_config
from rewardbench.contracts import FeedbackCondition, ModelClientError
from rewardbench.environments.apollolander.schema import (
    constant_controller,
    demonstration_guidance_controller,
    validate_controller,
)
from rewardbench.prompts import PROMPT_TEMPLATE_ID, SYSTEM_PROMPT, render_messages
from rewardbench.providers import build_model_client, preflight_first_call, require_preflight_ok
from rewardbench.providers.pricing import quote_call, load_catalog

from tests.providers.conftest import FakeTransport, http_json, make_request
from tests.providers.e2e_helpers import APOLLO_SCHEMA, live_client, openai_reply, weak_controller
from tests.providers.test_adapters import _chat


ROOT = Path(__file__).resolve().parents[2]


def test_prompt_asks_for_compact_json_without_tools_or_fences():
    assert PROMPT_TEMPLATE_ID == "rewardbench.prompts.v4"
    assert "compact JSON" in SYSTEM_PROMPT
    assert "markdown fences" in SYSTEM_PROMPT
    assert "Do not call tools" in SYSTEM_PROMPT
    _system, user = render_messages(
        make_request(settings={"max_output_tokens": 800, "reasoning_effort": "none"})
    )
    assert "smallest valid controller" not in user  # removed in v4: it invited a minimal copy
    assert "compact JSON" in user


def test_apollo_controller_sizes_fit_recommended_ceilings():
    constant = json.dumps(constant_controller(0.4, -20), separators=(",", ":"), sort_keys=True)
    guidance = json.dumps(
        demonstration_guidance_controller(), separators=(",", ":"), sort_keys=True
    )
    assert validate_controller(json.loads(constant)).valid
    assert validate_controller(json.loads(guidance)).valid
    # Rough upper bound: ~1 token per 3 chars for dense JSON.
    assert len(constant) // 3 < 400
    assert len(guidance) // 3 < 400
    assert len(guidance) // 3 + 200 < 800  # room for modest reasoning leftovers


def test_openai_payload_bounds_output_sets_model_id_and_omits_tools():
    transport = FakeTransport([http_json(openai_reply(weak_controller()))])
    client = live_client("openai", "gpt-5.4-mini", transport, max_retries=0)
    client.propose(
        make_request(
            settings={
                "max_output_tokens": 800,
                "reasoning_effort": "none",
                "temperature": 0,
                "json_mode": True,
            }
        )
    )
    body = json.loads(transport.requests[0].body)
    assert body["model"] == "gpt-5.4-mini"
    assert body["max_completion_tokens"] == 800
    assert body["reasoning_effort"] == "none"
    assert "temperature" not in body
    assert body["response_format"] == {"type": "json_object"}
    assert "tools" not in body
    assert "tool_choice" not in body
    assert "web_search" not in body
    assert "functions" not in body


def test_truncated_finish_reason_marks_usage_and_explains_parse_failure():
    payload = _chat("{", reasoning=350, prompt=20, completion=400)
    payload["choices"][0]["finish_reason"] = "length"
    transport = FakeTransport([http_json(payload)])
    response = live_client("openai", "gpt-5.4-mini", transport, max_retries=0).propose(
        make_request(settings={"max_output_tokens": 400, "reasoning_effort": "none"})
    )
    assert response.parameters is None
    assert response.parse_error
    assert "finish_reason='length'" in response.parse_error
    assert response.usage["truncated"] is True


def test_budget_mismatch_and_unknown_price_refuse_before_http():
    transport = FakeTransport([http_json(openai_reply(weak_controller()))])
    tiny = live_client("openai", "gpt-5.4-mini", transport, max_retries=0, max_spend_usd=0.000001)
    with pytest.raises(Exception) as exc:
        tiny.propose(make_request(settings={"max_output_tokens": 800}))
    assert transport.requests == []
    assert "cap" in str(exc.value).lower() or "reserved" in str(exc.value).lower()

    unknown = FakeTransport([http_json(openai_reply(weak_controller()))])
    bad = live_client("openai", "not-a-priced-model", unknown, max_retries=0, max_spend_usd=1.0)
    with pytest.raises(ModelClientError) as priced:
        bad.propose(make_request(settings={"max_output_tokens": 100}))
    assert "not-a-priced-model" in str(priced.value)
    assert unknown.requests == []


def test_preflight_first_call_matches_pilot_and_fails_closed_on_mismatch():
    config = load_config(ROOT / "configs/apollolander_pilot_openai_gpt54mini.yaml")
    request = make_request(
        FeedbackCondition.NUMERICAL_REWARD,
        settings=dict(config.model_settings),
    )
    # Swap in Apollo schema text size via environment from make_request is lunar;
    # rebuild with Apollo fixture for a realistic quote.
    from rewardbench.contracts import EnvironmentSpec, ModelRequest, Split

    request = ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp",
        session_id="ses",
        revision_index=0,
        feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
        split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="apollolander",
            display_name="ApolloLander",
            task_description="Land.",
            controller_schema=APOLLO_SCHEMA,
            action_space_summary="thrust",
            observation_space_summary="state",
        ),
        history=(),
        model_settings=dict(config.model_settings),
    )
    ok = require_preflight_ok(
        preflight_first_call(
            provider=config.provider,
            model_id=config.model_id,
            request=request,
            max_spend_usd=0.05,
            http_attempts=1,
        )
    )
    assert ok.ok
    assert ok.quote.completion_tokens == 800
    assert ok.reasoning_effort == "none"

    with pytest.raises(ModelClientError):
        require_preflight_ok(
            preflight_first_call(
                provider=config.provider,
                model_id=config.model_id,
                request=request,
                max_spend_usd=0.000001,
                http_attempts=1,
            )
        )


def test_nofeedback_prompt_still_hides_rewards_after_v2():
    from tests.prompts.test_render import _request

    _system, user = render_messages(_request(FeedbackCondition.NO_FEEDBACK))
    assert "reward=" not in user
    assert "-87.5" not in user
    assert "compact JSON" in _system


def test_dry_run_example_requires_no_api_key_or_network(monkeypatch):
    import os

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    env = {key: value for key, value in os.environ.items() if key != "OPENAI_API_KEY"}
    script = ROOT / "examples/providers/dry_run_first_call.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "No network sockets were opened" in completed.stdout
    assert "preflight: OK" in completed.stdout
    assert "No API key was read" in completed.stdout
    assert "sk-" not in completed.stdout


def test_400_ceiling_with_high_reasoning_is_flagged_by_preflight_notes():
    from rewardbench.contracts import EnvironmentSpec, ModelRequest, Split

    request = ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp",
        session_id="ses",
        revision_index=0,
        feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
        split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="apollolander",
            display_name="ApolloLander",
            task_description="Land.",
            controller_schema=APOLLO_SCHEMA,
            action_space_summary="thrust",
            observation_space_summary="state",
        ),
        history=(),
        model_settings={"max_output_tokens": 400, "reasoning_effort": "high"},
    )
    result = preflight_first_call(
        provider="openai",
        model_id="gpt-5.4-mini",
        request=request,
        max_spend_usd=1.0,
        http_attempts=1,
    )
    assert any("truncating" in note for note in result.notes)
