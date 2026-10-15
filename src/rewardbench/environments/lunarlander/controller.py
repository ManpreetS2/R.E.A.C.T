"""Turn a validated controller into one discrete engine command per step.

The functions here are fixed research code. They read numbers from a
normalized controller and return idle, left engine, main engine, or right
engine. They do not interpret strings as programs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from rewardbench.environments.lunarlander.actions import (
    IDLE,
    LEFT_ENGINE,
    MAIN_ENGINE,
    N_OBSERVATIONS,
    RIGHT_ENGINE,
)
from rewardbench.environments.lunarlander.schema import (
    NormalizedController,
    normalize_controller,
)

_HEURISTIC_ORDER = (
    "angle_target_x_gain",
    "angle_target_vx_gain",
    "angle_target_limit",
    "hover_x_gain",
    "angle_error_gain",
    "angular_velocity_gain",
    "hover_error_gain",
    "vertical_velocity_gain",
    "main_engine_threshold",
    "side_engine_threshold",
    "contact_vertical_velocity_gain",
)


@dataclass(frozen=True)
class CompiledController:
    """Callable numeric policy produced only after schema validation."""

    policy: str
    normalized: NormalizedController

    def act(self, observation: Sequence[float], rng: np.random.Generator) -> int:
        state = observation_vector(observation)
        if self.policy == "heuristic":
            return heuristic_action(state, self.normalized.parameter_map())
        if self.policy == "linear":
            assert self.normalized.weights is not None
            assert self.normalized.bias is not None
            assert self.normalized.clip_obs is not None
            return linear_action(
                state,
                self.normalized.weights,
                self.normalized.bias,
                self.normalized.clip_obs,
            )
        if self.policy == "random":
            return random_action(rng)
        raise RuntimeError(f"compiled controller has unknown policy {self.policy!r}")


def compile_controller(payload: Mapping[str, Any] | str) -> CompiledController:
    normalized = normalize_controller(payload)
    return CompiledController(policy=normalized.policy, normalized=normalized)


def observation_vector(observation: Sequence[float]) -> list[float]:
    values = [float(value) for value in observation]
    if len(values) != N_OBSERVATIONS:
        raise RuntimeError(
            f"LunarLander observation must have {N_OBSERVATIONS} values, got {len(values)}"
        )
    if not all(math.isfinite(value) for value in values):
        raise RuntimeError("LunarLander observation contains a non-finite value")
    return values


def heuristic_action(state: Sequence[float], parameters: Mapping[str, float]) -> int:
    """Parameterized form of Gymnasium's discrete lunar-lander heuristic.

    With ``REFERENCE_HEURISTIC_PARAMETERS`` this matches the control law in
    ``gymnasium.envs.box2d.lunar_lander.heuristic`` for the discrete environment.
    """
    gains = [parameters[name] for name in _HEURISTIC_ORDER]
    (
        angle_target_x_gain,
        angle_target_vx_gain,
        angle_target_limit,
        hover_x_gain,
        angle_error_gain,
        angular_velocity_gain,
        hover_error_gain,
        vertical_velocity_gain,
        main_engine_threshold,
        side_engine_threshold,
        contact_vertical_velocity_gain,
    ) = gains

    angle_target = state[0] * angle_target_x_gain + state[2] * angle_target_vx_gain
    if angle_target > angle_target_limit:
        angle_target = angle_target_limit
    if angle_target < -angle_target_limit:
        angle_target = -angle_target_limit

    hover_target = hover_x_gain * abs(state[0])
    angle_todo = (angle_target - state[4]) * angle_error_gain - state[5] * angular_velocity_gain
    hover_todo = (hover_target - state[1]) * hover_error_gain - state[3] * vertical_velocity_gain

    if state[6] or state[7]:
        angle_todo = 0.0
        hover_todo = -(state[3]) * contact_vertical_velocity_gain

    if hover_todo > abs(angle_todo) and hover_todo > main_engine_threshold:
        return MAIN_ENGINE
    if angle_todo < -side_engine_threshold:
        return RIGHT_ENGINE
    if angle_todo > side_engine_threshold:
        return LEFT_ENGINE
    return IDLE


def linear_action(
    state: Sequence[float],
    weights: Sequence[Sequence[float]],
    bias: Sequence[float],
    clip_obs: float,
) -> int:
    """Argmax linear policy. Equal logits keep the lowest action index."""
    clipped: list[float] = []
    for value in state:
        if value > clip_obs:
            clipped.append(clip_obs)
        elif value < -clip_obs:
            clipped.append(-clip_obs)
        else:
            clipped.append(value)

    best_action = IDLE
    best_logit: float | None = None
    for action, row in enumerate(weights):
        logit = float(bias[action])
        for weight, value in zip(row, clipped, strict=True):
            logit += float(weight) * value
        if best_logit is None or logit > best_logit:
            best_logit = logit
            best_action = action
    return best_action


def random_action(rng: np.random.Generator) -> int:
    return int(rng.integers(0, 4))


def episode_rng(controller_seed: int, episode_seed: int) -> np.random.Generator:
    """Mix the policy seed with the episode seed. The stream is deterministic."""
    sequence = np.random.SeedSequence([controller_seed, episode_seed])
    return np.random.default_rng(sequence)
