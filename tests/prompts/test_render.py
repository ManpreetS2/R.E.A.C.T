"""No-feedback and numerical prompts share the task and differ in rewards."""

from __future__ import annotations

from rewardbench.contracts import (
    EnvironmentSpec,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)
from rewardbench.prompts import SYSTEM_PROMPT, render_messages

CONTROLLER = {"schema": "rewardbench.lunarlander.controller.v1", "policy": "heuristic"}


def _request(condition: FeedbackCondition) -> ModelRequest:
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
        )
    history = (
        PriorAttempt(
            revision_index=0,
            parameters=CONTROLLER,
            valid=False,
            validation_error="missing heuristic parameter",
            feedback=feedback,
        ),
    )
    return ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp_test",
        session_id="ses_test",
        revision_index=2,
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
        model_settings={},
    )


def test_both_modes_share_rules_schema_and_validation_errors():
    no_system, no_user = render_messages(_request(FeedbackCondition.NO_FEEDBACK))
    num_system, num_user = render_messages(_request(FeedbackCondition.NUMERICAL_REWARD))
    assert no_system == num_system == SYSTEM_PROMPT
    assert "Do not update, train, or fine-tune neural network weights." in no_system
    for user in (no_user, num_user):
        assert "Land the vehicle between the flags." in user
        assert "rewardbench.lunarlander.controller.v1" in user
        assert "0 idle, 1 left engine, 2 main engine, 3 right engine" in user
        assert "missing heuristic parameter" in user
        assert "Reply with one compact JSON object" in user
    assert "reward=-87.5" in num_user
    assert "fuel_used" in num_user
    assert "reward=" not in no_user
    assert "-87.5" not in no_user
    assert "fuel_used" not in no_user
    assert "Scores were withheld on purpose." in no_user


def test_no_feedback_hides_rewards_even_if_a_caller_attached_them():
    request = _request(FeedbackCondition.NUMERICAL_REWARD)
    hidden = ModelRequest(
        contract_version=request.contract_version,
        experiment_id=request.experiment_id,
        session_id=request.session_id,
        revision_index=request.revision_index,
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        split=request.split,
        environment=request.environment,
        history=request.history,
        model_settings={},
    )
    _system, user = render_messages(hidden)
    assert "-87.5" not in user
    assert "success=" not in user


def test_first_revision_has_no_fake_history():
    request = _request(FeedbackCondition.NUMERICAL_REWARD)
    empty = ModelRequest(
        contract_version=request.contract_version,
        experiment_id=request.experiment_id,
        session_id=request.session_id,
        revision_index=0,
        feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
        split=request.split,
        environment=request.environment,
        history=(),
        model_settings={},
    )
    _system, user = render_messages(empty)
    assert "No earlier controller is available." in user
    assert "reward=" not in user
