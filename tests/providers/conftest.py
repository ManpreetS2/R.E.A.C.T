"""Shared request builder for provider tests. No network."""

from __future__ import annotations

import json

from rewardbench.contracts import (
    EnvironmentSpec,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)

CONTROLLER = {
    "schema": "rewardbench.lunarlander.controller.v1",
    "policy": "heuristic",
    "parameters": {"angle_target_limit": 0.4},
}


def make_request(
    condition: FeedbackCondition = FeedbackCondition.NUMERICAL_REWARD,
    history: tuple[PriorAttempt, ...] = (),
    settings: dict | None = None,
    revision_index: int = 1,
) -> ModelRequest:
    return ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp_test",
        session_id="ses_test",
        revision_index=revision_index,
        feedback_condition=condition,
        split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="lunarlander-v3",
            display_name="LunarLander",
            task_description="Land the vehicle between the flags.",
            controller_schema={"schema": "rewardbench.lunarlander.controller.v1"},
            action_space_summary="0 idle, 1 left engine, 2 main engine, 3 right engine",
            observation_space_summary="x, y, vx, vy, angle, angular velocity, two leg contacts",
        ),
        history=history,
        model_settings=settings or {},
    )


def prior(condition: FeedbackCondition) -> PriorAttempt:
    feedback = None
    if condition is FeedbackCondition.NUMERICAL_REWARD:
        feedback = (
            RewardFeedback(
                revision_index=0,
                episode_index=1,
                total_reward=-87.5,
                success=False,
                crashed=True,
                steps=90,
                metrics={"fuel_used": 12.0},
            ),
            RewardFeedback(
                revision_index=0,
                episode_index=0,
                total_reward=10.0,
                success=True,
                crashed=False,
                steps=40,
                metrics={"fuel_used": 3.0},
            ),
        )
    return PriorAttempt(
        revision_index=0,
        parameters=CONTROLLER,
        valid=False,
        validation_error="missing heuristic parameter",
        feedback=feedback,
    )


def http_json(payload: dict, status: int = 200, headers: dict | None = None, latency: float = 0.2):
    from rewardbench.providers.http import HttpResponse

    return HttpResponse(
        status=status,
        headers=headers or {},
        body=json.dumps(payload).encode("utf-8"),
        latency_seconds=latency,
    )


class FakeTransport:
    def __init__(self, responses: list) -> None:
        self.responses = list(responses)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
