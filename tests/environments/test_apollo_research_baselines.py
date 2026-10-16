"""Regression checks for research-mode baseline validity helpers."""

from __future__ import annotations

import pytest

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import (
    ORIGIN_DETERMINISTIC_MOCK,
    ORIGIN_HAND_SPECIFIED,
    constant_controller,
    demonstration_guidance_controller,
    random_controller,
)
from rewardbench.environments.lunarlander.seeds import HELD_OUT_SEED_START


def test_random_controller_is_deterministic_per_episode_seed() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=25)
    controller = random_controller(0)
    first = adapter.evaluate(
        controller,
        [3],
        revision=1,
        split="development",
        origin=ORIGIN_DETERMINISTIC_MOCK,
        model="random-a",
        max_steps=25,
    )
    second = adapter.evaluate(
        controller,
        [3],
        revision=1,
        split="development",
        origin=ORIGIN_DETERMINISTIC_MOCK,
        model="random-b",
        max_steps=25,
    )
    other = adapter.evaluate(
        controller,
        [4],
        revision=1,
        split="development",
        origin=ORIGIN_DETERMINISTIC_MOCK,
        model="random-c",
        max_steps=25,
    )
    assert first["episodes"][0]["trace"] == second["episodes"][0]["trace"]
    assert first["episodes"][0]["reward"] == second["episodes"][0]["reward"]
    assert first["episodes"][0]["trace"] != other["episodes"][0]["trace"]
    assert first["autonomous_learning"] is False


def test_development_baseline_seeds_reject_held_out() -> None:
    adapter = make_environment("ApolloLander", research_mode=True)
    with pytest.raises(ValueError, match="held-out"):
        adapter.evaluate(
            constant_controller(0, -90),
            [HELD_OUT_SEED_START],
            revision=1,
            split="development",
            origin=ORIGIN_DETERMINISTIC_MOCK,
        )


def test_fixed_guidance_still_lands_while_research_may_differ() -> None:
    """Guard against silently breaking the known fixed-start demonstration."""
    fixed = make_environment("ApolloLander", research_mode=False)
    landing = fixed.evaluate(
        demonstration_guidance_controller(),
        [0],
        revision=1,
        split="development",
        origin=ORIGIN_HAND_SPECIFIED,
        model="hand-specified-guidance",
    )
    assert landing["episodes"][0]["landed"] is True
    assert landing["autonomous_learning"] is False
    assert landing["origin"] == ORIGIN_HAND_SPECIFIED
