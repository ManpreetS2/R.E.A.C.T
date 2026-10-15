"""Numerical reward and penalty feedback for one controller revision.

The numbers come from scored flights. This module does not propose a new
controller and does not describe a change as model learning.
"""

from __future__ import annotations

from typing import Any

from rewardbench.environments.lunarlander.types import FlightEvaluation


def numerical_feedback(evaluation: FlightEvaluation) -> dict[str, Any]:
    """Return the reward vector and failure counts a later proposer can read."""
    episodes = evaluation.executed_episodes
    rewards = [float(episode.reward) for episode in episodes if episode.reward is not None]
    return {
        "revision": evaluation.revision,
        "environment_id": evaluation.environment_id,
        "primary_metric": "gymnasium_return",
        "seeds": [episode.seed for episode in episodes],
        "reward": {
            "values": rewards,
            "mean": evaluation.mean_reward,
            "sample_std": evaluation.reward_std,
        },
        "penalties": {
            "fuel_penalty_values": [episode.fuel_penalty for episode in episodes],
            "fuel_penalty_mean": evaluation.mean_fuel_penalty,
            "physical_crash_count": evaluation.category_counts.get("physical_crash", 0),
            "viewport_exit_count": evaluation.category_counts.get("viewport_exit", 0),
            "timeout_count": evaluation.category_counts.get("timeout", 0),
            "landed_outside_zone_count": evaluation.category_counts.get("landed_outside_zone", 0),
        },
        "landing_rate": evaluation.landing_rate,
        "landing_count": evaluation.landing_count,
        "category_counts": evaluation.category_counts,
        "episodes": [
            {
                "seed": episode.seed,
                "reward": episode.reward,
                "outcome": episode.outcome,
                "fuel_penalty": episode.fuel_penalty,
                "in_landing_zone": episode.in_landing_zone,
                "steps": episode.steps,
                "duration_seconds": episode.duration_seconds,
            }
            for episode in episodes
        ],
    }
