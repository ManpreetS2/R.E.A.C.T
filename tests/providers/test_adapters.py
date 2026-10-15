"""Mocked HTTP for GPT, Gemini, Claude, and Grok. No paid calls."""

from __future__ import annotations

import json
import random
import urllib.request

import pytest

from rewardbench.contracts import BudgetExceeded, FeedbackCondition, ModelClient, ModelClientError
from rewardbench.providers import build_model_client
from rewardbench.providers.http import HttpResponse, TransportError

from tests.providers.conftest import CONTROLLER, FakeTransport, http_json, make_request, prior

SECRET = "sk-test-secret-value"


def _chat(content: str, *, reasoning: int = 0, prompt: int = 20, completion: int = 11, model: str = "response-model"):
    return {
        "id": "req-1",
        "model": model,
        "choices": [
            {"finish_reason": "stop", "message": {"role": "assistant", "content": content}}
        ],
        "usage": {
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "total_tokens": prompt + completion,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
        },
    }


def _client(provider: str, model_id: str, transport: FakeTransport, **kwargs):
    return build_model_client(
        provider,
        model_id,
        transport=transport,
        api_key=SECRET,
        max_retries=kwargs.pop("max_retries", 0),
        timeout_s=5,
        rng=random.Random(0),
        **kwargs,
    )


def test_four_providers_are_interchangeable_on_the_same_controller():
    text = json.dumps(CONTROLLER)
    specs = [
        ("openai", "gpt-5.4-mini", _chat(text, reasoning=9), "https://api.openai.com/v1/chat/completions"),
        ("google", "gemini-3.1-flash-lite", _gemini(text), "generativelanguage.googleapis.com"),
        ("anthropic", "claude-haiku-5-5", _anthropic(text), "https://api.anthropic.com/v1/messages"),
        ("xai", "grok-4.3", _chat(text), "https://api.x.ai/v1/chat/completions"),
    ]
    parsed = []
    for provider, model_id, payload, url_part in specs:
        transport = FakeTransport([http_json(payload, latency=0.4)])
        client = _client(provider, model_id, transport)
        assert isinstance(client, ModelClient)
        response = client.propose(
            make_request(settings={"temperature": 0, "top_k": 20, "seed": 7})
        )
        assert response.parse_error is None
        assert dict(response.parameters)["policy"] == "heuristic"
        assert response.model_id == model_id
        assert response.provider == provider
        assert response.latency_seconds == 0.4
        assert url_part in transport.requests[0].url
        assert SECRET not in transport.requests[0].url
        parsed.append(dict(response.parameters))
        body = json.loads(transport.requests[0].body)
        assert "tools" not in body
        assert "web_search" not in body
    assert parsed[0] == parsed[1] == parsed[2] == parsed[3]


def test_provider_sampling_knobs_are_not_copied_blindly():
    text = json.dumps(CONTROLLER)
    settings = {
        "temperature": 0,
        "top_p": 0.2,
        "top_k": 10,
        "seed": 7,
        "reasoning_effort": "low",
        "grok_reasoning_effort": "high",
        "max_output_tokens": 120,
    }

    openai = FakeTransport([http_json(_chat(text))])
    _client("openai", "gpt-5.4-mini", openai).propose(make_request(settings=settings))
    openai_body = json.loads(openai.requests[0].body)
    assert openai_body["model"] == "gpt-5.4-mini"
    assert openai_body["max_completion_tokens"] == 120
    assert "temperature" not in openai_body
    assert "top_p" not in openai_body
    assert openai_body["reasoning_effort"] == "low"
    assert openai_body["seed"] == 7
    assert openai_body["response_format"] == {"type": "json_object"}
    assert "top_k" not in openai_body

    grok = FakeTransport([http_json(_chat(text))])
    response = _client("xai", "grok-custom-id", grok).propose(make_request(settings=settings))
    grok_body = json.loads(grok.requests[0].body)
    assert grok_body["model"] == "grok-custom-id"
    assert grok_body["max_tokens"] == 120
    assert "max_completion_tokens" not in grok_body
    assert grok_body["reasoning_effort"] == "high"
    assert "seed" not in grok_body
    assert "temperature" not in grok_body
    assert response.usage["ignored_settings"]["seed"]
    assert response.usage["response_model_id"] == "response-model"

    claude = FakeTransport([http_json(_anthropic(text))])
    claude_response = _client("anthropic", "claude-haiku-5-5", claude).propose(
        make_request(settings={**settings, "anthropic_thinking_budget_tokens": 200})
    )
    claude_body = json.loads(claude.requests[0].body)
    assert claude_body["system"].startswith("You are proposing a controller")
    assert claude_body["max_tokens"] == 120
    assert claude_body["thinking"]["budget_tokens"] == 200
    assert "temperature" not in claude_body
    assert claude_body["top_k"] == 10
    assert "seed" not in claude_body
    assert "response_format" not in claude_body
    assert "json_mode" in claude_response.usage["ignored_settings"]
    assert claude.requests[0].headers["x-api-key"] == SECRET
    assert claude.requests[0].headers["anthropic-version"] == "2023-06-01"

    gemini = FakeTransport([http_json(_gemini(text, thoughts=15))])
    gemini_response = _client("google", "gemini-3.1-flash-lite", gemini).propose(
        make_request(settings=settings)
    )
    gemini_body = json.loads(gemini.requests[0].body)
    assert gemini_body["systemInstruction"]["parts"][0]["text"].startswith("You are proposing")
    assert gemini_body["generationConfig"]["responseMimeType"] == "application/json"
    assert gemini_body["generationConfig"]["topK"] == 10
    assert "seed" not in gemini_body["generationConfig"]
    assert "thinkingConfig" not in gemini_body["generationConfig"]
    assert gemini.requests[0].headers["x-goog-api-key"] == SECRET
    assert "key=" not in gemini.requests[0].url
    assert gemini_response.reasoning_tokens == 15
    assert gemini_response.usage["cost_status"] == "priced"
    # 20 prompt tokens are not in this fixture; thoughts are billed at the output rate.
    assert gemini_response.completion_tokens == 8
    assert gemini_response.estimated_cost_usd == pytest.approx(
        (4 * 0.25 + (8 + 15) * 1.5) / 1_000_000
    )


def test_openai_reports_reasoning_tokens_without_billing_them_twice():
    transport = FakeTransport([http_json(_chat(json.dumps(CONTROLLER), reasoning=30, prompt=1000, completion=80))])
    response = _client("openai", "gpt-5.4-mini", transport).propose(make_request())
    assert response.reasoning_tokens == 30
    assert response.prompt_tokens == 1000
    assert response.completion_tokens == 80
    assert response.total_tokens == 1080
    assert response.estimated_cost_usd == pytest.approx((1000 * 0.75 + 80 * 4.5) / 1_000_000)
    assert response.usage["extra_usage"]["reasoning_included_in_completion_tokens"] is True


def test_unparsable_success_is_a_response_not_an_exception():
    transport = FakeTransport([http_json(_chat("not json"))])
    response = _client("openai", "gpt-5.4-mini", transport).propose(make_request())
    assert response.parameters is None
    assert response.parse_error
    assert response.prompt_tokens == 20


def test_mock_is_offline_and_keeps_reward_history(monkeypatch):
    def explode(*_args, **_kwargs):
        raise AssertionError("mock adapter opened a socket")

    monkeypatch.setattr(urllib.request, "urlopen", explode)
    client = build_model_client(
        "mock",
        "offline-model",
        mock_script=[json.dumps(CONTROLLER)],
    )
    numerical = client.propose(
        make_request(
            FeedbackCondition.NUMERICAL_REWARD,
            history=(prior(FeedbackCondition.NUMERICAL_REWARD),),
        )
    )
    withheld = client.propose(
        make_request(
            FeedbackCondition.NO_FEEDBACK,
            history=(prior(FeedbackCondition.NO_FEEDBACK),),
        )
    )
    assert numerical.parse_error is None
    assert numerical.provider == "mock"
    assert numerical.usage["extra_usage"]["offline"] is True
    user = client._backend.calls[0]["user"]
    assert "reward=-87.5" in user
    assert "missing heuristic parameter" in user
    hidden = client._backend.calls[1]["user"]
    assert "-87.5" not in hidden
    assert withheld.model_id == "offline-model"


def test_retry_timeout_auth_and_redaction(caplog):
    retry_transport = FakeTransport(
        [
            http_json({"error": {"message": "slow down"}}, status=429, headers={"Retry-After": "0"}),
            http_json(_chat(json.dumps(CONTROLLER))),
        ]
    )
    slept = []
    client = _client(
        "openai",
        "gpt-5.4-mini",
        retry_transport,
        max_retries=2,
        sleeper=slept.append,
    )
    response = client.propose(make_request())
    assert response.parse_error is None
    assert response.usage["retry_count"] == 1
    assert len(retry_transport.requests) == 2
    assert slept == [0.0]

    timeout_transport = FakeTransport(
        [TransportError("provider request timed out", retryable=True)]
    )
    timeout_client = _client("openai", "gpt-5.4-mini", timeout_transport, max_retries=0)
    with pytest.raises(ModelClientError) as timeout_exc:
        timeout_client.propose(make_request())
    assert timeout_exc.value.retryable is True

    auth = FakeTransport(
        [http_json({"error": {"message": f"bad key {SECRET}"}}, status=401)]
    )
    auth_client = _client("openai", "gpt-5.4-mini", auth, max_retries=2)
    caplog.set_level("INFO", logger="rewardbench.providers")
    with pytest.raises(ModelClientError) as auth_exc:
        auth_client.propose(make_request())
    assert auth_exc.value.retryable is False
    assert len(auth.requests) == 1
    assert SECRET not in str(auth_exc.value)
    assert SECRET not in caplog.text
    assert SECRET not in json.dumps(auth_client.invocations)


def test_spending_cap_stops_before_an_unaffordable_call_and_after_real_usage():
    blocked = FakeTransport([http_json(_chat(json.dumps(CONTROLLER)))])
    client = _client("openai", "gpt-5.4-mini", blocked, max_spend_usd=0.001)
    with pytest.raises(BudgetExceeded) as exc:
        client.propose(make_request())
    assert exc.value.resource == "provider_cost_usd"
    assert blocked.requests == []

    first = http_json(_chat(json.dumps(CONTROLLER), prompt=0, completion=3000, reasoning=0))
    second = FakeTransport([first, http_json(_chat(json.dumps(CONTROLLER)))])
    capped = _client("openai", "gpt-5.4-mini", second, max_spend_usd=0.01)
    response = capped.propose(make_request(settings={"max_output_tokens": 1}))
    assert response.estimated_cost_usd == pytest.approx(3000 * 4.5 / 1_000_000)
    with pytest.raises(BudgetExceeded):
        capped.propose(make_request(settings={"max_output_tokens": 1}))
    assert len(second.requests) == 1


def test_unknown_price_with_a_cap_does_not_call_the_provider():
    transport = FakeTransport([http_json(_chat(json.dumps(CONTROLLER)))])
    client = _client("openai", "gpt-4.1", transport, max_spend_usd=5)
    with pytest.raises(ModelClientError) as exc:
        client.propose(make_request())
    assert exc.value.retryable is False
    assert "gpt-4.1" in str(exc.value)
    assert transport.requests == []


def test_missing_key_and_rate_limit(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ModelClientError) as exc:
        build_model_client("anthropic", "claude-haiku-5-5")
    assert "ANTHROPIC_API_KEY" in str(exc.value)

    class Clock:
        def __init__(self) -> None:
            self.now = 0.0
            self.slept: list[float] = []

        def time(self) -> float:
            return self.now

        def sleep(self, seconds: float) -> None:
            self.slept.append(seconds)
            self.now += seconds

    clock = Clock()
    transport = FakeTransport(
        [
            http_json(_chat(json.dumps(CONTROLLER))),
            http_json(_chat(json.dumps(CONTROLLER))),
        ]
    )
    client = build_model_client(
        "openai",
        "gpt-5.4-mini",
        transport=transport,
        api_key="local-test",
        min_interval_s=5,
        clock=clock.time,
        sleeper=clock.sleep,
        max_retries=0,
        max_spend_usd=20,
    )
    client.propose(make_request(settings={"max_output_tokens": 1}))
    client.propose(make_request(settings={"max_output_tokens": 1}))
    assert clock.slept == [5.0]
    assert len(transport.requests) == 2


def _gemini(text: str, *, thoughts: int = 0) -> dict:
    return {
        "responseId": "gem-1",
        "modelVersion": "gemini-3.1-flash-lite-001",
        "candidates": [
            {
                "finishReason": "STOP",
                "content": {"parts": [{"text": text}, {"thought": True, "text": "hidden"}]},
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 4,
            "candidatesTokenCount": 8,
            "thoughtsTokenCount": thoughts,
            "totalTokenCount": 12 + thoughts,
        },
    }


def _anthropic(text: str) -> dict:
    return {
        "id": "msg_1",
        "model": "claude-haiku-5-5-20261001",
        "stop_reason": "end_turn",
        "content": [
            {"type": "thinking", "thinking": "hidden"},
            {"type": "text", "text": text},
        ],
        "usage": {
            "input_tokens": 15,
            "output_tokens": 9,
            "cache_read_input_tokens": 4,
        },
    }


def test_anthropic_cache_tokens_are_recorded_and_not_priced_as_normal_input():
    transport = FakeTransport([http_json(_anthropic(json.dumps(CONTROLLER)))])
    response = _client("anthropic", "claude-haiku-5-5", transport).propose(make_request())
    assert response.prompt_tokens == 15
    assert response.completion_tokens == 9
    assert response.usage["extra_usage"]["cache_read_input_tokens"] == 4
    assert response.estimated_cost_usd == pytest.approx((15 * 0.1 + 9 * 0.5) / 1_000_000)
    assert "cache_read_input_tokens" in response.usage["extra_usage"]["unpriced_details"]


def test_urllib_transport_reads_http_errors_without_a_socket(monkeypatch):
    from rewardbench.providers.http import HttpRequest, UrllibTransport

    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout):
        assert timeout == 3
        assert request.get_header("Authorization") == "Bearer local"
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    response = UrllibTransport().send(
        HttpRequest("POST", "https://example.invalid/v1", {"Authorization": "Bearer local"}, b"{}", 3)
    )
    assert response.status == 200
    assert response.body == b'{"ok": true}'
