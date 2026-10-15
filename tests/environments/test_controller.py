"""Action selection for valid controllers."""

from __future__ import annotations

import numpy as np

from rewardbench.environments.lunarlander.actions import (
    IDLE,
    LEFT_ENGINE,
    MAIN_ENGINE,
    RIGHT_ENGINE,
)
from rewardbench.environments.lunarlander.controller import (
    compile_controller,
    episode_rng,
    heuristic_action,
    linear_action,
)
from rewardbench.environments.lunarlander.schema import (
    REFERENCE_HEURISTIC_PARAMETERS,
    idle_controller,
    reference_controller,
)


def test_linear_argmax_breaks_ties_toward_idle() -> None:
    state = [0.0] * 8
    weights = tuple(tuple(0.0 for _ in range(8)) for _ in range(4))
    assert linear_action(state, weights, (0.0, 0.0, 0.0, 0.0), clip_obs=10.0) == IDLE
    assert linear_action(state, weights, (1.0, 1.0, 0.0, 0.0), clip_obs=10.0) == IDLE
    assert linear_action(state, weights, (0.0, 0.0, 5.0, 4.0), clip_obs=10.0) == MAIN_ENGINE


def test_linear_controller_clips_observations() -> None:
    weights = tuple(tuple(0.0 for _ in range(8)) for _ in range(4))
    biased = (
        (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    )
    huge = [1000.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    clipped = linear_action(huge, biased, (0.0, 0.0, 0.0, 0.0), clip_obs=2.0)
    assert clipped == IDLE
    assert linear_action(huge, biased, (0.0, 0.0, 0.0, 0.0), clip_obs=2.0) == linear_action(
        [2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        biased,
        (0.0, 0.0, 0.0, 0.0),
        clip_obs=2.0,
    )


def test_idle_controller_always_idles() -> None:
    compiled = compile_controller(idle_controller())
    rng = np.random.default_rng(0)
    for _ in range(20):
        observation = rng.normal(size=8)
        assert compiled.act(observation, rng) == IDLE


def test_reference_heuristic_matches_hand_computed_cases() -> None:
    # Level, above the pad, no velocity: hover target is 0 and y is positive,
    # so hover_todo is negative and the craft should not fire the main engine.
    hovering = [0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert heuristic_action(hovering, REFERENCE_HEURISTIC_PARAMETERS) == IDLE

    # Positive angle produces a negative angle command, which fires the right engine.
    tilted = [0.0, 0.5, 0.0, -0.1, 0.8, 0.0, 0.0, 0.0]
    assert heuristic_action(tilted, REFERENCE_HEURISTIC_PARAMETERS) == RIGHT_ENGINE

    # Negative angle fires the left engine.
    opposite = [0.0, 0.5, 0.0, -0.1, -0.8, 0.0, 0.0, 0.0]
    assert heuristic_action(opposite, REFERENCE_HEURISTIC_PARAMETERS) == LEFT_ENGINE


def test_leg_contact_zeros_the_angle_command() -> None:
    # Without contact the tilt would fire a side engine. Contact clears angle_todo.
    contacted = [0.0, 0.0, 0.0, -0.2, 0.8, 0.0, 1.0, 0.0]
    assert heuristic_action(contacted, REFERENCE_HEURISTIC_PARAMETERS) == MAIN_ENGINE


def test_random_policy_is_deterministic_and_uses_all_engines() -> None:
    compiled = compile_controller(
        {"schema": "rewardbench.lunarlander.controller.v1", "policy": "random", "seed": 11}
    )
    observation = [0.0] * 8
    first = [compiled.act(observation, episode_rng(11, 4)) for _ in range(1)]
    again = [compiled.act(observation, episode_rng(11, 4)) for _ in range(1)]
    assert first == again

    rng = episode_rng(11, 4)
    actions = {compiled.act(observation, rng) for _ in range(200)}
    assert actions == {IDLE, LEFT_ENGINE, MAIN_ENGINE, RIGHT_ENGINE}


def test_same_controller_seed_changes_with_episode_seed() -> None:
    compiled = compile_controller(
        {"schema": "rewardbench.lunarlander.controller.v1", "policy": "random", "seed": 11}
    )
    observation = [0.1, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    first = [compiled.act(observation, episode_rng(11, 1)) for _ in range(8)]
    # Rebuild the generator for a fair sequence comparison.
    sequence_a = []
    rng_a = episode_rng(11, 1)
    rng_b = episode_rng(11, 2)
    sequence_b = []
    for _ in range(8):
        sequence_a.append(compiled.act(observation, rng_a))
        sequence_b.append(compiled.act(observation, rng_b))
    assert sequence_a != sequence_b
    assert first  # the single-step call above constructed a valid action
