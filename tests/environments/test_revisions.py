"""Revision scoring and numerical feedback. These tests do not claim model learning."""

from __future__ import annotations

import pytest

from rewardbench.environments.lunarlander.revisions import evaluate_revision
from rewardbench.environments.lunarlander.schema import (
    imperfect_heuristic_controller,
    reference_controller,
    thrust_biased_controller,
)
from rewardbench.environments.lunarlander.seeds import development_seeds
from rewardbench.environments.lunarlander.types import FlightEpisode, FlightEvaluation, sample_standard_deviation


def _episode(seed: int, reward: float, outcome: str) -> FlightEpisode:
    return FlightEpisode(
        environment_id="LunarLander-v3",
        seed=seed,
        revision=1,
        controller_valid=True,
        invalid_reason=None,
        executed=True,
        policy="heuristic",
        reward=reward,
        steps=10,
        duration_seconds=0.2,
        terminated=True,
        truncated=False,
        landed=outcome == "landed",
        crashed=outcome == "physical_crash",
        outcome=outcome,
        crash_cause="hull_contact" if outcome == "physical_crash" else None,
        hull_contact=outcome == "physical_crash",
        out_of_bounds=outcome == "viewport_exit",
        lander_awake=False,
        main_engine_steps=0,
        side_engine_steps=0,
        idle_steps=10,
        fuel_penalty=0.0,
        action_checksum=None,
        last_step_reward=reward,
        viewport_exit=outcome == "viewport_exit",
        timed_out=outcome == "timeout",
        in_landing_zone=True if outcome == "landed" else False,
        lander_x=10.0,
        helipad_x1=8.0,
        helipad_x2=12.0,
    )


def test_sample_standard_deviation_uses_one_degree_of_freedom() -> None:
    assert sample_standard_deviation([1.0, 2.0, 3.0]) == pytest.approx(1.0)
    assert sample_standard_deviation([5.0]) is None


def test_feedback_separates_failure_categories() -> None:
    evaluation = FlightEvaluation(
        environment_id="LunarLander-v3",
        revision=2,
        controller_valid=True,
        invalid_reason=None,
        policy="heuristic",
        split="development",
        episodes=(
            _episode(1, 200.0, "landed"),
            _episode(2, -100.0, "physical_crash"),
            _episode(3, -80.0, "viewport_exit"),
            _episode(4, -20.0, "timeout"),
            _episode(5, 40.0, "landed_outside_zone"),
        ),
    )
    assert evaluation.landing_rate == pytest.approx(0.2)
    assert evaluation.reward_std == pytest.approx(sample_standard_deviation([200, -100, -80, -20, 40]))
    assert evaluation.category_counts["landed"] == 1
    assert evaluation.category_counts["physical_crash"] == 1
    assert evaluation.category_counts["viewport_exit"] == 1
    assert evaluation.category_counts["timeout"] == 1
    assert evaluation.category_counts["landed_outside_zone"] == 1


def test_revision_numbers_start_at_one() -> None:
    from rewardbench.environments.lunarlander.adapter import LunarLanderAdapter

    adapter = LunarLanderAdapter()
    with pytest.raises(ValueError, match="revision"):
        evaluate_revision(
            adapter,
            reference_controller(),
            development_seeds(1),
            revision=0,
            origin="benchmark",
        )


def test_revision_evaluates_the_submitted_controller() -> None:
    pytest.importorskip("gymnasium")
    pytest.importorskip("Box2D")
    from rewardbench.environments.lunarlander.adapter import LunarLanderAdapter

    adapter = LunarLanderAdapter()
    seeds = development_seeds(1, start=8)
    weak = evaluate_revision(
        adapter,
        imperfect_heuristic_controller(),
        seeds,
        revision=1,
        origin="hand_specified_demonstration",
    )
    revised = evaluate_revision(
        adapter,
        thrust_biased_controller(),
        seeds,
        revision=2,
        origin="hand_specified_demonstration",
    )
    benchmark = evaluate_revision(
        adapter,
        reference_controller(),
        seeds,
        revision=1,
        origin="benchmark",
    )
    assert weak.controller["parameters"] != benchmark.controller["parameters"]
    assert weak.evaluation.episodes[0].action_checksum != revised.evaluation.episodes[0].action_checksum
    assert weak.feedback["landing_count"] == 0
    assert weak.evaluation.episodes[0].outcome == "physical_crash"
    assert revised.to_dict()["autonomous_learning"] is False
    assert revised.evaluation.episodes[0].main_engine_steps == revised.evaluation.episodes[0].steps
