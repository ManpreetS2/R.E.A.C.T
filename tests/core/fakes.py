"""Offline stand-ins for the model client and environment adapter."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from rewardbench.contracts import (
    BudgetLimits,
    CandidatePolicy,
    EnvironmentSpec,
    EpisodeResult,
    ExperimentConfig,
    FailurePolicy,
    FeedbackCondition,
    ModelResponse,
    Split,
    ValidationResult,
)


def make_config(**overrides: Any) -> ExperimentConfig:
    values: dict[str, Any] = {
        "experiment_name": "unit",
        "environment_id": "lunarlander-v3",
        "provider": "fake",
        "model_id": "fake-1",
        "feedback_condition": FeedbackCondition.NUMERICAL_REWARD,
        "split": Split.DEVELOPMENT,
        "seed": 7,
        "num_revisions": 2,
        "episodes_per_revision": 2,
        "history_window": 2,
        "development_seeds": (1, 2, 3, 4),
        "held_out_seeds": (101, 102, 103, 104),
        "budget": BudgetLimits(),
        "max_model_retries": 0,
        "on_invalid_policy": FailurePolicy.SKIP,
        "on_model_failure": FailurePolicy.ABORT,
        "on_episode_failure": FailurePolicy.SKIP,
        "database_path": "runs/test.sqlite",
    }
    values.update(overrides)
    return ExperimentConfig(**values)


def proposal(parameters: Mapping[str, Any] | None, **overrides: Any) -> ModelResponse:
    values: dict[str, Any] = {
        "raw_text": "{}" if parameters is None else str(dict(parameters)),
        "parameters": None if parameters is None else dict(parameters),
        "prompt_tokens": 8,
        "completion_tokens": 4,
        "reasoning_tokens": 0,
        "total_tokens": 12,
        "latency_seconds": 0.2,
        "estimated_cost_usd": 0.01,
        "model_id": "fake-1",
        "provider": "fake",
    }
    values.update(overrides)
    return ModelResponse(**values)


class FakeModel:
    provider = "fake"
    model_id = "fake-1"

    def __init__(self, scripts: list[Any]) -> None:
        self.scripts = list(scripts)
        self.requests: list[Any] = []

    def propose(self, request: Any) -> ModelResponse:
        self.requests.append(request)
        if not self.scripts:
            raise AssertionError("FakeModel ran out of scripted responses")
        item = self.scripts.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(request)
        return item


class FakeEnv:
    def __init__(
        self,
        *,
        environment_id: str = "lunarlander-v3",
        fail_seeds: set[int] | None = None,
        on_episode: Callable[[], None] | None = None,
    ) -> None:
        self.environment_id = environment_id
        self.fail_seeds = fail_seeds or set()
        self.on_episode = on_episode
        self.episodes: list[tuple[int, int, int]] = []

    def describe(self) -> EnvironmentSpec:
        return EnvironmentSpec(
            environment_id=self.environment_id,
            display_name="Fake lander",
            task_description="Land the vehicle.",
            controller_schema={"type": "object", "required": ["gain"]},
            action_space_summary="idle, left, main, right",
            observation_space_summary="position and velocity",
        )

    def validate_policy(self, parameters: Mapping[str, Any]) -> ValidationResult:
        gain = parameters.get("gain")
        if isinstance(gain, bool) or not isinstance(gain, (int, float)):
            return ValidationResult(False, "missing gain")
        return ValidationResult(True, None)

    def run_episode(
        self,
        policy: CandidatePolicy,
        *,
        seed: int,
        episode_index: int,
        revision_index: int,
        max_steps: int | None = None,
    ) -> EpisodeResult:
        if self.on_episode is not None:
            self.on_episode()
        self.episodes.append((revision_index, episode_index, seed))
        if seed in self.fail_seeds:
            raise RuntimeError(f"simulated failure for seed {seed}")
        gain = float(policy.parameters["gain"])
        return EpisodeResult(
            revision_index=revision_index,
            episode_index=episode_index,
            seed=seed,
            total_reward=gain - (0.01 * seed),
            success=gain > 0,
            crashed=gain <= 0,
            steps=7,
            terminated=True,
            truncated=False,
            elapsed_seconds=0.05,
            metrics={"fuel_used": 2.5},
        )
