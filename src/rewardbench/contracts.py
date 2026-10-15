"""Shared contracts for the reward-driven adaptation benchmark.

Controller revisions and simulated episodes are different records. Models adapt
inside the prompt from prior attempts and, when enabled, numerical rewards.
Nothing in this package fine-tunes neural network weights.

Environment-specific controllers stay inside ``parameters`` mappings validated
by an ``EnvironmentAdapter``. Core never executes model-authored code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping, Protocol, runtime_checkable

CONTRACT_VERSION = "1.0.0"
SCHEMA_VERSION = 1


class FeedbackCondition(str, Enum):
    """Whether prior numerical rewards are shown to the model."""

    NO_FEEDBACK = "no_feedback"
    NUMERICAL_REWARD = "numerical_reward"


class Split(str, Enum):
    """Which seed pool a run is allowed to execute."""

    DEVELOPMENT = "development"
    HELD_OUT = "held_out"


class ExperimentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    INTERRUPTED = "interrupted"


class FailurePolicy(str, Enum):
    """What the runner does after a recorded, expected failure."""

    ABORT = "abort"
    SKIP = "skip"


class ErrorPhase(str, Enum):
    MODEL = "model"
    VALIDATION = "validation"
    EPISODE = "episode"
    BUDGET = "budget"
    CHECKPOINT = "checkpoint"
    CONFIG = "config"


class RewardBenchError(Exception):
    """Base error for benchmark failures."""


class ConfigError(RewardBenchError):
    """The experiment configuration is missing or inconsistent."""


class SplitViolation(RewardBenchError):
    """A run tried to use a seed outside its development or held-out pool."""


class BudgetExceeded(RewardBenchError):
    """A budget limit was reached. The runner stops without further calls."""

    def __init__(self, message: str, *, resource: str, spent: float, limit: float) -> None:
        super().__init__(message)
        self.resource = resource
        self.spent = spent
        self.limit = limit


class ModelClientError(RewardBenchError):
    """A model provider failed before returning a usable proposal."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class EnvironmentAdapterError(RewardBenchError):
    """A simulation adapter could not validate or execute a controller."""


class ResumeError(RewardBenchError):
    """Stored state does not match the configuration being resumed."""


def _reject_bool_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    return value


def _freeze_mapping(name: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(value, MappingProxyType):
        return value
    if not isinstance(value, Mapping):
        raise ConfigError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _non_empty(name: str, value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True)
class BudgetLimits:
    """Caps for one experiment, or for an injected process-wide limiter.

    ``None`` means that resource is not capped. Every set limit must be > 0.
    Tokens and cost are cumulative. Wall time is cumulative across resumes.
    """

    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_wall_seconds: float | None = None
    max_revisions: int | None = None
    max_episodes: int | None = None
    max_model_calls: int | None = None

    def __post_init__(self) -> None:
        integer_limits = {
            "max_tokens": self.max_tokens,
            "max_revisions": self.max_revisions,
            "max_episodes": self.max_episodes,
            "max_model_calls": self.max_model_calls,
        }
        for name, value in integer_limits.items():
            if value is None:
                continue
            _reject_bool_int(name, value)
            if value <= 0:
                raise ConfigError(f"{name} must be positive when set")
        for name, value in (
            ("max_cost_usd", self.max_cost_usd),
            ("max_wall_seconds", self.max_wall_seconds),
        ):
            if value is None:
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ConfigError(f"{name} must be a real number")
            if value <= 0:
                raise ConfigError(f"{name} must be positive when set")


@dataclass(frozen=True)
class BudgetSnapshot:
    """Spend already committed for an experiment budget."""

    cost_usd: float
    tokens: int
    episodes: int
    revisions: int
    model_calls: int
    elapsed_seconds: float


@dataclass(frozen=True)
class ExperimentConfig:
    """Immutable configuration for one model, environment, and feedback condition.

    ``experiment_id`` is derived from this object. ``database_path`` and
    ``notes`` are excluded from that id so logs can move without changing it.
    ``development_seeds`` and ``held_out_seeds`` are both required and must be
    disjoint, including when only one split is executed.
    """

    experiment_name: str
    environment_id: str
    provider: str
    model_id: str
    feedback_condition: FeedbackCondition
    split: Split
    seed: int
    num_revisions: int
    episodes_per_revision: int
    history_window: int
    development_seeds: tuple[int, ...]
    held_out_seeds: tuple[int, ...]
    budget: BudgetLimits = field(default_factory=BudgetLimits)
    max_episode_steps: int | None = None
    max_model_retries: int = 2
    checkpoint_every: int = 1
    on_invalid_policy: FailurePolicy = FailurePolicy.SKIP
    on_model_failure: FailurePolicy = FailurePolicy.ABORT
    on_episode_failure: FailurePolicy = FailurePolicy.SKIP
    database_path: str = "runs/rewardbench.sqlite"
    model_settings: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "experiment_name", _non_empty("experiment_name", self.experiment_name))
        object.__setattr__(self, "environment_id", _non_empty("environment_id", self.environment_id))
        object.__setattr__(self, "provider", _non_empty("provider", self.provider))
        object.__setattr__(self, "model_id", _non_empty("model_id", self.model_id))
        if not isinstance(self.feedback_condition, FeedbackCondition):
            raise ConfigError("feedback_condition must be a FeedbackCondition")
        if not isinstance(self.split, Split):
            raise ConfigError("split must be a Split")
        object.__setattr__(self, "seed", _reject_bool_int("seed", self.seed))
        for name in ("num_revisions", "episodes_per_revision"):
            value = _reject_bool_int(name, getattr(self, name))
            if value < 1:
                raise ConfigError(f"{name} must be >= 1")
        history_window = _reject_bool_int("history_window", self.history_window)
        if history_window < 0:
            raise ConfigError("history_window must be >= 0")
        retries = _reject_bool_int("max_model_retries", self.max_model_retries)
        if retries < 0:
            raise ConfigError("max_model_retries must be >= 0")
        checkpoint_every = _reject_bool_int("checkpoint_every", self.checkpoint_every)
        if checkpoint_every < 1:
            raise ConfigError("checkpoint_every must be >= 1")
        if self.max_episode_steps is not None:
            steps = _reject_bool_int("max_episode_steps", self.max_episode_steps)
            if steps < 1:
                raise ConfigError("max_episode_steps must be >= 1 when set")
        if not isinstance(self.budget, BudgetLimits):
            raise ConfigError("budget must be a BudgetLimits")
        for name in ("on_invalid_policy", "on_model_failure", "on_episode_failure"):
            if not isinstance(getattr(self, name), FailurePolicy):
                raise ConfigError(f"{name} must be a FailurePolicy")
        if not isinstance(self.database_path, str) or not self.database_path.strip():
            raise ConfigError("database_path must be a non-empty string")
        if not isinstance(self.notes, str):
            raise ConfigError("notes must be a string")
        object.__setattr__(
            self,
            "development_seeds",
            _seed_pool("development_seeds", self.development_seeds),
        )
        object.__setattr__(
            self,
            "held_out_seeds",
            _seed_pool("held_out_seeds", self.held_out_seeds),
        )
        overlap = set(self.development_seeds) & set(self.held_out_seeds)
        if overlap:
            raise ConfigError(
                "development_seeds and held_out_seeds must be disjoint; "
                f"overlap={sorted(overlap)}"
            )
        object.__setattr__(
            self,
            "model_settings",
            _freeze_mapping("model_settings", self.model_settings),
        )
        object.__setattr__(self, "metadata", _freeze_mapping("metadata", self.metadata))


def _seed_pool(name: str, seeds: tuple[int, ...] | list[int]) -> tuple[int, ...]:
    if isinstance(seeds, (str, bytes)) or not isinstance(seeds, (tuple, list)):
        raise ConfigError(f"{name} must be a sequence of integers")
    if len(seeds) == 0:
        raise ConfigError(f"{name} must be non-empty")
    cleaned = tuple(_reject_bool_int(name, seed) for seed in seeds)
    if len(set(cleaned)) != len(cleaned):
        raise ConfigError(f"{name} must not contain duplicates")
    return cleaned


@dataclass(frozen=True)
class EnvironmentSpec:
    """Static description an adapter gives the runner and the model client."""

    environment_id: str
    display_name: str
    task_description: str
    controller_schema: Mapping[str, Any]
    action_space_summary: str
    observation_space_summary: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "environment_id", _non_empty("environment_id", self.environment_id))
        object.__setattr__(self, "display_name", _non_empty("display_name", self.display_name))
        object.__setattr__(
            self,
            "task_description",
            _non_empty("task_description", self.task_description),
        )
        object.__setattr__(
            self,
            "controller_schema",
            _freeze_mapping("controller_schema", self.controller_schema),
        )
        object.__setattr__(
            self,
            "action_space_summary",
            _non_empty("action_space_summary", self.action_space_summary),
        )
        object.__setattr__(
            self,
            "observation_space_summary",
            _non_empty("observation_space_summary", self.observation_space_summary),
        )


@dataclass(frozen=True)
class ValidationResult:
    """Result of checking a controller without executing it."""

    valid: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise ConfigError("valid must be a boolean")
        if self.valid and self.error is not None:
            raise ConfigError("a valid policy cannot include an error")
        if not self.valid and (not isinstance(self.error, str) or not self.error.strip()):
            raise ConfigError("an invalid policy requires a non-empty error")


@dataclass(frozen=True)
class CandidatePolicy:
    """One controller revision. This is not a simulated episode."""

    revision_index: int
    parameters: Mapping[str, Any]
    raw_response: str
    valid: bool
    validation_error: str | None = None
    model_id: str = ""
    provider: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            _freeze_mapping("parameters", self.parameters),
        )
        if not isinstance(self.raw_response, str):
            raise ConfigError("raw_response must be a string")
        if not isinstance(self.valid, bool):
            raise ConfigError("valid must be a boolean")


@dataclass(frozen=True)
class EpisodeResult:
    """Outcome of one simulated episode under a controller revision.

    ``total_reward`` is the environment's own primary score. Negative values
    are penalties. ``metrics`` holds environment-specific numbers such as fuel
    use. Seeds stay in storage and are not copied into model-facing feedback.
    """

    revision_index: int
    episode_index: int
    seed: int
    total_reward: float
    success: bool
    crashed: bool | None
    steps: int
    terminated: bool
    truncated: bool
    elapsed_seconds: float
    metrics: Mapping[str, float] = field(default_factory=dict)
    error: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _freeze_mapping("metrics", self.metrics))


@dataclass(frozen=True)
class RewardFeedback:
    """Numerical outcome shown to a model. Seeds are intentionally omitted."""

    revision_index: int
    episode_index: int
    total_reward: float
    success: bool
    crashed: bool | None
    steps: int
    metrics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _freeze_mapping("metrics", self.metrics))

    @classmethod
    def from_episode(cls, result: EpisodeResult) -> RewardFeedback:
        return cls(
            revision_index=result.revision_index,
            episode_index=result.episode_index,
            total_reward=result.total_reward,
            success=result.success,
            crashed=result.crashed,
            steps=result.steps,
            metrics=dict(result.metrics),
        )


@dataclass(frozen=True)
class PriorAttempt:
    """One earlier controller revision as presented to the model.

    ``feedback is None`` means rewards were withheld. An empty tuple means the
    numerical-reward condition is on, but this revision produced no scores.
    """

    revision_index: int
    parameters: Mapping[str, Any]
    valid: bool
    validation_error: str | None
    feedback: tuple[RewardFeedback, ...] | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "parameters",
            _freeze_mapping("parameters", self.parameters),
        )
        if self.feedback is not None:
            object.__setattr__(self, "feedback", tuple(self.feedback))


@dataclass(frozen=True)
class ModelRequest:
    """Structured request. Prompt wording belongs to ``rewardbench.prompts``."""

    contract_version: str
    experiment_id: str
    session_id: str
    revision_index: int
    feedback_condition: FeedbackCondition
    split: Split
    environment: EnvironmentSpec
    history: tuple[PriorAttempt, ...]
    model_settings: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "history", tuple(self.history))
        object.__setattr__(
            self,
            "model_settings",
            _freeze_mapping("model_settings", self.model_settings),
        )


@dataclass(frozen=True)
class ModelResponse:
    """A parsed controller proposal. The client does not run the environment.

    ``total_tokens`` is what the experiment budget charges. Set it explicitly.
    ``reasoning_tokens`` is disclosed separately and is not added again when
    ``total_tokens`` is already set. If ``total_tokens`` is 0, the budget uses
    ``prompt_tokens + completion_tokens``.
    """

    raw_text: str
    parameters: Mapping[str, Any] | None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    model_id: str = ""
    provider: str = ""
    parse_error: str | None = None
    usage: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.parameters is not None:
            object.__setattr__(
                self,
                "parameters",
                _freeze_mapping("parameters", self.parameters),
            )
        object.__setattr__(self, "usage", _freeze_mapping("usage", self.usage))
        for name in (
            "prompt_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "total_tokens",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ConfigError(f"{name} must be a non-negative integer")
        if not isinstance(self.raw_text, str):
            raise ConfigError("raw_text must be a string")

    @property
    def charged_tokens(self) -> int:
        if self.total_tokens:
            return self.total_tokens
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class ExperimentRecord:
    experiment_id: str
    experiment_name: str
    environment_id: str
    provider: str
    model_id: str
    feedback_condition: FeedbackCondition
    split: Split
    seed: int
    contract_version: str
    config_json: str
    config_hash: str
    status: ExperimentStatus
    created_at: str
    updated_at: str
    completed_revisions: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    experiment_id: str
    status: ExperimentStatus
    started_at: str
    ended_at: str | None
    python_version: str
    platform: str
    error: str | None = None


@dataclass(frozen=True)
class StoredAttempt:
    """One model call. Several calls may belong to one controller revision."""

    experiment_id: str
    session_id: str
    revision_index: int
    call_index: int
    selected: bool
    parameters: Mapping[str, Any]
    raw_response: str
    valid: bool
    validation_error: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_seconds: float
    estimated_cost_usd: float
    model_id: str
    provider: str
    error: str | None
    created_at: str
    attempt_id: int | None = None

    def as_policy(self) -> CandidatePolicy:
        return CandidatePolicy(
            revision_index=self.revision_index,
            parameters=dict(self.parameters),
            raw_response=self.raw_response,
            valid=self.valid,
            validation_error=self.validation_error,
            model_id=self.model_id,
            provider=self.provider,
        )


@dataclass(frozen=True)
class StoredEpisode:
    experiment_id: str
    session_id: str
    revision_index: int
    episode_index: int
    seed: int
    total_reward: float | None
    success: bool | None
    crashed: bool | None
    steps: int
    terminated: bool
    truncated: bool
    elapsed_seconds: float
    metrics: Mapping[str, float]
    error: str | None
    created_at: str
    episode_id: int | None = None

    def as_result(self) -> EpisodeResult:
        if self.total_reward is None or self.success is None:
            raise ResumeError("cannot rebuild an episode result without a score")
        return EpisodeResult(
            revision_index=self.revision_index,
            episode_index=self.episode_index,
            seed=self.seed,
            total_reward=self.total_reward,
            success=self.success,
            crashed=self.crashed,
            steps=self.steps,
            terminated=self.terminated,
            truncated=self.truncated,
            elapsed_seconds=self.elapsed_seconds,
            metrics=dict(self.metrics),
            error=self.error,
        )


@dataclass(frozen=True)
class StoredError:
    experiment_id: str
    session_id: str
    phase: str
    message: str
    revision_index: int | None = None
    episode_index: int | None = None
    traceback: str | None = None
    created_at: str = ""
    error_id: int | None = None


@dataclass(frozen=True)
class Checkpoint:
    experiment_id: str
    next_revision_index: int
    budget: BudgetSnapshot
    seed_schedule: tuple[tuple[int, ...], ...]
    updated_at: str


@dataclass(frozen=True)
class ExperimentSummary:
    experiment_id: str
    session_id: str
    status: ExperimentStatus
    revisions_completed: int
    episodes_recorded: int
    invalid_revisions: int
    model_calls: int
    total_tokens: int
    total_cost_usd: float
    mean_reward: float | None
    best_reward: float | None
    error: str | None = None


class ExperimentAborted(RewardBenchError):
    """A failure policy stopped the run after the error was stored."""

    def __init__(self, message: str, summary: ExperimentSummary) -> None:
        super().__init__(message)
        self.summary = summary


@runtime_checkable
class ModelClient(Protocol):
    """Provider-neutral client. Implementations must not run the environment."""

    @property
    def provider(self) -> str: ...

    @property
    def model_id(self) -> str: ...

    def propose(self, request: ModelRequest) -> ModelResponse:
        """Return a structured controller proposal.

        Raise ``ModelClientError`` for transport, timeout, or API failures.
        Put unparsable but successful responses in ``ModelResponse.parse_error``
        instead of raising.
        """


@runtime_checkable
class EnvironmentAdapter(Protocol):
    """One simulation environment. A future Minecraft adapter uses this too."""

    def describe(self) -> EnvironmentSpec:
        """Return the id, task text, and controller schema."""

    def validate_policy(self, parameters: Mapping[str, Any]) -> ValidationResult:
        """Accept or reject a controller. Must not exec or eval model text."""

    def run_episode(
        self,
        policy: CandidatePolicy,
        *,
        seed: int,
        episode_index: int,
        revision_index: int,
        max_steps: int | None = None,
    ) -> EpisodeResult:
        """Simulate one episode. Must not call a language model."""


@runtime_checkable
class ExperimentStore(Protocol):
    """Persistence for experiments, sessions, attempts, episodes, and errors."""

    def initialize(self) -> None: ...

    def create_experiment(self, record: ExperimentRecord) -> None: ...

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None: ...

    def update_experiment(
        self,
        experiment_id: str,
        *,
        status: ExperimentStatus,
        error: str | None = None,
        completed_revisions: int | None = None,
    ) -> None: ...

    def start_session(self, record: SessionRecord) -> None: ...

    def end_session(
        self,
        session_id: str,
        *,
        status: ExperimentStatus,
        error: str | None = None,
    ) -> None: ...

    def insert_attempt(self, record: StoredAttempt) -> int: ...

    def insert_episode(self, record: StoredEpisode) -> int: ...

    def insert_error(self, record: StoredError) -> int: ...

    def save_checkpoint(self, checkpoint: Checkpoint) -> None: ...

    def load_checkpoint(self, experiment_id: str) -> Checkpoint | None: ...

    def fetch_attempts(self, experiment_id: str) -> list[StoredAttempt]: ...

    def fetch_episodes(self, experiment_id: str) -> list[StoredEpisode]: ...

    def fetch_errors(self, experiment_id: str) -> list[StoredError]: ...

    def fetch_sessions(self, experiment_id: str) -> list[SessionRecord]: ...
