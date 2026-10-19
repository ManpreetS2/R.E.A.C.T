"""Baselines for gate checks. Reference guidance is feasibility-only — never used in PPO."""

from __future__ import annotations

from typing import Any

import numpy as np

from rewardbench.environments.apollolander.schema import (
    DEMONSTRATION_GUIDANCE,
    guidance_action,
)

from .apollo_env import STEER_DELTAS, THRUST_LEVELS


def noop_action(_obs: np.ndarray | None = None, **_kwargs) -> np.ndarray:
    """Zero thrust, hold commanded angle."""
    return np.array([0, 1], dtype=np.int64)


def random_action(rng: np.random.Generator) -> np.ndarray:
    return np.array(
        [int(rng.integers(0, len(THRUST_LEVELS))), int(rng.integers(0, len(STEER_DELTAS)))],
        dtype=np.int64,
    )


def _nearest_thrust_index(thrust: float) -> int:
    return int(np.argmin(np.abs(THRUST_LEVELS - float(thrust))))


def reference_continuous_command(
    raw_obs: dict[str, Any],
    *,
    parameters: dict[str, float] | None = None,
) -> dict[str, float]:
    """Absolute thrust/rotation from demonstration guidance — feasibility only."""
    params = parameters or DEMONSTRATION_GUIDANCE
    continuous = guidance_action(
        {
            "dx": float(raw_obs["dx"]),
            "vx": float(raw_obs["vx"]),
            "vy": float(raw_obs["vy"]),
            "altitude": float(raw_obs["altitude"]),
            "rotation": float(raw_obs["rotation"]),
            "fuel": float(raw_obs.get("fuel", 1000.0)),
            "step": float(raw_obs.get("step", 0)),
        },
        params,
    )
    return {
        "thrust": float(continuous["thrust"]),
        "rotation": float(continuous["rotation"]),
    }


def reference_guidance_action(
    raw_obs: dict[str, Any],
    cmd_angle: float,
    *,
    parameters: dict[str, float] | None = None,
) -> np.ndarray:
    """Approximate guidance as MultiDiscrete (learner-compatible; weaker than continuous)."""
    continuous = reference_continuous_command(raw_obs, parameters=parameters)
    desired = float(continuous["rotation"])
    delta = desired - float(cmd_angle)
    if delta <= -5.0:
        steer_i = 0  # −10°
    elif delta >= 5.0:
        steer_i = 2  # +10°
    else:
        steer_i = 1  # hold
    thrust_i = _nearest_thrust_index(float(continuous["thrust"]))
    return np.array([thrust_i, steer_i], dtype=np.int64)
