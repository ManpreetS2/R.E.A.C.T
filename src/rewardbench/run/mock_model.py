"""Deterministic offline model for infrastructure experiments.

``ScriptedFeedbackModel`` revises its controller only when the request carries
numerical reward feedback. Under ``no_feedback`` it keeps the initial
controller and never reads episode scores. This proves the runner, history
isolation, and SQLite path. It is not an LLM and does not demonstrate learning.
"""

from __future__ import annotations

import json
from typing import Any

from rewardbench.contracts import ConfigError, FeedbackCondition, ModelRequest, ModelResponse

# Labeled intentionally so logs cannot be mistaken for a paid model.
SCRIPTED_PROVIDER = "mock"
SCRIPTED_MODEL_ID = "scripted-feedback-responsive"


def apollo_initial_controller() -> dict[str, object]:
    from rewardbench.environments.apollolander.schema import constant_controller

    return constant_controller(0.0, -90)


def apollo_revised_controller() -> dict[str, object]:
    from rewardbench.environments.apollolander.schema import constant_controller

    return constant_controller(1.0, 0)


# Stable aliases for Apollo offline configs and tests.
INITIAL_CONTROLLER = apollo_initial_controller()
REVISED_CONTROLLER = apollo_revised_controller()


class ScriptedFeedbackModel:
    """Offline ``ModelClient`` that reacts only to numerical reward history."""

    def __init__(
        self,
        *,
        provider: str = SCRIPTED_PROVIDER,
        model_id: str = SCRIPTED_MODEL_ID,
    ) -> None:
        self._provider = provider
        self._model_id = model_id
        self.requests: list[ModelRequest] = []
        self.proposals: list[dict[str, Any]] = []

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model_id(self) -> str:
        return self._model_id

    def propose(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        parameters = self._select(request)
        self.proposals.append(dict(parameters))
        raw = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        return ModelResponse(
            raw_text=raw,
            parameters=dict(parameters),
            prompt_tokens=32,
            completion_tokens=24,
            reasoning_tokens=0,
            total_tokens=56,
            latency_seconds=0.0,
            estimated_cost_usd=0.0,
            model_id=self._model_id,
            provider=self._provider,
            usage={
                "offline": True,
                "scripted": True,
                "infrastructure_test": True,
                "not_llm_learning": True,
            },
        )

    def _select(self, request: ModelRequest) -> dict[str, Any]:
        initial, revised = _controllers_for(request.environment.environment_id)
        if not request.history:
            return dict(initial)
        prior = request.history[-1]
        if request.feedback_condition is FeedbackCondition.NO_FEEDBACK:
            if prior.feedback is not None:
                raise RuntimeError("no-feedback history leaked reward feedback into the model request")
            return dict(initial)
        if prior.feedback is None or not prior.feedback:
            return dict(initial)
        # Numerical condition: change the controller after seeing objective scores.
        _ = [item.total_reward for item in prior.feedback]
        return dict(revised)


def _controllers_for(environment_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized = environment_id.strip().lower().replace("_", "-")
    if normalized in {"apollolander", "apollo-lander", "apollo"}:
        return apollo_initial_controller(), apollo_revised_controller()
    if normalized in {"lunarlander-v3", "lunarlander", "lunar-lander", "lunar-lander-v3"}:
        from rewardbench.environments.lunarlander.schema import (
            idle_controller,
            thrust_biased_controller,
        )

        return idle_controller(), thrust_biased_controller()
    raise ConfigError(
        f"scripted mock model has no offline controllers for environment {environment_id!r}"
    )
