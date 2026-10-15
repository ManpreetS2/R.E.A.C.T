from pathlib import Path

import pytest

from rewardbench.analysis.load import load_logs
from rewardbench.analysis.schema import LogRejected
from rewardbench.analysis.sessions import session_summaries
from fixtures import (
    connect_memory,
    insert_attempt,
    insert_episode,
    insert_experiment,
    insert_session,
    write_database,
)


def _simple_log(path: Path, *, cost: float = 2.0, valid: bool = True) -> None:
    connection = connect_memory()
    insert_experiment(
        connection,
        experiment_id="exp-1",
        model_id="model-a",
        synthetic=False,
    )
    insert_session(connection, session_id="ses-1", experiment_id="exp-1")
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        cost=cost,
        valid=valid,
        validation_error=None if valid else "bad controller",
    )
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=1,
        call_index=0,
        cost=cost,
        valid=True,
    )
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=-10.0,
        success=False,
        crashed=False,
    )
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=1,
        episode_index=0,
        seed=2,
        reward=10.0,
        success=True,
        crashed=False,
    )
    write_database(path, connection)
    connection.close()


def test_loader_reads_schema_version_one(tmp_path: Path) -> None:
    database = tmp_path / "run.sqlite"
    _simple_log(database)
    bundle = load_logs(database)
    assert bundle.schema_version == 1
    assert bundle.sha256
    assert len(bundle.episodes) == 2
    assert bundle.episodes[0].model_id == "model-a"
    assert bundle.episodes[0].validation_status == "preliminary"
    assert bundle.synthetic is False


def test_session_improvement_and_zero_cost(tmp_path: Path) -> None:
    database = tmp_path / "run.sqlite"
    _simple_log(database, cost=2.0)
    summary = session_summaries(load_logs(database))[0]
    assert summary.initial_mean_reward == pytest.approx(-10.0)
    assert summary.final_mean_reward == pytest.approx(10.0)
    assert summary.improvement == pytest.approx(20.0)
    assert summary.improvement_per_dollar == pytest.approx(20.0 / 4.0)

    free = tmp_path / "free.sqlite"
    _simple_log(free, cost=0.0)
    free_summary = session_summaries(load_logs(free))[0]
    assert free_summary.total_cost_usd == pytest.approx(0.0)
    assert free_summary.improvement_per_dollar is None


def test_invalid_selected_attempt_is_counted_separately_from_retries(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp-1", model_id="model-a", synthetic=False)
    insert_session(connection, session_id="ses-1", experiment_id="exp-1")
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        call_index=0,
        selected=False,
        valid=False,
        validation_error="retry",
        cost=0.1,
    )
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        call_index=1,
        selected=True,
        valid=False,
        validation_error="rejected",
        cost=0.2,
    )
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=1,
        selected=True,
        valid=True,
        cost=0.2,
    )
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=1,
        episode_index=0,
        seed=1,
        reward=1.0,
        success=False,
        crashed=True,
    )
    database = tmp_path / "invalid.sqlite"
    write_database(database, connection)
    connection.close()
    summary = session_summaries(load_logs(database))[0]
    assert summary.n_selected_attempts == 2
    assert summary.n_invalid_selected == 1
    assert summary.invalid_rate == pytest.approx(0.5)
    assert summary.crash_rate == pytest.approx(1.0)
    assert summary.total_cost_usd == pytest.approx(0.5)


def test_success_and_crash_row_is_excluded(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp-1", model_id="model-a", synthetic=False)
    insert_session(connection, session_id="ses-1", experiment_id="exp-1")
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=1.0,
        success=True,
        crashed=True,
    )
    database = tmp_path / "bad.sqlite"
    write_database(database, connection)
    connection.close()
    bundle = load_logs(database)
    assert bundle.episodes == []
    assert any(issue.code == "success_and_crash" for issue in bundle.issues)


def test_duplicate_episode_is_excluded() -> None:
    from rewardbench.analysis.schema import EpisodeObservation, LogBundle
    from rewardbench.analysis.validate import validate_bundle

    episode = EpisodeObservation(
        experiment_id="exp-1",
        session_id="ses-1",
        environment_id="LunarLander-v3",
        provider="fixture-provider",
        model_id="model-a",
        feedback_condition="numerical_reward",
        split="development",
        experiment_seed=0,
        experiment_status="completed",
        revision_index=0,
        episode_index=0,
        episode_seed=1,
        total_reward=1.0,
        success=False,
        crashed=False,
        steps=10,
        elapsed_seconds=1.0,
        error=None,
        validation_status="preliminary",
        synthetic=False,
    )
    bundle = validate_bundle(
        LogBundle(
            episodes=[episode, episode],
            attempts=[],
            errors=[],
            issues=[],
            source=Path("memory.jsonl"),
            sha256="0",
            schema_version=1,
            source_format="jsonl",
        )
    )
    assert len(bundle.episodes) == 1
    assert any(issue.code == "duplicate_episode" for issue in bundle.issues)


def test_mixed_synthetic_rows_are_rejected(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(
        connection,
        experiment_id="exp-real",
        model_id="model-a",
        synthetic=False,
    )
    insert_experiment(
        connection,
        experiment_id="exp-fake",
        model_id="model-b",
        synthetic=True,
    )
    insert_session(connection, session_id="ses-real", experiment_id="exp-real")
    insert_session(connection, session_id="ses-fake", experiment_id="exp-fake")
    insert_episode(
        connection,
        experiment_id="exp-real",
        session_id="ses-real",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=1.0,
        success=False,
        crashed=False,
    )
    insert_episode(
        connection,
        experiment_id="exp-fake",
        session_id="ses-fake",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=1.0,
        success=False,
        crashed=False,
    )
    database = tmp_path / "mixed.sqlite"
    write_database(database, connection)
    connection.close()
    with pytest.raises(LogRejected):
        load_logs(database)


def test_missing_tables_raise_schema_error(tmp_path: Path) -> None:
    from rewardbench.analysis.schema import SchemaError

    database = tmp_path / "empty.sqlite"
    connection = __import__("sqlite3").connect(database)
    connection.execute("CREATE TABLE notes (id INTEGER)")
    connection.commit()
    connection.close()
    with pytest.raises(SchemaError):
        load_logs(database)
