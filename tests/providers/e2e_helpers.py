"""Helpers for provider→runner→ApolloLander→SQLite end-to-end tests.

These helpers never open a real provider socket. Physics uses the local Node
Apollo session when an episode runs.
"""

from __future__ import annotations

import json
import random
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from rewardbench.contracts import (
    BudgetLimits,
    ExperimentConfig,
    FailurePolicy,
    FeedbackCondition,
    ModelClient,
    ModelRequest,
    ModelResponse,
    Split,
)
from rewardbench.environments.apollolander import ApolloLanderAdapter, constant_controller
from rewardbench.environments.apollolander.schema import demonstration_guidance_controller
from rewardbench.providers import build_model_client
from rewardbench.prompts import render_messages
from rewardbench.storage import SqliteStore

from tests.providers.conftest import FakeTransport, http_json
from tests.providers.test_adapters import _anthropic, _chat, _gemini

SECRET = "sk-test-e2e-not-a-real-key"

APOLLO_SCHEMA = json.loads(
    (Path(__file__).resolve().parent / "fixtures" / "apollolander_controller_schema.json").read_text(
        encoding="utf-8"
    )
)


class RecordingModelClient:
    """Wrap a real ModelClient and keep every ModelRequest."""

    def __init__(self, inner: ModelClient) -> None:
        self.inner = inner
        self.requests: list[ModelRequest] = []
        self.responses: list[ModelResponse] = []

    @property
    def provider(self) -> str:
        return getattr(self.inner, "provider", "")

    @property
    def model_id(self) -> str:
        return getattr(self.inner, "model_id", "")

    def propose(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        response = self.inner.propose(request)
        self.responses.append(response)
        return response


def apollo_config(
    tmp_path: Path,
    *,
    name: str,
    feedback: FeedbackCondition = FeedbackCondition.NUMERICAL_REWARD,
    provider: str = "openai",
    model_id: str = "gpt-5.4-mini",
    num_revisions: int = 2,
    episodes_per_revision: int = 1,
    max_model_retries: int = 1,
    max_episode_steps: int = 40,
    max_cost_usd: float | None = 1.0,
    model_settings: Mapping[str, Any] | None = None,
) -> ExperimentConfig:
    settings = {
        "max_output_tokens": 400,
        "temperature": 0,
    }
    if model_settings:
        settings.update(dict(model_settings))
    return ExperimentConfig(
        experiment_name=name,
        environment_id="apollolander",
        provider=provider,
        model_id=model_id,
        feedback_condition=feedback,
        split=Split.DEVELOPMENT,
        seed=11,
        num_revisions=num_revisions,
        episodes_per_revision=episodes_per_revision,
        history_window=4,
        max_episode_steps=max_episode_steps,
        max_model_retries=max_model_retries,
        checkpoint_every=1,
        on_invalid_policy=FailurePolicy.SKIP,
        on_model_failure=FailurePolicy.ABORT,
        on_episode_failure=FailurePolicy.SKIP,
        database_path=str(tmp_path / "rewardbench.sqlite"),
        development_seeds=(0, 1, 2, 3, 4, 5, 6, 7),
        held_out_seeds=(1_000_000, 1_000_001, 1_000_002, 1_000_003),
        budget=BudgetLimits(
            max_cost_usd=max_cost_usd,
            max_tokens=50_000,
            max_wall_seconds=120.0,
            max_revisions=num_revisions,
            max_episodes=num_revisions * episodes_per_revision,
            max_model_calls=20,
        ),
        model_settings=settings,
        notes="provider e2e mock pilot; not a live call",
    )


def live_client(
    provider: str,
    model_id: str,
    transport: FakeTransport,
    *,
    max_retries: int = 1,
    max_spend_usd: float | None = 5.0,
    **kwargs: Any,
) -> RecordingModelClient:
    inner = build_model_client(
        provider,
        model_id,
        transport=transport,
        api_key=SECRET,
        max_retries=max_retries,
        timeout_s=5,
        rng=random.Random(0),
        max_spend_usd=max_spend_usd,
        sleeper=lambda _seconds: None,
        **kwargs,
    )
    return RecordingModelClient(inner)


def openai_reply(
    controller: Mapping[str, Any],
    *,
    prompt: int = 120,
    completion: int = 80,
    reasoning: int = 12,
) -> dict[str, Any]:
    return _chat(
        json.dumps(controller, sort_keys=True),
        prompt=prompt,
        completion=completion,
        reasoning=reasoning,
        model="gpt-5.4-mini-2026-03-17",
    )


def gemini_reply(controller: Mapping[str, Any], *, thoughts: int = 20) -> dict[str, Any]:
    return _gemini(json.dumps(controller, sort_keys=True), thoughts=thoughts)


def anthropic_reply(controller: Mapping[str, Any], *, cache_read: int = 0) -> dict[str, Any]:
    return _anthropic(json.dumps(controller, sort_keys=True), cache_read=cache_read)


def grok_reply(
    controller: Mapping[str, Any],
    *,
    prompt: int = 100,
    completion: int = 60,
    reasoning: int = 8,
) -> dict[str, Any]:
    return _chat(
        json.dumps(controller, sort_keys=True),
        prompt=prompt,
        completion=completion,
        reasoning=reasoning,
        model="grok-4.3",
    )


def scripted_transport(provider: str, controllers: Sequence[Mapping[str, Any]]) -> FakeTransport:
    replies: list[Any] = []
    for controller in controllers:
        if provider == "google":
            replies.append(http_json(gemini_reply(controller)))
        elif provider == "anthropic":
            replies.append(http_json(anthropic_reply(controller)))
        elif provider == "xai":
            replies.append(http_json(grok_reply(controller)))
        else:
            replies.append(http_json(openai_reply(controller)))
    return FakeTransport(replies)


def apollo_environment(*, max_steps: int = 40) -> ApolloLanderAdapter:
    return ApolloLanderAdapter(max_steps=max_steps)


def store_for(tmp_path: Path) -> SqliteStore:
    return SqliteStore(tmp_path / "rewardbench.sqlite")


def weak_controller() -> dict[str, Any]:
    return constant_controller(0, -90)


def stronger_controller() -> dict[str, Any]:
    return constant_controller(0.4, -20)


def guidance_controller() -> dict[str, Any]:
    return demonstration_guidance_controller()


def user_text_from_request(request: ModelRequest) -> str:
    _system, user = render_messages(request)
    return user


def assert_no_numeric_reward_leak(text: str) -> None:
    lowered = text.lower()
    assert "reward=" not in lowered
    assert "total_reward" not in lowered
