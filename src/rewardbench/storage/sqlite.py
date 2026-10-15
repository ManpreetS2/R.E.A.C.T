"""SQLite log of experiments, sessions, attempts, episodes, errors, and cost."""

from __future__ import annotations

import json
import sqlite3
import threading
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
            self._conn.commit()

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
                        estimated_cost_usd, model_id, provider, error, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
