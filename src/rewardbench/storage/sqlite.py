"""SQLite log of experiments, sessions, attempts, episodes, errors, and cost."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rewardbench.contracts import (
    SCHEMA_VERSION,
    BudgetSnapshot,
    Checkpoint,
    ExperimentRecord,
    ExperimentStatus,
    FeedbackCondition,
    ResumeError,
    SessionRecord,
    Split,
    StoredAttempt,
    StoredEpisode,
    StoredError,
)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dump(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _load(text: str) -> Any:
    return json.loads(text)


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


class SqliteStore:
    """One database file can hold every experiment for later analysis."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA busy_timeout = 5000")
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            pass

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> SqliteStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def initialize(self) -> None:
        script = _SCHEMA_PATH.read_text(encoding="utf-8")
        with self._lock:
            self._conn.executescript(script)
            with self._conn:
                # Serialize version initialization and additive migrations across
                # independent connections opening the same new database.
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT value FROM schema_meta WHERE key = 'schema_version'"
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', ?)",
                        (str(SCHEMA_VERSION),),
                    )
                elif int(row["value"]) != SCHEMA_VERSION:
                    raise ResumeError(
                        f"database schema version is {row['value']}, expected {SCHEMA_VERSION}"
                    )
                # Additive v1 migration: old rows have no provider provenance.
                columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(attempts)")}
                if "usage_json" not in columns:
                    self._conn.execute("ALTER TABLE attempts ADD COLUMN usage_json TEXT NOT NULL DEFAULT '{}'")

    def create_experiment(self, record: ExperimentRecord) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO experiments (
                        experiment_id, experiment_name, environment_id, provider,
                        model_id, feedback_condition, split, seed, contract_version,
                        config_json, config_hash, status, schema_version, created_at,
                        updated_at, completed_revisions, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.experiment_id,
                        record.experiment_name,
                        record.environment_id,
                        record.provider,
                        record.model_id,
                        record.feedback_condition.value,
                        record.split.value,
                        record.seed,
                        record.contract_version,
                        record.config_json,
                        record.config_hash,
                        record.status.value,
                        SCHEMA_VERSION,
                        record.created_at or utc_now(),
                        record.updated_at or utc_now(),
                        record.completed_revisions,
                        record.error,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(
                    f"experiment {record.experiment_id} already exists"
                ) from exc
            self._conn.commit()

    def get_experiment(self, experiment_id: str) -> ExperimentRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM experiments WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        return _experiment_from_row(row)

    def update_experiment(
        self,
        experiment_id: str,
        *,
        status: ExperimentStatus,
        error: str | None = None,
        completed_revisions: int | None = None,
    ) -> None:
        assignments = ["status = ?", "updated_at = ?", "error = ?"]
        params: list[Any] = [status.value, utc_now(), error]
        if completed_revisions is not None:
            assignments.append("completed_revisions = ?")
            params.append(completed_revisions)
        params.append(experiment_id)
        with self._lock:
            cursor = self._conn.execute(
                f"UPDATE experiments SET {', '.join(assignments)} WHERE experiment_id = ?",
                params,
            )
            if cursor.rowcount != 1:
                raise ResumeError(f"experiment {experiment_id} was not found")
            self._conn.commit()

    def start_session(self, record: SessionRecord) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO sessions (
                    session_id, experiment_id, status, started_at, ended_at,
                    python_version, platform, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.session_id,
                    record.experiment_id,
                    record.status.value,
                    record.started_at,
                    record.ended_at,
                    record.python_version,
                    record.platform,
                    record.error,
                ),
            )
            self._conn.commit()

    def end_session(
        self,
        session_id: str,
        *,
        status: ExperimentStatus,
        error: str | None = None,
    ) -> None:
        with self._lock:
            cursor = self._conn.execute(
                """
                UPDATE sessions
                SET status = ?, ended_at = ?, error = ?
                WHERE session_id = ?
                """,
                (status.value, utc_now(), error, session_id),
            )
            if cursor.rowcount != 1:
                raise ResumeError(f"session {session_id} was not found")
            self._conn.commit()

    def insert_attempt(self, record: StoredAttempt) -> int:
        created_at = record.created_at or utc_now()
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    INSERT INTO attempts (
                        experiment_id, session_id, revision_index, call_index,
                        selected, parameters_json, raw_response, valid,
                        validation_error, prompt_tokens, completion_tokens,
                        reasoning_tokens, total_tokens, latency_seconds,
                        estimated_cost_usd, model_id, provider, error, created_at, usage_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.experiment_id,
                        record.session_id,
                        record.revision_index,
                        record.call_index,
                        int(record.selected),
                        _dump(dict(record.parameters)),
                        record.raw_response,
                        int(record.valid),
                        record.validation_error,
                        record.prompt_tokens,
                        record.completion_tokens,
                        record.reasoning_tokens,
                        record.total_tokens,
                        record.latency_seconds,
                        record.estimated_cost_usd,
                        record.model_id,
                        record.provider,
                        record.error,
                        created_at,
                        _dump(dict(record.usage)),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(
                    "attempt already exists for "
                    f"{record.experiment_id} revision {record.revision_index} "
                    f"call {record.call_index}"
                ) from exc
            self._conn.commit()
            return int(cursor.lastrowid)

    def insert_episode(self, record: StoredEpisode) -> int:
        created_at = record.created_at or utc_now()
        with self._lock:
            try:
                cursor = self._conn.execute(
                    """
                    INSERT INTO episodes (
                        experiment_id, session_id, revision_index, episode_index,
                        seed, total_reward, success, crashed, steps, terminated,
                        truncated, elapsed_seconds, metrics_json, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.experiment_id,
                        record.session_id,
                        record.revision_index,
                        record.episode_index,
                        record.seed,
                        record.total_reward,
                        None if record.success is None else int(record.success),
                        None if record.crashed is None else int(record.crashed),
                        record.steps,
                        int(record.terminated),
                        int(record.truncated),
                        record.elapsed_seconds,
                        _dump(dict(record.metrics)),
                        record.error,
                        created_at,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(
                    "episode already exists for "
                    f"{record.experiment_id} revision {record.revision_index} "
                    f"episode {record.episode_index}"
                ) from exc
            self._conn.commit()
            return int(cursor.lastrowid)

    def insert_error(self, record: StoredError) -> int:
        created_at = record.created_at or utc_now()
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO errors (
                    experiment_id, session_id, phase, message, revision_index,
                    episode_index, traceback, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.experiment_id,
                    record.session_id,
                    record.phase,
                    record.message,
                    record.revision_index,
                    record.episode_index,
                    record.traceback,
                    created_at,
                ),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        budget = {
            "cost_usd": checkpoint.budget.cost_usd,
            "tokens": checkpoint.budget.tokens,
            "episodes": checkpoint.budget.episodes,
            "revisions": checkpoint.budget.revisions,
            "model_calls": checkpoint.budget.model_calls,
            "elapsed_seconds": checkpoint.budget.elapsed_seconds,
        }
        schedule = [list(row) for row in checkpoint.seed_schedule]
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO checkpoints (
                    experiment_id, next_revision_index, budget_json,
                    seed_schedule_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    next_revision_index = excluded.next_revision_index,
                    budget_json = excluded.budget_json,
                    seed_schedule_json = excluded.seed_schedule_json,
                    updated_at = excluded.updated_at
                """,
                (
                    checkpoint.experiment_id,
                    checkpoint.next_revision_index,
                    _dump(budget),
                    _dump(schedule),
                    checkpoint.updated_at or utc_now(),
                ),
            )
            self._conn.commit()

    def load_checkpoint(self, experiment_id: str) -> Checkpoint | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM checkpoints WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchone()
        if row is None:
            return None
        budget = _load(row["budget_json"])
        schedule = tuple(tuple(int(seed) for seed in row_seeds) for row_seeds in _load(row["seed_schedule_json"]))
        return Checkpoint(
            experiment_id=row["experiment_id"],
            next_revision_index=row["next_revision_index"],
            budget=BudgetSnapshot(
                cost_usd=float(budget["cost_usd"]),
                tokens=int(budget["tokens"]),
                episodes=int(budget["episodes"]),
                revisions=int(budget["revisions"]),
                model_calls=int(budget["model_calls"]),
                elapsed_seconds=float(budget["elapsed_seconds"]),
            ),
            seed_schedule=schedule,
            updated_at=row["updated_at"],
        )

    def fetch_attempts(self, experiment_id: str) -> list[StoredAttempt]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM attempts
                WHERE experiment_id = ?
                ORDER BY revision_index, call_index
                """,
                (experiment_id,),
            ).fetchall()
        return [_attempt_from_row(row) for row in rows]

    def fetch_episodes(self, experiment_id: str) -> list[StoredEpisode]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM episodes
                WHERE experiment_id = ?
                ORDER BY revision_index, episode_index
                """,
                (experiment_id,),
            ).fetchall()
        return [_episode_from_row(row) for row in rows]

    def fetch_errors(self, experiment_id: str) -> list[StoredError]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM errors
                WHERE experiment_id = ?
                ORDER BY error_id
                """,
                (experiment_id,),
            ).fetchall()
        return [_error_from_row(row) for row in rows]

    def fetch_sessions(self, experiment_id: str) -> list[SessionRecord]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM sessions
                WHERE experiment_id = ?
                ORDER BY started_at, session_id
                """,
                (experiment_id,),
            ).fetchall()
        return [_session_from_row(row) for row in rows]

    def fetch_scores(self, experiment_id: str) -> list[dict[str, Any]]:
        """Read the ``scores`` view. ``score`` is the environment reward."""

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM scores
                WHERE experiment_id = ?
                ORDER BY revision_index, episode_index
                """,
                (experiment_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- Held-out freeze / evaluation (not part of ModelRequest history) ---

    def insert_frozen_controller(self, record: Any) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO frozen_controllers (
                        freeze_id, controller_hash, parameters_json, source_experiment_id,
                        source_attempt_id, source_revision_index, source_call_index,
                        source_session_id, model_id, provider, feedback_condition,
                        environment_id, selection_rule, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.freeze_id,
                        record.controller_hash,
                        _dump(dict(record.parameters)),
                        record.source_experiment_id,
                        record.source_attempt_id,
                        record.source_revision_index,
                        record.source_call_index,
                        record.source_session_id,
                        record.model_id,
                        record.provider,
                        record.feedback_condition.value,
                        record.environment_id,
                        record.selection_rule,
                        record.created_at or utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(f"frozen controller already exists: {exc}") from exc
            self._conn.commit()

    def get_frozen_controller(self, freeze_id: str) -> Any | None:
        from rewardbench.core.heldout import FrozenController

        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM frozen_controllers WHERE freeze_id = ?",
                (freeze_id,),
            ).fetchone()
        if row is None:
            return None
        return FrozenController(
            freeze_id=row["freeze_id"],
            controller_hash=row["controller_hash"],
            parameters=_load(row["parameters_json"]),
            source_experiment_id=row["source_experiment_id"],
            source_attempt_id=row["source_attempt_id"],
            source_revision_index=row["source_revision_index"],
            source_call_index=row["source_call_index"],
            source_session_id=row["source_session_id"],
            model_id=row["model_id"],
            provider=row["provider"],
            feedback_condition=FeedbackCondition(row["feedback_condition"]),
            environment_id=row["environment_id"],
            selection_rule=row["selection_rule"],
            created_at=row["created_at"],
        )

    def insert_heldout_evaluation(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO heldout_evaluations (
                        evaluation_id, freeze_id, source_experiment_id, environment_id,
                        environment_version, start_schedule_version, vary_fuel,
                        held_out_seeds_json, max_episode_steps, status, controller_hash,
                        created_at, updated_at, completed_episodes, error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["evaluation_id"],
                        record["freeze_id"],
                        record["source_experiment_id"],
                        record["environment_id"],
                        record["environment_version"],
                        record["start_schedule_version"],
                        1 if record["vary_fuel"] else 0,
                        _dump(list(record["held_out_seeds"])),
                        record.get("max_episode_steps"),
                        record["status"],
                        record["controller_hash"],
                        record["created_at"],
                        record["updated_at"],
                        int(record.get("completed_episodes", 0)),
                        record.get("error"),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(f"held-out evaluation already exists: {exc}") from exc
            self._conn.commit()

    def get_heldout_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM heldout_evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
        if row is None:
            return None
        return _heldout_evaluation_from_row(row)

    def find_heldout_evaluation(
        self,
        *,
        freeze_id: str,
        held_out_seeds: Sequence[int],
        start_schedule_version: str,
        environment_version: str,
        vary_fuel: bool,
        max_episode_steps: int | None,
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM heldout_evaluations
                WHERE freeze_id = ?
                  AND held_out_seeds_json = ?
                  AND start_schedule_version = ?
                  AND environment_version = ?
                  AND vary_fuel = ?
                  AND (
                    (max_episode_steps IS NULL AND ? IS NULL)
                    OR max_episode_steps = ?
                  )
                """,
                (
                    freeze_id,
                    _dump(list(held_out_seeds)),
                    start_schedule_version,
                    environment_version,
                    1 if vary_fuel else 0,
                    max_episode_steps,
                    max_episode_steps,
                ),
            ).fetchone()
        if row is None:
            return None
        return _heldout_evaluation_from_row(row)

    def update_heldout_evaluation(
        self,
        evaluation_id: str,
        *,
        status: str,
        completed_episodes: int | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT evaluation_id FROM heldout_evaluations WHERE evaluation_id = ?",
                (evaluation_id,),
            ).fetchone()
            if row is None:
                raise ResumeError(f"held-out evaluation {evaluation_id} was not found")
            fields = ["status = ?", "updated_at = ?", "error = ?"]
            values: list[Any] = [status, utc_now(), error]
            if completed_episodes is not None:
                fields.append("completed_episodes = ?")
                values.append(int(completed_episodes))
            values.append(evaluation_id)
            self._conn.execute(
                f"UPDATE heldout_evaluations SET {', '.join(fields)} WHERE evaluation_id = ?",
                values,
            )
            self._conn.commit()

    def insert_heldout_episode(self, record: Mapping[str, Any]) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    """
                    INSERT INTO heldout_episodes (
                        evaluation_id, freeze_id, source_experiment_id, episode_index,
                        seed, total_reward, success, crashed, steps, terminated,
                        truncated, elapsed_seconds, metrics_json, initial_state_json,
                        replay_path, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record["evaluation_id"],
                        record["freeze_id"],
                        record["source_experiment_id"],
                        record["episode_index"],
                        record["seed"],
                        record.get("total_reward"),
                        None if record.get("success") is None else int(bool(record["success"])),
                        None if record.get("crashed") is None else int(bool(record["crashed"])),
                        record["steps"],
                        int(bool(record["terminated"])),
                        int(bool(record["truncated"])),
                        record["elapsed_seconds"],
                        _dump(dict(record.get("metrics") or {})),
                        _dump(dict(record.get("initial_state") or {})),
                        record.get("replay_path"),
                        record.get("error"),
                        record.get("created_at") or utc_now(),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ResumeError(f"held-out episode already exists: {exc}") from exc
            self._conn.commit()

    def fetch_heldout_episodes(self, evaluation_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM heldout_episodes
                WHERE evaluation_id = ?
                ORDER BY episode_index
                """,
                (evaluation_id,),
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            result.append(
                {
                    "heldout_episode_id": row["heldout_episode_id"],
                    "evaluation_id": row["evaluation_id"],
                    "freeze_id": row["freeze_id"],
                    "source_experiment_id": row["source_experiment_id"],
                    "episode_index": row["episode_index"],
                    "seed": row["seed"],
                    "total_reward": row["total_reward"],
                    "success": _optional_bool(row["success"]),
                    "crashed": _optional_bool(row["crashed"]),
                    "steps": row["steps"],
                    "terminated": bool(row["terminated"]),
                    "truncated": bool(row["truncated"]),
                    "elapsed_seconds": row["elapsed_seconds"],
                    "metrics": _load(row["metrics_json"]),
                    "initial_state": _load(row["initial_state_json"]),
                    "replay_path": row["replay_path"],
                    "error": row["error"],
                    "created_at": row["created_at"],
                }
            )
        return result


def _heldout_evaluation_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "evaluation_id": row["evaluation_id"],
        "freeze_id": row["freeze_id"],
        "source_experiment_id": row["source_experiment_id"],
        "environment_id": row["environment_id"],
        "environment_version": row["environment_version"],
        "start_schedule_version": row["start_schedule_version"],
        "vary_fuel": bool(row["vary_fuel"]),
        "held_out_seeds": tuple(_load(row["held_out_seeds_json"])),
        "max_episode_steps": row["max_episode_steps"],
        "status": row["status"],
        "controller_hash": row["controller_hash"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_episodes": row["completed_episodes"],
        "error": row["error"],
    }


def _experiment_from_row(row: sqlite3.Row) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=row["experiment_id"],
        experiment_name=row["experiment_name"],
        environment_id=row["environment_id"],
        provider=row["provider"],
        model_id=row["model_id"],
        feedback_condition=FeedbackCondition(row["feedback_condition"]),
        split=Split(row["split"]),
        seed=row["seed"],
        contract_version=row["contract_version"],
        config_json=row["config_json"],
        config_hash=row["config_hash"],
        status=ExperimentStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_revisions=row["completed_revisions"],
        error=row["error"],
    )


def _attempt_from_row(row: sqlite3.Row) -> StoredAttempt:
    return StoredAttempt(
        experiment_id=row["experiment_id"],
        session_id=row["session_id"],
        revision_index=row["revision_index"],
        call_index=row["call_index"],
        selected=bool(row["selected"]),
        parameters=_load(row["parameters_json"]),
        raw_response=row["raw_response"],
        valid=bool(row["valid"]),
        validation_error=row["validation_error"],
        prompt_tokens=row["prompt_tokens"],
        completion_tokens=row["completion_tokens"],
        reasoning_tokens=row["reasoning_tokens"],
        total_tokens=row["total_tokens"],
        latency_seconds=row["latency_seconds"],
        estimated_cost_usd=row["estimated_cost_usd"],
        model_id=row["model_id"],
        provider=row["provider"],
        error=row["error"],
        created_at=row["created_at"],
        attempt_id=row["attempt_id"],
        usage=_load(row["usage_json"]),
    )


def _episode_from_row(row: sqlite3.Row) -> StoredEpisode:
    return StoredEpisode(
        experiment_id=row["experiment_id"],
        session_id=row["session_id"],
        revision_index=row["revision_index"],
        episode_index=row["episode_index"],
        seed=row["seed"],
        total_reward=row["total_reward"],
        success=_optional_bool(row["success"]),
        crashed=_optional_bool(row["crashed"]),
        steps=row["steps"],
        terminated=bool(row["terminated"]),
        truncated=bool(row["truncated"]),
        elapsed_seconds=row["elapsed_seconds"],
        metrics=_load(row["metrics_json"]),
        error=row["error"],
        created_at=row["created_at"],
        episode_id=row["episode_id"],
    )


def _error_from_row(row: sqlite3.Row) -> StoredError:
    return StoredError(
        experiment_id=row["experiment_id"],
        session_id=row["session_id"],
        phase=row["phase"],
        message=row["message"],
        revision_index=row["revision_index"],
        episode_index=row["episode_index"],
        traceback=row["traceback"],
        created_at=row["created_at"],
        error_id=row["error_id"],
    )


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        experiment_id=row["experiment_id"],
        status=ExperimentStatus(row["status"]),
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        python_version=row["python_version"],
        platform=row["platform"],
        error=row["error"],
    )
