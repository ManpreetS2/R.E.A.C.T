"""Sealed held-out rows appear in the markdown report (read-only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rewardbench.analysis.heldout import load_heldout_summaries
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.report import write_report
from fixtures import connect_memory, write_database


def _add_heldout_tables(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS frozen_controllers (
            freeze_id TEXT PRIMARY KEY,
            controller_hash TEXT NOT NULL,
            parameters_json TEXT NOT NULL,
            source_experiment_id TEXT NOT NULL,
            source_attempt_id INTEGER NOT NULL,
            source_revision_index INTEGER NOT NULL,
            source_call_index INTEGER NOT NULL,
            source_session_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            provider TEXT NOT NULL,
            feedback_condition TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            selection_rule TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS heldout_evaluations (
            evaluation_id TEXT PRIMARY KEY,
            freeze_id TEXT NOT NULL,
            source_experiment_id TEXT NOT NULL,
            environment_id TEXT NOT NULL,
            environment_version TEXT NOT NULL,
            start_schedule_version TEXT NOT NULL,
            vary_fuel INTEGER NOT NULL,
            held_out_seeds_json TEXT NOT NULL,
            max_episode_steps INTEGER,
            status TEXT NOT NULL,
            controller_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_episodes INTEGER NOT NULL DEFAULT 0,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS heldout_episodes (
            heldout_episode_id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluation_id TEXT NOT NULL,
            freeze_id TEXT NOT NULL,
            source_experiment_id TEXT NOT NULL,
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
            initial_state_json TEXT NOT NULL,
            replay_path TEXT,
            error TEXT,
            created_at TEXT NOT NULL
        );
        """
    )


def test_report_summarizes_heldout_tables(tmp_path: Path) -> None:
    database = tmp_path / "with_heldout.sqlite"
    connection = connect_memory()
    write_database(database, connection)
    connection.close()

    con = sqlite3.connect(database)
    _add_heldout_tables(con)
    # Reuse the experiment id written by the synthetic fixture loader path:
    # write_database may leave an empty DB — insert a minimal experiment row.
    con.execute(
        """
        INSERT OR IGNORE INTO experiments (
            experiment_id, experiment_name, environment_id, provider, model_id,
            feedback_condition, split, seed, contract_version, config_json, config_hash,
            status, schema_version, created_at, updated_at, completed_revisions, error
        ) VALUES (
            'exp_demo', 'demo', 'apollolander', 'mock', 'scripted-feedback-responsive',
            'numerical_reward', 'development', 0, '1.0.0', '{}', 'hash',
            'completed', 1, 't', 't', 1, NULL
        )
        """
    )
    con.execute(
        """
        INSERT INTO frozen_controllers VALUES (
            'frz_1', 'abc123controllerhash', '{}', 'exp_demo', 1, 0, 0, 'ses_1',
            'scripted-feedback-responsive', 'mock', 'numerical_reward', 'apollolander',
            'last_valid_selected', 't'
        )
        """
    )
    con.execute(
        """
        INSERT INTO heldout_evaluations VALUES (
            'hev_1', 'frz_1', 'exp_demo', 'apollolander', 'apollolander.env.v1',
            'apollolander.starts.v1', 0, '[2000000,2000001]', 100, 'completed',
            'abc123controllerhash', 't', 't', 2, NULL
        )
        """
    )
    for idx, (seed, reward, success, crashed, truncated, replay) in enumerate(
        [
            (2_000_000, 10.0, 1, 0, 0, "runs/flights/a.flight.json"),
            (2_000_001, -5.0, 0, 0, 1, None),
        ]
    ):
        con.execute(
            """
            INSERT INTO heldout_episodes (
                evaluation_id, freeze_id, source_experiment_id, episode_index, seed,
                total_reward, success, crashed, steps, terminated, truncated,
                elapsed_seconds, metrics_json, initial_state_json, replay_path, error, created_at
            ) VALUES (?, 'frz_1', 'exp_demo', ?, ?, ?, ?, ?, 10, 1, ?, 0.1, '{}', '{}', ?, NULL, 't')
            """,
            ("hev_1", idx, seed, reward, success, crashed, truncated, replay),
        )
    con.commit()
    con.close()

    summaries = load_heldout_summaries(database)
    assert len(summaries) == 1
    assert summaries[0].episode_count == 2
    assert summaries[0].landing_rate == 0.5
    assert summaries[0].timeout_rate == 0.5
    assert summaries[0].crash_rate == 0.0
    assert abs(summaries[0].mean_reward - 2.5) < 1e-9
    assert summaries[0].feedback_condition == "numerical_reward"

    result = write_report(load_logs(database), tmp_path / "report")
    text = result.markdown_path.read_text(encoding="utf-8")
    assert "## Sealed held-out evaluations" in text
    assert "hev_1" in text
    assert "exp_demo" in text
    assert "numerical_reward" in text
    assert "ApolloLander" in text
    assert "runs/flights/a.flight.json" in text


def test_report_without_heldout_tables_still_mentions_section(tmp_path: Path) -> None:
    database = tmp_path / "empty.sqlite"
    connection = connect_memory()
    write_database(database, connection)
    connection.close()
    text = write_report(load_logs(database), tmp_path / "report").markdown_path.read_text(
        encoding="utf-8"
    )
    assert "## Sealed held-out evaluations" in text
    assert "No `heldout_evaluations`" in text
