"""reward_only isolates the scalar reward: prompts differ only in the planned intervention."""

from __future__ import annotations

import re

from rewardbench.contracts import (
    EnvironmentSpec,
    FeedbackCondition,
    ModelRequest,
    PriorAttempt,
    RewardFeedback,
    Split,
)
from rewardbench.prompts import render_messages

CONTROLLER = {"schema": "rewardbench.apollolander.controller.v1", "policy": "constant"}
_REWARD_LINE = re.compile(r"^  episode \d+ reward=\S+$")


def _request(condition: FeedbackCondition) -> ModelRequest:
    history = tuple(
        PriorAttempt(
            revision_index=index,
            parameters=CONTROLLER,
            valid=True,
            validation_error=None,
            # The stored episodes are identical in every condition; only the renderer differs.
            feedback=(
                RewardFeedback(
                    revision_index=index,
                    episode_index=0,
                    total_reward=-40.25 + index,
                    success=False,
                    crashed=True,
                    steps=77 + index,
                    metrics={"fuel_used": 12.5, "vertical_speed": 31.0},
                ),
            ),
        )
        for index in range(2)
    )
    return ModelRequest(
        contract_version="1.0.0",
        experiment_id="exp_test",
        session_id="ses_test",
        revision_index=2,
        feedback_condition=condition,
        split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="apollolander",
            display_name="ApolloLander",
            task_description="Land on the pad.",
            controller_schema={"schema": "rewardbench.apollolander.controller.v1"},
            action_space_summary="thrust, rotation",
            observation_space_summary="position, velocity, fuel",
        ),
        history=history,
        model_settings={},
    )


def _split(condition: FeedbackCondition) -> tuple[str, list[str], list[str]]:
    """Return (system, user lines that are not the feedback header, per-episode detail lines)."""

    system, user = render_messages(_request(condition))
    header_free: list[str] = []
    details: list[str] = []
    for line in user.splitlines():
        if line.startswith("  episode "):
            details.append(line)
        elif line.startswith("Earlier revisions"):
            continue  # the one-sentence condition disclosure
        else:
            header_free.append(line)
    return system, header_free, details


def test_reward_only_differs_from_no_feedback_only_by_rewards_and_condition_header():
    no_system, no_rest, no_details = _split(FeedbackCondition.NO_FEEDBACK)
    ro_system, ro_rest, ro_details = _split(FeedbackCondition.REWARD_ONLY)
    assert no_system == ro_system
    assert no_rest == ro_rest
    assert no_details == []
    assert [line for line in ro_details if not _REWARD_LINE.match(line)] == []
    assert len(ro_details) == 2


def test_reward_only_hides_every_non_reward_outcome_field():
    _system, user = render_messages(_request(FeedbackCondition.REWARD_ONLY))
    for hidden in ("success=", "steps=", "crashed=", "metrics=", "fuel_used", "vertical_speed", "77"):
        assert hidden not in user
    assert "reward=-40.25" in user


def test_reward_only_equals_numerical_after_removing_extra_outcome_fields():
    num_system, num_rest, num_details = _split(FeedbackCondition.NUMERICAL_REWARD)
    ro_system, ro_rest, ro_details = _split(FeedbackCondition.REWARD_ONLY)
    assert num_system == ro_system
    assert num_rest == ro_rest
    stripped = [re.sub(r" success=.*$", "", line) for line in num_details]
    assert stripped == ro_details
    assert all("success=" in line and "metrics=" in line for line in num_details)


def test_condition_headers_are_the_only_other_difference():
    users = {c: render_messages(_request(c))[1] for c in FeedbackCondition}
    headers = {
        c: [line for line in user.splitlines() if line.startswith("Earlier revisions")]
        for c, user in users.items()
    }
    assert all(len(value) == 1 for value in headers.values())
    assert len({value[0] for value in headers.values()}) == 3
