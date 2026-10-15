"""Local episode records and the adapter surface a future environment must match.

``docs/INTERFACES.md`` is owned by the core framework and was not present when
this environment was written. These types stay inside the LunarLander package
so they do not redefine that shared contract. A Minecraft adapter can implement
the same three operations: validate a candidate, evaluate it on explicit seeds,
and close its resources.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from rewardbench.environments.lunarlander.outcomes import OUTCOME_LABELS
from rewardbench.environments.lunarlander.schema import ControllerStatus


@dataclass(frozen=True)
class FlightEpisode:
    """One simulated flight, or one seed skipped because the controller was invalid."""

    environment_id: str
    seed: int
    revision: int | None
    controller_valid: bool
    invalid_reason: str | None
    executed: bool
    policy: str | None
    reward: float | None
    steps: int
    duration_seconds: float
    terminated: bool
    truncated: bool
    landed: bool
    crashed: bool
    outcome: str
    crash_cause: str | None
    hull_contact: bool
    out_of_bounds: bool
    lander_awake: bool | None
    main_engine_steps: int
    side_engine_steps: int
    idle_steps: int
    fuel_penalty: float
    action_checksum: str | None
    last_step_reward: float | None
    viewport_exit: bool
    timed_out: bool
    in_landing_zone: bool | None
    lander_x: float | None
    helipad_x1: float | None
    helipad_x2: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "seed": self.seed,
            "revision": self.revision,
            "controller_valid": self.controller_valid,
            "invalid_reason": self.invalid_reason,
            "executed": self.executed,
            "policy": self.policy,
            "reward": self.reward,
            "steps": self.steps,
            "duration_seconds": self.duration_seconds,
            "terminated": self.terminated,
            "truncated": self.truncated,
            "landed": self.landed,
            "crashed": self.crashed,
            "outcome": self.outcome,
            "crash_cause": self.crash_cause,
            "hull_contact": self.hull_contact,
            "out_of_bounds": self.out_of_bounds,
            "lander_awake": self.lander_awake,
            "main_engine_steps": self.main_engine_steps,
            "side_engine_steps": self.side_engine_steps,
            "idle_steps": self.idle_steps,
            "fuel_penalty": self.fuel_penalty,
            "action_checksum": self.action_checksum,
            "last_step_reward": self.last_step_reward,
            "viewport_exit": self.viewport_exit,
            "timed_out": self.timed_out,
            "in_landing_zone": self.in_landing_zone,
            "lander_x": self.lander_x,
            "helipad_x1": self.helipad_x1,
            "helipad_x2": self.helipad_x2,
        }


@dataclass(frozen=True)
class FlightEvaluation:
    """All flights for one controller revision."""

    environment_id: str
    revision: int | None
    controller_valid: bool
    invalid_reason: str | None
    policy: str | None
    split: str
    episodes: tuple[FlightEpisode, ...]
    replay_paths: tuple[str, ...] = ()
    video_paths: tuple[str, ...] = ()
    video_errors: tuple[str, ...] = ()
    gymnasium_version: str | None = None
    box2d_version: str | None = None

    @property
    def executed_episodes(self) -> tuple[FlightEpisode, ...]:
        return tuple(episode for episode in self.episodes if episode.executed)

    @property
    def mean_reward(self) -> float | None:
        episodes = self.executed_episodes
        if not episodes:
            return None
        return sum(episode.reward or 0.0 for episode in episodes) / len(episodes)

    @property
    def landing_count(self) -> int:
        return sum(1 for episode in self.executed_episodes if episode.landed)

    @property
    def crash_count(self) -> int:
        return sum(1 for episode in self.executed_episodes if episode.crashed)

    @property
    def landing_rate(self) -> float | None:
        episodes = self.executed_episodes
        if not episodes:
            return None
        return self.landing_count / len(episodes)

    @property
    def crash_rate(self) -> float | None:
        episodes = self.executed_episodes
        if not episodes:
            return None
        return self.crash_count / len(episodes)

    @property
    def reward_std(self) -> float | None:
        """Sample standard deviation of Gymnasium returns (ddof=1)."""
        rewards = [episode.reward for episode in self.executed_episodes if episode.reward is not None]
        return sample_standard_deviation(rewards)

    @property
    def category_counts(self) -> dict[str, int]:
        counts = {label: 0 for label in OUTCOME_LABELS if label != "invalid"}
        for episode in self.executed_episodes:
            counts[episode.outcome] = counts.get(episode.outcome, 0) + 1
        return counts

    @property
    def mean_fuel_penalty(self) -> float | None:
        episodes = self.executed_episodes
        if not episodes:
            return None
        return sum(episode.fuel_penalty for episode in episodes) / len(episodes)

    @property
    def mean_duration_seconds(self) -> float | None:
        episodes = self.executed_episodes
        if not episodes:
            return None
        return sum(episode.duration_seconds for episode in episodes) / len(episodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "environment_id": self.environment_id,
            "revision": self.revision,
            "controller_valid": self.controller_valid,
            "invalid_reason": self.invalid_reason,
            "policy": self.policy,
            "split": self.split,
            "episode_count": len(self.episodes),
            "executed_count": len(self.executed_episodes),
            "mean_reward": self.mean_reward,
            "landing_count": self.landing_count,
            "crash_count": self.crash_count,
            "landing_rate": self.landing_rate,
            "reward_std": self.reward_std,
            "crash_rate": self.crash_rate,
            "category_counts": self.category_counts,
            "mean_fuel_penalty": self.mean_fuel_penalty,
            "mean_duration_seconds": self.mean_duration_seconds,
            "replay_paths": list(self.replay_paths),
            "video_paths": list(self.video_paths),
            "video_errors": list(self.video_errors),
            "gymnasium_version": self.gymnasium_version,
            "box2d_version": self.box2d_version,
            "episodes": [episode.to_dict() for episode in self.episodes],
        }


def sample_standard_deviation(values: Sequence[float]) -> float | None:
    """Sample standard deviation. Returns None when fewer than two values exist."""
    count = len(values)
    if count < 2:
        return None
    mean = sum(values) / count
    variance = sum((value - mean) ** 2 for value in values) / (count - 1)
    return math.sqrt(variance)


class EnvironmentAdapter(Protocol):
    """Minimal environment surface shared with a future Minecraft adapter.

    The core package may replace this protocol with the types in
    ``docs/INTERFACES.md``. LunarLanderAdapter already exposes these methods
    so that swap can be a thin wrapper.
    """

    environment_id: str

    def validate_controller(self, controller: Mapping[str, Any] | str) -> ControllerStatus:
        """Accept a candidate or explain why it was rejected. Do not simulate."""

    def evaluate(
        self,
        controller: Mapping[str, Any] | str,
        seeds: Sequence[int],
        *,
        revision: int | None = None,
        split: str = "unrestricted",
        record_dir: str | Path | None = None,
        record_video: bool = False,
        video_seeds: Sequence[int] | None = None,
        max_steps: int | None = None,
    ) -> FlightEvaluation:
        """Run every seed as its own flight. Invalid controllers are not stepped."""

    def close(self) -> None:
        """Release environment resources. Safe to call more than once."""
