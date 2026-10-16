"""Freeze a development controller and score it on sealed held-out starts.

Held-out evaluation never calls ``ModelClient.propose``. Results are stored in
dedicated SQLite tables that the development runner and prompt history never
read, so evaluation scores cannot contaminate resumed training.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rewardbench.contracts import (
    CandidatePolicy,
    ConfigError,
    EnvironmentAdapter,
    ExperimentStatus,
    FeedbackCondition,
    Split,
    StoredAttempt,
)
from rewardbench.core.evaluation import SplitGuard
from rewardbench.environments.apollolander.starts import (
    START_SCHEDULE_VERSION,
    assert_schedules_disjoint,
    derive_start,
)
from rewardbench.storage import SqliteStore
from rewardbench.storage.sqlite import utc_now

SELECTION_LAST_VALID_SELECTED = "last_valid_selected"
SELECTION_RULES = (SELECTION_LAST_VALID_SELECTED,)


@dataclass(frozen=True)
class FrozenController:
    """Immutable snapshot of a development controller selected for evaluation."""

    freeze_id: str
    controller_hash: str
    parameters: Mapping[str, Any]
    source_experiment_id: str
    source_attempt_id: int
    source_revision_index: int
    source_call_index: int
    source_session_id: str
    model_id: str
    provider: str
    feedback_condition: FeedbackCondition
    environment_id: str
    selection_rule: str
    created_at: str


@dataclass(frozen=True)
class HeldOutEvaluationSummary:
    """Outcome of scoring one frozen controller on sealed held-out starts."""

    evaluation_id: str
    freeze_id: str
    source_experiment_id: str
    status: str
    controller_hash: str
    held_out_seeds: tuple[int, ...]
    start_schedule_version: str
    environment_version: str
    episodes_recorded: int
    mean_reward: float | None
    best_reward: float | None
    success_count: int
    error: str | None = None


class GuardedModelClient:
    """Stand-in that fails closed if any code path tries to call a model."""

    provider = "heldout-forbidden"
    model_id = "heldout-forbidden"

    def propose(self, request: object) -> object:  # pragma: no cover - defensive
        raise ConfigError(
            "held-out evaluation forbids ModelClient.propose; "
            "the frozen controller must be scored without a new model call"
        )


def canonical_controller_json(parameters: Mapping[str, Any]) -> str:
    return json.dumps(dict(parameters), sort_keys=True, separators=(",", ":"))


def controller_hash(parameters: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_controller_json(parameters).encode("utf-8")).hexdigest()


def select_final_controller(
    attempts: Sequence[StoredAttempt],
    *,
    rule: str = SELECTION_LAST_VALID_SELECTED,
) -> StoredAttempt:
    """Pick the development controller using a predefined rule.

    Default ``last_valid_selected`` uses the highest ``(revision_index, call_index)``
    among selected valid attempts. It does **not** look at held-out rewards.
    """

    if rule not in SELECTION_RULES:
        raise ConfigError(f"unknown selection rule {rule!r}; expected one of {SELECTION_RULES}")
    valid = [item for item in attempts if item.selected and item.valid]
    if not valid:
        raise ConfigError("no valid selected controller exists on the development experiment")
    return max(valid, key=lambda item: (item.revision_index, item.call_index, item.attempt_id or 0))


def freeze_id_for(
    *,
    source_experiment_id: str,
    source_attempt_id: int,
    controller_digest: str,
    selection_rule: str,
) -> str:
    payload = {
        "source_experiment_id": source_experiment_id,
        "source_attempt_id": source_attempt_id,
        "controller_hash": controller_digest,
        "selection_rule": selection_rule,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"frz_{digest[:20]}"


def evaluation_id_for(
    *,
    freeze_id: str,
    held_out_seeds: Sequence[int],
    start_schedule_version: str,
    environment_version: str,
    vary_fuel: bool,
    max_episode_steps: int | None,
) -> str:
    payload = {
        "freeze_id": freeze_id,
        "held_out_seeds": list(held_out_seeds),
        "start_schedule_version": start_schedule_version,
        "environment_version": environment_version,
        "vary_fuel": bool(vary_fuel),
        "max_episode_steps": max_episode_steps,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"hev_{digest[:20]}"


def load_source_config(store: SqliteStore, source_experiment_id: str) -> dict[str, Any]:
    record = store.get_experiment(source_experiment_id)
    if record is None:
        raise ConfigError(f"development experiment {source_experiment_id!r} was not found")
    if record.status is not ExperimentStatus.COMPLETED:
        raise ConfigError(
            f"development experiment {source_experiment_id!r} status is "
            f"{record.status.value}; held-out freeze requires status=completed"
        )
    if record.split is not Split.DEVELOPMENT:
        raise ConfigError(
            f"source experiment split is {record.split.value}; expected development"
        )
    try:
        payload = json.loads(record.config_json)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"source experiment config_json is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ConfigError("source experiment config_json must be an object")
    return payload


def freeze_controller_from_experiment(
    store: SqliteStore,
    source_experiment_id: str,
    *,
    selection_rule: str = SELECTION_LAST_VALID_SELECTED,
) -> FrozenController:
    """Select and persist the frozen controller for a completed development run."""

    store.initialize()
    record = store.get_experiment(source_experiment_id)
    if record is None:
        raise ConfigError(f"development experiment {source_experiment_id!r} was not found")
    if record.status is not ExperimentStatus.COMPLETED:
        raise ConfigError(
            f"development experiment {source_experiment_id!r} is not completed "
            f"(status={record.status.value})"
        )
    if record.split is not Split.DEVELOPMENT:
        raise ConfigError("held-out freeze requires a development-split source experiment")

    attempts = store.fetch_attempts(source_experiment_id)
    chosen = select_final_controller(attempts, rule=selection_rule)
    if chosen.attempt_id is None:
        raise ConfigError("selected attempt is missing attempt_id; cannot audit freeze provenance")
    digest = controller_hash(chosen.parameters)
    freeze_id = freeze_id_for(
        source_experiment_id=source_experiment_id,
        source_attempt_id=chosen.attempt_id,
        controller_digest=digest,
        selection_rule=selection_rule,
    )
    existing = store.get_frozen_controller(freeze_id)
    if existing is not None:
        if existing.controller_hash != digest:
            raise ConfigError(
                f"frozen controller {freeze_id} exists with a different controller hash; "
                "refusing to replace held-out evidence"
            )
        if dict(existing.parameters) != dict(chosen.parameters):
            raise ConfigError(
                f"frozen controller {freeze_id} parameters disagree with the source attempt; "
                "refusing to replace held-out evidence"
            )
        return existing

    frozen = FrozenController(
        freeze_id=freeze_id,
        controller_hash=digest,
        parameters=dict(chosen.parameters),
        source_experiment_id=source_experiment_id,
        source_attempt_id=chosen.attempt_id,
        source_revision_index=chosen.revision_index,
        source_call_index=chosen.call_index,
        source_session_id=chosen.session_id,
        model_id=chosen.model_id or record.model_id,
        provider=chosen.provider or record.provider,
        feedback_condition=record.feedback_condition,
        environment_id=record.environment_id,
        selection_rule=selection_rule,
        created_at=utc_now(),
    )
    store.insert_frozen_controller(frozen)
    return frozen


def evaluate_frozen_controller(
    store: SqliteStore,
    frozen: FrozenController,
    environment: EnvironmentAdapter,
    *,
    held_out_seeds: Sequence[int],
    development_seeds: Sequence[int],
    start_schedule_version: str = START_SCHEDULE_VERSION,
    vary_fuel: bool = False,
    max_episode_steps: int | None = None,
    environment_version: str,
    record_dir: str | Path | None = None,
) -> HeldOutEvaluationSummary:
    """Score a frozen controller on held-out starts without any model call."""

    store.initialize()
    if not held_out_seeds:
        raise ConfigError("held_out_seeds must be non-empty")
    guard = SplitGuard(Split.HELD_OUT, development_seeds, held_out_seeds)
    for seed in held_out_seeds:
        guard.check(seed)

    # Research schedule integrity: catalogs must stay disjoint.
    try:
        assert_schedules_disjoint(
            [
                (seed, derive_start(seed, version=start_schedule_version, vary_fuel=vary_fuel))
                for seed in development_seeds
            ],
            [
                (seed, derive_start(seed, version=start_schedule_version, vary_fuel=vary_fuel))
                for seed in held_out_seeds
            ],
        )
    except ValueError as exc:
        raise ConfigError(f"research schedule mismatch: {exc}") from exc

    if frozen.controller_hash != controller_hash(frozen.parameters):
        raise ConfigError("controller hash no longer matches frozen parameters; refusing evaluation")

    research_mode = bool(getattr(environment, "research_mode", False))
    if not research_mode:
        raise ConfigError(
            "held-out evaluation requires the ApolloLander research-mode adapter "
            "(research_mode=True)"
        )
    adapter_schedule = getattr(environment, "start_schedule_version", None)
    if adapter_schedule != start_schedule_version:
        raise ConfigError(
            f"adapter start_schedule_version {adapter_schedule!r} does not match "
            f"requested {start_schedule_version!r}"
        )
    spec = environment.describe()
    if spec.environment_id != frozen.environment_id:
        raise ConfigError(
            f"environment id {spec.environment_id!r} does not match frozen "
            f"controller environment {frozen.environment_id!r}"
        )

    validation = environment.validate_policy(dict(frozen.parameters))
    if not validation.valid:
        raise ConfigError(
            f"frozen controller failed validation before held-out flight: {validation.error}"
        )

    evaluation_id = evaluation_id_for(
        freeze_id=frozen.freeze_id,
        held_out_seeds=held_out_seeds,
        start_schedule_version=start_schedule_version,
        environment_version=environment_version,
        vary_fuel=vary_fuel,
        max_episode_steps=max_episode_steps,
    )
    existing = store.get_heldout_evaluation(evaluation_id)
    if existing is not None:
        if existing["status"] == "completed":
            raise ConfigError(
                f"held-out evaluation {evaluation_id} already completed; "
                "refusing to silently replace prior held-out evidence"
            )
        raise ConfigError(
            f"held-out evaluation {evaluation_id} already exists with status "
            f"{existing['status']!r}; refusing to replace prior evidence"
        )
    # Also refuse another completed eval for the same freeze+seeds via unique lookup.
    prior = store.find_heldout_evaluation(
        freeze_id=frozen.freeze_id,
        held_out_seeds=held_out_seeds,
        start_schedule_version=start_schedule_version,
        environment_version=environment_version,
        vary_fuel=vary_fuel,
        max_episode_steps=max_episode_steps,
    )
    if prior is not None:
        raise ConfigError(
            f"held-out evaluation {prior['evaluation_id']} already exists for this "
            "frozen controller and sealed start schedule; refusing to replace evidence"
        )

    now = utc_now()
    store.insert_heldout_evaluation(
        {
            "evaluation_id": evaluation_id,
            "freeze_id": frozen.freeze_id,
            "source_experiment_id": frozen.source_experiment_id,
            "environment_id": frozen.environment_id,
            "environment_version": environment_version,
            "start_schedule_version": start_schedule_version,
            "vary_fuel": bool(vary_fuel),
            "held_out_seeds": list(held_out_seeds),
            "max_episode_steps": max_episode_steps,
            "status": "running",
            "controller_hash": frozen.controller_hash,
            "created_at": now,
            "updated_at": now,
            "completed_episodes": 0,
            "error": None,
        }
    )

    policy = CandidatePolicy(
        revision_index=frozen.source_revision_index,
        parameters=dict(frozen.parameters),
        raw_response=canonical_controller_json(frozen.parameters),
        valid=True,
        validation_error=None,
        model_id=frozen.model_id,
        provider="frozen",
    )
    # Defensive: ensure no code path can lazily grab a live model from this module.
    _ = GuardedModelClient()

    rewards: list[float] = []
    successes = 0
    try:
        for episode_index, seed in enumerate(held_out_seeds):
            guard.check(seed)
            start = derive_start(seed, version=start_schedule_version, vary_fuel=vary_fuel)
            result = environment.run_episode(
                policy,
                seed=seed,
                episode_index=episode_index,
                revision_index=frozen.source_revision_index,
                max_steps=max_episode_steps,
            )
            if result.seed != seed:
                raise ConfigError("episode result seed does not match the sealed held-out seed")
            if frozen.controller_hash != controller_hash(frozen.parameters):
                raise ConfigError("controller hash changed during evaluation; aborting")
            replay_path = None
            if record_dir is not None:
                # Provenance pointer only; Agent 2 owns flight file format.
                candidate = Path(record_dir) / f"heldout-{evaluation_id}-seed-{seed}.flight.json"
                if candidate.is_file():
                    replay_path = str(candidate)
            metrics = dict(result.metrics)
            store.insert_heldout_episode(
                {
                    "evaluation_id": evaluation_id,
                    "freeze_id": frozen.freeze_id,
                    "source_experiment_id": frozen.source_experiment_id,
                    "episode_index": episode_index,
                    "seed": seed,
                    "total_reward": result.total_reward,
                    "success": result.success,
                    "crashed": result.crashed,
                    "steps": result.steps,
                    "terminated": result.terminated,
                    "truncated": result.truncated,
                    "elapsed_seconds": result.elapsed_seconds,
                    "metrics": metrics,
                    "initial_state": start.as_dict(),
                    "replay_path": replay_path,
                    "error": result.error,
                    "created_at": utc_now(),
                }
            )
            if result.error is None and result.total_reward is not None:
                rewards.append(float(result.total_reward))
            if result.success:
                successes += 1
            store.update_heldout_evaluation(
                evaluation_id,
                status="running",
                completed_episodes=episode_index + 1,
                error=None,
            )
    except Exception as exc:
        store.update_heldout_evaluation(
            evaluation_id,
            status="failed",
            completed_episodes=len(rewards),
            error=str(exc),
        )
        raise

    store.update_heldout_evaluation(
        evaluation_id,
        status="completed",
        completed_episodes=len(held_out_seeds),
        error=None,
    )
    return HeldOutEvaluationSummary(
        evaluation_id=evaluation_id,
        freeze_id=frozen.freeze_id,
        source_experiment_id=frozen.source_experiment_id,
        status="completed",
        controller_hash=frozen.controller_hash,
        held_out_seeds=tuple(held_out_seeds),
        start_schedule_version=start_schedule_version,
        environment_version=environment_version,
        episodes_recorded=len(held_out_seeds),
        mean_reward=(sum(rewards) / len(rewards)) if rewards else None,
        best_reward=max(rewards) if rewards else None,
        success_count=successes,
        error=None,
    )


def adapter_settings_from_source_config(config_payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract research-mode adapter settings from a stored development config."""

    metadata = config_payload.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        raise ConfigError("source metadata must be a mapping")
    adapter_kwargs = dict(metadata.get("adapter_kwargs") or {})
    if not adapter_kwargs.get("research_mode", False):
        raise ConfigError(
            "source development experiment did not enable research_mode; "
            "held-out evaluation requires the versioned research start schedule"
        )
    schedule = adapter_kwargs.get("start_schedule_version", START_SCHEDULE_VERSION)
    if not isinstance(schedule, str) or not schedule:
        raise ConfigError("start_schedule_version must be a non-empty string")
    return {
        "research_mode": True,
        "start_schedule_version": schedule,
        "vary_fuel": bool(adapter_kwargs.get("vary_fuel", False)),
        "max_steps": config_payload.get("max_episode_steps") or adapter_kwargs.get("max_steps"),
        "locked_camera": bool(adapter_kwargs.get("locked_camera", True)),
    }
