"""Canonical analysis records read from experiment logs.

Column names follow the SQLite contract in ``docs/INTERFACES.md``. This module
does not redefine runner types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

PRELIMINARY = "preliminary"
INDEPENDENTLY_VALIDATED = "independently_validated"
VALIDATION_STATUSES = frozenset({PRELIMINARY, INDEPENDENTLY_VALIDATED})

SYNTHETIC_BANNER = "SYNTHETIC FIXTURE — NOT EXPERIMENTAL RESULTS"
EMPTY_LOG_MESSAGE = "No experiment logs loaded"

FEEDBACK_CONDITIONS = frozenset({"no_feedback", "numerical_reward", "reward_only"})
SPLITS = frozenset({"development", "held_out"})


class AnalysisError(Exception):
    """The analysis could not be completed."""


class SchemaError(AnalysisError):
    """The log is not a RewardBench experiment database or export."""


class LogRejected(AnalysisError):
    """The log is internally inconsistent and was not summarized."""


@dataclass(frozen=True)
class Interval:
    """A point estimate and an optional confidence interval."""

    point: float | None
    low: float | None
    high: float | None
    n: int
    note: str | None = None

    @property
    def defined(self) -> bool:
        return self.low is not None and self.high is not None


@dataclass(frozen=True)
class EpisodeObservation:
    experiment_id: str
    session_id: str
    environment_id: str
    provider: str
    model_id: str
    feedback_condition: str
    split: str
    experiment_seed: int
    experiment_status: str
    revision_index: int
    episode_index: int
    episode_seed: int
    total_reward: float | None
    success: bool | None
    crashed: bool | None
    steps: int
    elapsed_seconds: float
    error: str | None
    validation_status: str
    synthetic: bool
    development_seeds: tuple[int, ...] = ()
    held_out_seeds: tuple[int, ...] = ()
    environment_config: str = "{}"


@dataclass(frozen=True)
class AttemptObservation:
    experiment_id: str
    session_id: str
    environment_id: str
    provider: str
    model_id: str
    feedback_condition: str
    split: str
    experiment_status: str
    revision_index: int
    call_index: int
    selected: bool
    valid: bool
    validation_error: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_seconds: float
    estimated_cost_usd: float
    error: str | None
    validation_status: str
    synthetic: bool
    environment_config: str = "{}"
    usage: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ErrorObservation:
    experiment_id: str
    session_id: str
    phase: str
    message: str
    revision_index: int | None
    episode_index: int | None


@dataclass(frozen=True)
class ValidationIssue:
    level: str
    code: str
    message: str
    experiment_id: str | None = None
    session_id: str | None = None


@dataclass
class LogBundle:
    """Episodes and attempts from one log file."""

    episodes: list[EpisodeObservation]
    attempts: list[AttemptObservation]
    errors: list[ErrorObservation]
    issues: list[ValidationIssue]
    source: Path
    sha256: str
    schema_version: int | None
    source_format: str
    load_warnings: list[str] = field(default_factory=list)

    @property
    def synthetic(self) -> bool:
        flags = [row.synthetic for row in self.episodes]
        flags.extend(row.synthetic for row in self.attempts)
        return any(flags)

    @property
    def empty(self) -> bool:
        return not self.episodes and not self.attempts
