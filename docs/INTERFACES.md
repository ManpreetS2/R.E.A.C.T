# RewardBench interfaces

Contract version: `1.0.0` (`rewardbench.CONTRACT_VERSION`)

SQLite schema version: `1` (`rewardbench.SCHEMA_VERSION`)

This document is the stable contract for every other package. Import the
objects below from `rewardbench` or `rewardbench.contracts`. Do not copy the
definitions into another package.

This benchmark measures in-context adaptation. Models see earlier controller
revisions and, under one condition, numerical rewards. No component fine-tunes
neural network weights. A controller revision is not a simulated episode.
Those are stored and executed separately.

The primary score is the environment's own reward. Penalties are negative
rewards. An adapter must reject invalid controllers without executing
model-authored Python. The same protocols must fit LunarLander-v3 now and a
later Minecraft adapter.

Prompt text belongs to `rewardbench.prompts`. Provider HTTP clients belong to
`rewardbench.providers`. Physics belongs to `rewardbench.environments`.

## Enums

```python
class FeedbackCondition(str, Enum):
    NO_FEEDBACK = "no_feedback"
    NUMERICAL_REWARD = "numerical_reward"

class Split(str, Enum):
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
    ABORT = "abort"
    SKIP = "skip"

class ErrorPhase(str, Enum):
    MODEL = "model"
    VALIDATION = "validation"
    EPISODE = "episode"
    BUDGET = "budget"
    CHECKPOINT = "checkpoint"
    CONFIG = "config"
```

## Errors

```python
class RewardBenchError(Exception): ...
class ConfigError(RewardBenchError): ...
class SplitViolation(RewardBenchError): ...
class BudgetExceeded(RewardBenchError):
    resource: str
    spent: float
    limit: float
    def __init__(self, message: str, *, resource: str, spent: float, limit: float) -> None: ...
class ModelClientError(RewardBenchError):
    retryable: bool
    def __init__(self, message: str, *, retryable: bool = True) -> None: ...
class EnvironmentAdapterError(RewardBenchError): ...
class ResumeError(RewardBenchError): ...
class ExperimentAborted(RewardBenchError):
    summary: ExperimentSummary
    def __init__(self, message: str, summary: ExperimentSummary) -> None: ...
```

Providers raise `ModelClientError` for transport, timeout, and API failures.
A response that arrives but does not parse is a `ModelResponse` with
`parse_error` set, not an exception. Adapters raise `EnvironmentAdapterError`
when a simulation cannot run. They return `ValidationResult(valid=False, ...)`
for a controller that is merely the wrong shape.

## Configuration

```python
@dataclass(frozen=True)
class BudgetLimits:
    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_wall_seconds: float | None = None
    max_revisions: int | None = None
    max_episodes: int | None = None
    max_model_calls: int | None = None

@dataclass(frozen=True)
class ExperimentConfig:
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
```

Rules enforced by `ExperimentConfig`:

- `development_seeds` and `held_out_seeds` are both non-empty, contain no
  duplicates, and do not overlap.
- `history_window >= 0`. Zero means the model sees no prior revisions.
- `num_revisions >= 1` and `episodes_per_revision >= 1`.
- `max_model_retries` is the number of extra model calls after the first.
- Set budget fields must be `> 0`. `None` means that resource is uncapped.
- `model_settings` is passed through to the provider. Core does not interpret
  temperature, reasoning effort, or other provider-specific knobs.
- `metadata` and `model_settings` must be JSON-serializable. They are part of
  the experiment id.

```python
def load_config(path: str | Path) -> ExperimentConfig: ...
def config_from_mapping(data: Mapping[str, Any]) -> ExperimentConfig: ...
```

`load_config` accepts `.yaml`, `.yml`, and `.json`. Unknown fields raise
`ConfigError`. Enum values are the strings shown above.

## Identifiers and seeds

```python
def canonical_config(config: ExperimentConfig) -> dict[str, Any]: ...
def config_hash(config: ExperimentConfig) -> str: ...
def experiment_id(config: ExperimentConfig) -> str: ...
def new_session_id() -> str: ...

def build_seed_schedule(
    master_seed: int,
    allowed_seeds: Sequence[int],
    num_revisions: int,
    episodes_per_revision: int,
) -> tuple[tuple[int, ...], ...]: ...

class SplitGuard:
    def __init__(
        self,
        split: Split,
        development_seeds: Sequence[int],
        held_out_seeds: Sequence[int],
    ) -> None: ...
    def allowed_seeds(self) -> tuple[int, ...]: ...
    def check(self, seed: int) -> None: ...
```

`experiment_id` is `exp_` plus the first 20 hex characters of
`config_hash`. The hash is SHA-256 of the canonical JSON (`sort_keys=True`,
compact separators). `database_path` and `notes` are not hashed. The same
config always yields the same id. Changing the feedback condition, split,
model id, seeds, or budget changes the id.

`new_session_id` is `ses_` plus a UUID. A resumed experiment keeps its
experiment id and opens a new session.

`build_seed_schedule` orders `allowed_seeds` by SHA-256 of
`"{master_seed}:{seed}"` and cycles that permutation. It does not use
`random.Random`. A development run receives only `development_seeds`.
`SplitGuard.check` raises `SplitViolation` for any other seed, including a
held-out seed during development.

Episode seeds are stored in SQLite and are not placed in `RewardFeedback`.

## Environment and model objects

```python
@dataclass(frozen=True)
class EnvironmentSpec:
    environment_id: str
    display_name: str
    task_description: str
    controller_schema: Mapping[str, Any]
    action_space_summary: str
    observation_space_summary: str

@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    error: str | None = None

@dataclass(frozen=True)
class CandidatePolicy:
    revision_index: int
    parameters: Mapping[str, Any]
    raw_response: str
    valid: bool
    validation_error: str | None = None
    model_id: str = ""
    provider: str = ""

@dataclass(frozen=True)
class EpisodeResult:
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

@dataclass(frozen=True)
class RewardFeedback:
    revision_index: int
    episode_index: int
    total_reward: float
    success: bool
    crashed: bool | None
    steps: int
    metrics: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def from_episode(cls, result: EpisodeResult) -> RewardFeedback: ...

@dataclass(frozen=True)
class PriorAttempt:
    revision_index: int
    parameters: Mapping[str, Any]
    valid: bool
    validation_error: str | None
    feedback: tuple[RewardFeedback, ...] | None

@dataclass(frozen=True)
class ModelRequest:
    contract_version: str
    experiment_id: str
    session_id: str
    revision_index: int
    feedback_condition: FeedbackCondition
    split: Split
    environment: EnvironmentSpec
    history: tuple[PriorAttempt, ...]
    model_settings: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ModelResponse:
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

    @property
    def charged_tokens(self) -> int: ...
```

`PriorAttempt.feedback is None` means the no-feedback condition withheld
scores. `feedback == ()` means numerical rewards were requested but that
revision has no episode scores. Validation errors are included in both
conditions because they describe the controller format, not the reward.

`ModelResponse.charged_tokens` returns `total_tokens` when it is non-zero,
otherwise `prompt_tokens + completion_tokens`. Do not also add
`reasoning_tokens` into `total_tokens` if those tokens are already included
in the provider's completion count. Record them in `reasoning_tokens` either
way. `estimated_cost_usd` is calculated by the provider from its own pricing
table. Core stores and sums that number.

`EpisodeResult.metrics` values are floats. LunarLander should include at
least `fuel_used` when the simulator reports it. `success` means the
environment verified the success condition. `crashed` may be `None` for
environments without that distinction.

## Protocols

```python
@runtime_checkable
class ModelClient(Protocol):
    @property
    def provider(self) -> str: ...
    @property
    def model_id(self) -> str: ...
    def propose(self, request: ModelRequest) -> ModelResponse: ...

@runtime_checkable
class EnvironmentAdapter(Protocol):
    def describe(self) -> EnvironmentSpec: ...
    def validate_policy(self, parameters: Mapping[str, Any]) -> ValidationResult: ...
    def run_episode(
        self,
        policy: CandidatePolicy,
        *,
        seed: int,
        episode_index: int,
        revision_index: int,
        max_steps: int | None = None,
    ) -> EpisodeResult: ...

@runtime_checkable
class ExperimentStore(Protocol):
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
```

`ModelClient.propose` must not simulate the environment and must not invent
the reward. `EnvironmentAdapter.run_episode` must not call a language model.
`validate_policy` must not execute arbitrary code.

The runner calls `describe()` and requires
`EnvironmentSpec.environment_id == ExperimentConfig.environment_id`.

## Stored records

```python
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
    def as_policy(self) -> CandidatePolicy: ...

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
    def as_result(self) -> EpisodeResult: ...

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
class BudgetSnapshot:
    cost_usd: float
    tokens: int
    episodes: int
    revisions: int
    model_calls: int
    elapsed_seconds: float

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
```

Timestamps are UTC ISO-8601 strings with a timezone offset.

`StoredAttempt.selected` marks the call that stands for that revision.
Retries that were replaced stay in the table with `selected=False`.
Episodes are inserted only for a selected valid controller.

## Command-line experiment entry

Core owns a narrow launcher that does not rewrite ``ExperimentRunner``:

```bash
python -m rewardbench.run --config <config.yaml> --mode mock
python -m rewardbench.run --config <config.yaml> --mode mock --database runs/custom.sqlite
```

``--mode mock`` (default) binds a scripted feedback-responsive offline model,
constructs the environment from ``environment_id``, applies validated
``metadata.adapter_kwargs`` to the adapter constructor, opens
``SqliteStore(config.database_path)``, and calls ``ExperimentRunner.run``.
It prints the experiment id, revision and episode counts, status, output
paths, and a ``run_state`` of ``completed``, ``paused``, ``failed``,
``budget-exhausted``, or ``interrupted``. Exit status ``0`` means
``completed`` or an intentional live-session ``paused`` stop; ``1`` means a
recorded failure or hard budget stop; ``2`` means configuration or usage
errors.

Mock mode is an infrastructure test. It is not evidence of LLM learning and
spends no API money.

### Live mode (authorized paid calls)

Live mode is off by default. It never runs unless the operator passes
``--i-authorize-paid-api-calls``. Core builds the client only through
``rewardbench.providers.build_model_client`` (no duplicated provider logic).

Before the first paid ``propose``, Core fail-closed preflight checks:

- provider is one of ``openai``, ``google``, ``anthropic``, ``xai``
- model id is present in the pricing catalog
- worst-case ``quote_call`` is available and ``<= budget.max_cost_usd``
- API credentials resolve (environment variable or test-injected key)
- ``max_model_retries == 0``
- ``budget.max_cost_usd`` and ``budget.max_model_calls`` are set
- ``model_settings.max_output_tokens`` is set
- environment ``controller_schema`` is present

Each live CLI process allows **at most one** new paid model request
(``--max-new-paid-calls`` defaults to 1 and must stay 1 for the pilot). When
``num_revisions`` is greater than the completed count, the session gate stops
further ``propose`` calls with ``BudgetExceeded(resource=live_session_model_calls)``.
The runner records that stop as ``interrupted`` (resumable), not terminal
``budget_exhausted``. The CLI reports ``run_state: paused`` and must not be
described as a completed learning experiment.

A second revision is a separately approved continuation:

```bash
python -m rewardbench.run --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls

python -m rewardbench.run --config configs/apollolander_pilot_openai_gpt54mini.yaml \
  --mode live --i-authorize-paid-api-calls --authorize-continuation
```

Resume reuses the selected attempt for finished revisions and does not repeat
those paid calls. Held-out rows from other experiments are never loaded into a
development request.

Paired offline ApolloLander development configs:

- ``configs/apollolander_offline_development_numerical.yaml``
- ``configs/apollolander_offline_development_nofeedback.yaml``

They share seed schedules, revision limits, and simulator parameters. Only
``feedback_condition``, experiment names, database paths, and notes differ.

Live pilot config (requires human spend approval before any real key is used):

- ``configs/apollolander_pilot_openai_gpt54mini.yaml``
- ``configs/apollolander_pilot_openai_gpt54mini_nofeedback.yaml``

### Held-out freeze and evaluation (no model calls)

After a development experiment reaches ``status=completed``, Core can freeze
one controller and score it on sealed held-out research starts:

```bash
python -m rewardbench.heldout \
  --database runs/apollolander_offline_numerical.sqlite \
  --source-config configs/apollolander_offline_development_numerical.yaml \
  --selection-rule last_valid_selected
```

Selection default is ``last_valid_selected``: the selected valid attempt with
the highest ``(revision_index, call_index)``. Held-out rewards are never used
to choose the controller.

The freeze records SHA-256 of canonical controller JSON, source experiment id,
model id, feedback condition, revision, call index, and attempt id. Evaluation
uses the ApolloLander research-mode adapter and the source config's
``held_out_seeds`` / ``start_schedule_version``. It never calls
``ModelClient.propose``.

Results are stored in additive SQLite tables that development history never
reads: ``frozen_controllers``, ``heldout_evaluations``, ``heldout_episodes``.
Repeated invocation of the same sealed evaluation fails closed.

Paired numerical and no-feedback development configs must share the same
held-out seed list so sealed starts are comparable across feedback conditions.

See ``examples/heldout/README.md``.

### ``metadata.adapter_kwargs``

Optional mapping of JSON-serializable constructor arguments for the
environment adapter. Core validates the mapping and passes accepted keys to
``make_environment``. Unsupported keys are dropped with a warning so older
adapters keep working.

### Agent 2 dependency — ApolloLander ``research_mode``

Core forwards ``metadata.adapter_kwargs.research_mode`` when
``ApolloLanderAdapter.__init__`` accepts that keyword. Agent 2 owns the
physics meaning. Until the constructor exposes it, offline configs may still
list ``research_mode: true``; Core warns and continues without changing
physics.

Agent 2 should expose, without breaking existing callers:

```python
class ApolloLanderAdapter:
    def __init__(
        self,
        *,
        max_steps: int = 8000,
        locked_camera: bool = True,
        record_dir: str | Path | None = None,
        record_video: bool = False,
        research_mode: bool = False,
    ) -> None: ...
```

When ``research_mode`` is true, Agent 2's deterministic research starts and
recording interface apply. Core does not interpret the flag beyond forwarding
it.

## Runner

```python
class BudgetLimiter:
    def __init__(
        self,
        limits: BudgetLimits,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None: ...
    def elapsed(self) -> float: ...
    def snapshot(self) -> BudgetSnapshot: ...
    def restore(self, snapshot: BudgetSnapshot) -> None: ...
    def ensure_can_start(
        self,
        *,
        model_call: bool = False,
        episode: bool = False,
        revision: bool = False,
    ) -> None: ...
    def ensure_within_limits(self) -> None: ...
    def charge(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        episodes: int = 0,
        revisions: int = 0,
        model_calls: int = 0,
    ) -> None: ...

class HistoryBuilder:
    def __init__(self, window: int, condition: FeedbackCondition) -> None: ...
    def build(self, entries: Sequence[RevisionHistoryEntry]) -> tuple[PriorAttempt, ...]: ...

@dataclass(frozen=True)
class RevisionHistoryEntry:
    revision_index: int
    parameters: Mapping[str, Any]
    valid: bool
    validation_error: str | None
    episodes: tuple[EpisodeResult, ...]

def feedback_for_revision(
    episodes: Sequence[EpisodeResult],
    condition: FeedbackCondition,
) -> tuple[RewardFeedback, ...] | None: ...

class ExperimentRunner:
    def __init__(
        self,
        config: ExperimentConfig,
        model: ModelClient,
        environment: EnvironmentAdapter,
        store: ExperimentStore,
        *,
        global_budget: BudgetLimiter | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None: ...
    def run(self) -> ExperimentSummary: ...
```

`run` creates the experiment or resumes it. A completed experiment returns
its summary and does not call the model again. Resume rebuilds spend from
stored attempts and episodes, keeps elapsed time from the checkpoint, and
continues at the first incomplete revision. It reuses a selected attempt
instead of calling the model again, and it skips episode rows that already
exist.

The concrete store is `rewardbench.storage.SqliteStore`:

```python
class SqliteStore:
    def __init__(self, path: str | Path) -> None: ...
    def close(self) -> None: ...
    def __enter__(self) -> SqliteStore: ...
    def __exit__(self, *exc: object) -> None: ...
```

`SqliteStore` implements `ExperimentStore`. One database file may hold many
experiments. Pass `ExperimentConfig.database_path`.

`global_budget`, when it is a different limiter from the experiment budget,
is the shared spending cap. Pass the same object to every run that must share
it. The limiter counts each stored attempt once, including after resume, and
overlapping runs cannot both start a paid call when only one fits under the
cap. Dollar and token limits block further model calls. They still allow
episodes for a controller that was already purchased. The v1.0.0 method
signatures are unchanged.

A repeated `run` of a completed, failed, or locally budget-exhausted
experiment does not call the model again. An interrupted run continues at the
first incomplete revision and reuses a selected controller. One experiment
cannot be executed twice at the same time; the second caller waits, then sees
the stored result.

The model request uses the environment description captured at the start of
the run. No-feedback history has `feedback is None` and does not include
reward fields. Episodes whose seeds are outside the active split are omitted
from that history. Held-out rows stored for another experiment are not read
into a development request.

Handled stops:

- Invalid controller: no `run_episode` call. Default policy is `skip`.
  `abort` stores the failure and returns `ExperimentSummary` with
  `status=failed`.
- `ModelClientError`: retried while `retryable` and attempts remain.
  Non-retryable errors stop immediately. Default policy is `abort`.
- Episode exception: the episode row stores `error`. Default policy is
  `skip`.
- `BudgetExceeded`: status `budget_exhausted`. `run` returns a summary and
  does not raise.
- `KeyboardInterrupt`: status `interrupted`, checkpoint saved, interrupt
  re-raised.

Rewards are written for both feedback conditions. Only the `ModelRequest`
history changes.

## Reward history

`HistoryBuilder` keeps at most `history_window` prior revisions. Under
`no_feedback`, each `PriorAttempt.feedback` is `None` even when episodes
were scored. Under `numerical_reward`, feedback contains one
`RewardFeedback` per episode that has a finite reward and no error.
Episodes with errors are omitted from the model view and kept in SQLite.

## SQLite schema

Tables: `schema_meta`, `experiments`, `sessions`, `attempts`, `episodes`,
`errors`, `checkpoints`.

View: `scores`, with `total_reward` exposed as `score`.

`attempts` is unique on `(experiment_id, revision_index, call_index)`.
`episodes` is unique on `(experiment_id, revision_index, episode_index)`.

Analysis should treat these rows as the source of truth:

- reward versus revision: `episodes.revision_index`, `episodes.total_reward`
- success and crashes: `episodes.success`, `episodes.crashed`
- invalid controllers: `attempts.valid` where `attempts.selected = 1`
- cost and tokens: `attempts.estimated_cost_usd`, `attempts.total_tokens`,
  `attempts.prompt_tokens`, `attempts.completion_tokens`,
  `attempts.reasoning_tokens`
- latency: `attempts.latency_seconds`, `episodes.elapsed_seconds`
- errors: `errors`, plus `attempts.error` and `episodes.error`
- split and condition: `experiments.split`, `experiments.feedback_condition`

Development rows and held-out rows are different experiment ids because
`split` is part of the hash. Do not read held-out seeds from a development
experiment.

## Example configuration

See `configs/lunarlander_development_numerical.yaml`.
The no-feedback and held-out files differ only in `feedback_condition` or
`split`, which changes the experiment id.
