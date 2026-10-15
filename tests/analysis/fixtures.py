"""SYNTHETIC FIXTURES.

Records built here are invented inputs for unit tests. They are not
experimental results, and they must not be copied into a paper, blog,
or model comparison.

The SQLite statements mirror schema version 1 from ``docs/INTERFACES.md``
so the loader can be tested without importing the runner.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE experiments (
    experiment_id TEXT PRIMARY KEY,
    experiment_name TEXT NOT NULL,
    environment_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    feedback_condition TEXT NOT NULL,
    split TEXT NOT NULL,
    seed INTEGER NOT NULL,
    contract_version TEXT NOT NULL,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    schema_version INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_revisions INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    python_version TEXT NOT NULL,
    platform TEXT NOT NULL,
    error TEXT
);

CREATE TABLE attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    revision_index INTEGER NOT NULL,
    call_index INTEGER NOT NULL,
    selected INTEGER NOT NULL,
    parameters_json TEXT NOT NULL,
    raw_response TEXT NOT NULL,
    valid INTEGER NOT NULL,
    validation_error TEXT,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    reasoning_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    latency_seconds REAL NOT NULL,
    estimated_cost_usd REAL NOT NULL,
    model_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (experiment_id, revision_index, call_index)
);

CREATE TABLE episodes (
    episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    revision_index INTEGER NOT NULL,
    episode_index INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    total_reward REAL,
    success INTEGER,
    crashed INTEGER,
    steps INTEGER NOT NULL,
    terminated INTEGER NOT NULL,
    truncated INTEGER NOT NULL,
    elapsed_seconds REAL NOT NULL,
    metrics_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (experiment_id, revision_index, episode_index)
);

CREATE TABLE errors (
    error_id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    phase TEXT NOT NULL,
    message TEXT NOT NULL,
    revision_index INTEGER,
    episode_index INTEGER,
    traceback TEXT,
    created_at TEXT NOT NULL
);
"""


def connect_memory() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT INTO schema_meta (key, value) VALUES ('schema_version', '1')"
    )
    return connection


def write_database(path: Path, connection: sqlite3.Connection) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    connection.commit()
    persisted = sqlite3.connect(path)
    try:
        connection.backup(persisted)
    finally:
        persisted.close()


def insert_experiment(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    model_id: str,
    provider: str = "fixture-provider",
    condition: str = "numerical_reward",
    split: str = "development",
    seed: int = 0,
    synthetic: bool = True,
    validation_status: str = "preliminary",
    development_seeds: tuple[int, ...] = (1, 2),
    held_out_seeds: tuple[int, ...] = (9,),
    status: str = "completed",
) -> None:
    config = {
        "development_seeds": list(development_seeds),
        "held_out_seeds": list(held_out_seeds),
        "metadata": {
            "synthetic": synthetic,
            "validation_status": validation_status,
        },
    }
    connection.execute(
        """
        INSERT INTO experiments (
            experiment_id, experiment_name, environment_id, provider, model_id,
            feedback_condition, split, seed, contract_version, config_json,
            config_hash, status, schema_version, created_at, updated_at,
            completed_revisions
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            experiment_id,
            "fixture",
            "LunarLander-v3",
            provider,
            model_id,
            condition,
            split,
            seed,
            "1.0.0",
            json.dumps(config),
            "fixture-hash",
            status,
            1,
            "2026-01-01T00:00:00+00:00",
            "2026-01-01T00:00:00+00:00",
            1,
        ),
    )


def insert_session(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    experiment_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO sessions (
            session_id, experiment_id, status, started_at, ended_at,
            python_version, platform
        ) VALUES (?, ?, 'completed', '2026-01-01T00:00:00+00:00',
                  '2026-01-01T00:10:00+00:00', '3.11', 'fixture')
        """,
        (session_id, experiment_id),
    )


def insert_attempt(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    session_id: str,
    revision_index: int,
    call_index: int = 0,
    selected: bool = True,
    valid: bool = True,
    cost: float = 0.5,
    tokens: int = 100,
    latency: float = 1.0,
    validation_error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO attempts (
            experiment_id, session_id, revision_index, call_index, selected,
            parameters_json, raw_response, valid, validation_error,
            prompt_tokens, completion_tokens, reasoning_tokens, total_tokens,
            latency_seconds, estimated_cost_usd, model_id, provider, created_at
        ) VALUES (?, ?, ?, ?, ?, '{}', '{}', ?, ?, 40, 60, 0, ?, ?, ?, 'model', 'provider',
                  '2026-01-01T00:00:00+00:00')
        """,
        (
            experiment_id,
            session_id,
            revision_index,
            call_index,
            int(selected),
            int(valid),
            validation_error,
            tokens,
            latency,
            cost,
        ),
    )


def insert_episode(
    connection: sqlite3.Connection,
    *,
    experiment_id: str,
    session_id: str,
    revision_index: int,
    episode_index: int,
    seed: int,
    reward: float | None,
    success: bool | None,
    crashed: bool | None,
    elapsed: float = 2.0,
    error: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO episodes (
            experiment_id, session_id, revision_index, episode_index, seed,
            total_reward, success, crashed, steps, terminated, truncated,
            elapsed_seconds, metrics_json, error, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 10, 1, 0, ?, '{}', ?, '2026-01-01T00:00:00+00:00')
        """,
        (
            experiment_id,
            session_id,
            revision_index,
            episode_index,
            seed,
            reward,
            None if success is None else int(success),
            None if crashed is None else int(crashed),
            elapsed,
            error,
        ),
    )


def build_synthetic_plot_log(path: Path) -> None:
    """Two fictional model ids, two conditions, enough rows to draw every figure."""

    connection = connect_memory()
    specs = [
        ("exp-a-reward", "ses-a-reward", "model-a", "numerical_reward", (-40.0, 10.0)),
        ("exp-a-none", "ses-a-none", "model-a", "no_feedback", (-30.0, -25.0)),
        ("exp-b-reward", "ses-b-reward", "model-b", "numerical_reward", (-20.0, 5.0)),
        ("exp-b-none", "ses-b-none", "model-b", "no_feedback", (-15.0, -12.0)),
    ]
    for experiment_id, session_id, model_id, condition, (initial, final) in specs:
        insert_experiment(
            connection,
            experiment_id=experiment_id,
            model_id=model_id,
            condition=condition,
            synthetic=True,
        )
        insert_session(connection, session_id=session_id, experiment_id=experiment_id)
        for revision, reward in ((0, initial), (1, final)):
            insert_attempt(
                connection,
                experiment_id=experiment_id,
                session_id=session_id,
                revision_index=revision,
                cost=1.0,
            )
            insert_episode(
                connection,
                experiment_id=experiment_id,
                session_id=session_id,
                revision_index=revision,
                episode_index=0,
                seed=1,
                reward=reward,
                success=reward > 0,
                crashed=False,
            )
    write_database(path, connection)
    connection.close()
