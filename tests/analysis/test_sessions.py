from pathlib import Path

import pytest

from rewardbench.analysis.diagnostics import fairness_notes, resume_notes, seed_leakage
from rewardbench.analysis.export import export_jsonl
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.sessions import session_summaries, summarize_groups, time_to_targets
from fixtures import (
    connect_memory,
    insert_attempt,
    insert_episode,
    insert_experiment,
    insert_session,
    write_database,
)


def test_group_intervals_need_two_sessions(tmp_path: Path) -> None:
    connection = connect_memory()
    for index in (1, 2):
        experiment_id = f"exp-{index}"
        session_id = f"ses-{index}"
        insert_experiment(
            connection,
            experiment_id=experiment_id,
            model_id="model-a",
            synthetic=False,
        )
        insert_session(connection, session_id=session_id, experiment_id=experiment_id)
        insert_attempt(
            connection,
            experiment_id=experiment_id,
            session_id=session_id,
            revision_index=0,
            cost=1.0,
        )
        insert_episode(
            connection,
            experiment_id=experiment_id,
            session_id=session_id,
            revision_index=0,
            episode_index=0,
            seed=1,
            reward=float(index),
            success=False,
            crashed=False,
        )
    database = tmp_path / "groups.sqlite"
    write_database(database, connection)
    connection.close()
    summaries = session_summaries(load_logs(database))
    estimate = summarize_groups(summaries)[0]
    assert estimate.n_sessions == 2
    assert estimate.initial_reward.point == pytest.approx(1.5)
    assert estimate.initial_reward.defined


def test_time_to_target_keeps_sessions_that_never_arrive(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp-1", model_id="model-a", synthetic=False)
    insert_session(connection, session_id="ses-1", experiment_id="exp-1")
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        latency=1.0,
        cost=1.0,
    )
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=0.0,
        success=False,
        crashed=False,
        elapsed=4.0,
    )
    database = tmp_path / "target.sqlite"
    write_database(database, connection)
    connection.close()
    summary = session_summaries(load_logs(database))[0]
    row = time_to_targets([summary], (200.0,))[0]
    assert row.reached is False
    assert row.seconds is None
    assert row.observed_seconds == pytest.approx(5.0)


def test_jsonl_round_trip(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp-1", model_id="model-a", synthetic=False)
    insert_session(connection, session_id="ses-1", experiment_id="exp-1")
    insert_attempt(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        cost=1.25,
    )
    insert_episode(
        connection,
        experiment_id="exp-1",
        session_id="ses-1",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=3.5,
        success=True,
        crashed=False,
    )
    database = tmp_path / "run.sqlite"
    write_database(database, connection)
    connection.close()
    exported = export_jsonl(load_logs(database), tmp_path / "run.jsonl")
    restored = load_logs(exported)
    assert restored.episodes[0].total_reward == pytest.approx(3.5)
    assert restored.attempts[0].estimated_cost_usd == pytest.approx(1.25)
    assert restored.episodes[0].success is True


def test_seed_leakage_and_resume_and_fairness(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(
        connection,
        experiment_id="exp-dev",
        model_id="model-a",
        split="development",
        synthetic=False,
        development_seeds=(1, 2),
        held_out_seeds=(7,),
    )
    insert_experiment(
        connection,
        experiment_id="exp-hold",
        model_id="model-a",
        split="held_out",
        synthetic=False,
        development_seeds=(1, 2),
        held_out_seeds=(7,),
    )
    insert_experiment(
        connection,
        experiment_id="exp-b",
        model_id="model-b",
        split="development",
        synthetic=False,
        development_seeds=(1, 2),
        held_out_seeds=(8,),
    )
    insert_session(connection, session_id="ses-dev", experiment_id="exp-dev")
    insert_session(connection, session_id="ses-dev-2", experiment_id="exp-dev")
    insert_session(connection, session_id="ses-hold", experiment_id="exp-hold")
    insert_session(connection, session_id="ses-b", experiment_id="exp-b")
    insert_episode(
        connection,
        experiment_id="exp-dev",
        session_id="ses-dev",
        revision_index=0,
        episode_index=0,
        seed=7,
        reward=1.0,
        success=False,
        crashed=False,
    )
    insert_episode(
        connection,
        experiment_id="exp-dev",
        session_id="ses-dev-2",
        revision_index=0,
        episode_index=1,
        seed=1,
        reward=2.0,
        success=False,
        crashed=False,
    )
    insert_episode(
        connection,
        experiment_id="exp-hold",
        session_id="ses-hold",
        revision_index=0,
        episode_index=0,
        seed=7,
        reward=1.0,
        success=False,
        crashed=False,
    )
    insert_attempt(
        connection,
        experiment_id="exp-dev",
        session_id="ses-dev",
        revision_index=0,
        cost=1.0,
        tokens=10,
    )
    insert_attempt(
        connection,
        experiment_id="exp-b",
        session_id="ses-b",
        revision_index=0,
        cost=5.0,
        tokens=100,
    )
    insert_episode(
        connection,
        experiment_id="exp-b",
        session_id="ses-b",
        revision_index=0,
        episode_index=0,
        seed=1,
        reward=1.0,
        success=False,
        crashed=False,
    )
    database = tmp_path / "seeds.sqlite"
    write_database(database, connection)
    connection.close()
    bundle = load_logs(database)
    findings = seed_leakage(bundle)
    assert any(finding.kind == "executed_development_seed_in_held_out_pool" for finding in findings)
    assert 7 in next(
        finding.seeds
        for finding in findings
        if finding.kind == "executed_development_seed_in_held_out_pool"
    )
    summaries = session_summaries(bundle)
    assert any("exp-dev" in note for note in resume_notes(summaries))
    notes = fairness_notes(
        [summary for summary in summaries if summary.split == "development"]
    )
    assert notes
    assert "model-a" in notes[0].message
    assert "model-b" in notes[0].message
    assert "better" not in notes[0].message
