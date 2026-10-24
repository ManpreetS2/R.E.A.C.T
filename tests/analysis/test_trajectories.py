"""Offline regressions for resumes and scientific report strata."""

import json
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import pytest

from fixtures import connect_memory, insert_attempt, insert_episode, insert_experiment, insert_session, write_database
from rewardbench.analysis.environments import config_label
from rewardbench.analysis.export import export_jsonl
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.plots import draw_landing_success_vs_attempt, draw_reward_vs_revision, draw_time_to_target
from rewardbench.analysis.report import _target_table, write_report
from rewardbench.analysis.sessions import experiment_rollups, session_summaries, summarize_groups, time_to_targets


def _episode(connection, session, revision, index, reward, success=True):
    insert_episode(connection, experiment_id="exp", session_id=session,
                   revision_index=revision, episode_index=index, seed=index + 1,
                   reward=reward, success=success, crashed=False, elapsed=2.0)


def test_resume_rebuilds_initial_and_final_rewards_and_all_costs(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp", model_id="model")
    for session, revision, reward in (("before", 0, 10.0), ("after", 1, 30.0)):
        insert_session(connection, experiment_id="exp", session_id=session)
        insert_attempt(connection, experiment_id="exp", session_id=session,
                       revision_index=revision, cost=1.0, tokens=100, latency=3.0)
        _episode(connection, session, revision, 0, reward)
    path = tmp_path / "resume.sqlite"
    write_database(path, connection)
    connection.close()
    summary, = experiment_rollups(session_summaries(load_logs(path)))
    assert summary.initial_mean_reward == 10.0
    assert summary.final_mean_reward == 30.0
    assert summary.improvement == 20.0
    assert summary.total_cost_usd == 2.0
    assert summary.total_tokens == 200
    assert summary.improvement_per_dollar == 10.0
    assert summary.n_episodes == 2
    assert summary.success_by_attempt == ((0, 1.0), (1, 1.0))
    assert time_to_targets([summary], (20.0,))[0].seconds == 10.0


def test_split_revision_uses_episode_weighting_and_respects_missing_outcomes(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp", model_id="model")
    for session in ("before", "after"):
        insert_session(connection, experiment_id="exp", session_id=session)
    _episode(connection, "before", 0, 0, 0.0, False)
    _episode(connection, "after", 0, 1, 30.0, True)
    _episode(connection, "after", 0, 2, 30.0, True)
    _episode(connection, "after", 1, 0, 50.0, None)
    _episode(connection, "after", 2, 0, 60.0, False)
    insert_attempt(connection, experiment_id="exp", session_id="before",
                   revision_index=0, selected=False, valid=False, latency=7.0, cost=2.0)
    insert_attempt(connection, experiment_id="exp", session_id="after",
                   revision_index=0, call_index=1, latency=3.0, cost=1.0)
    path = tmp_path / "split.sqlite"
    write_database(path, connection)
    connection.close()
    summary, = experiment_rollups(session_summaries(load_logs(path)))
    assert summary.reward_by_revision == ((0, 20.0), (1, 50.0), (2, 60.0))
    assert summary.improvement == 40.0
    assert summary.n_scored_episodes == 5
    assert summary.n_success_known == 4
    assert summary.success_rate == 0.5
    assert summary.success_by_attempt == ((0, 0.0), (1, 1.0), (2, 1.0), (4, 0.0))
    assert summary.n_selected_attempts == 1
    assert summary.invalid_rate == 0.0
    assert summary.total_cost_usd == 3.0
    assert summary.cumulative_seconds_by_revision == ((0, 16.0), (1, 18.0), (2, 20.0))
    assert time_to_targets([summary], (20.0,))[0].seconds == 16.0


def test_three_revisions_are_three_chronological_success_points(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp", model_id="model")
    insert_session(connection, experiment_id="exp", session_id="session")
    for revision in (2, 0, 1):  # Insertion order is deliberately scrambled.
        _episode(connection, "session", revision, 0, 10.0, revision != 0)
    path = tmp_path / "success.sqlite"
    write_database(path, connection)
    connection.close()
    summaries = session_summaries(load_logs(path))
    assert summaries[0].success_by_attempt == ((0, 0.0), (1, 1.0), (2, 1.0))
    figure = draw_landing_success_vs_attempt(summaries)
    assert list(figure.axes[0].lines[0].get_xdata()) == [0, 1, 2]
    assert list(figure.axes[0].lines[0].get_ydata()) == [0.0, 1.0, 1.0]
    plt.close(figure)


@pytest.mark.parametrize("field,value", [
    ("research_mode", False), ("start_schedule_version", "starts.v2"),
    ("vary_fuel", True), ("max_episode_steps", 500),
    ("environment_version", "sim.v2"),
])
def test_simulator_settings_survive_export_and_split_groups(tmp_path: Path, field, value) -> None:
    connection = connect_memory()
    baseline = {"research_mode": True, "start_schedule_version": "starts.v1",
                "vary_fuel": False, "max_episode_steps": 1000, "environment_version": "sim.v1"}
    for index in range(3):
        experiment = f"replica-{index}"
        insert_experiment(connection, experiment_id=experiment, model_id="model", seed=index)
        insert_session(connection, experiment_id=experiment, session_id=experiment)
        config = dict(baseline)
        if index == 2:
            config[field] = value
        maximum = config.pop("max_episode_steps")
        payload = {"max_episode_steps": maximum, "seed": index,
                   "metadata": {"synthetic": True, "adapter_kwargs": config}}
        connection.execute("UPDATE experiments SET config_json=? WHERE experiment_id=?",
                           (json.dumps(payload), experiment))
        insert_attempt(connection, experiment_id=experiment, session_id=experiment, revision_index=0)
        insert_episode(connection, experiment_id=experiment, session_id=experiment,
                       revision_index=0, episode_index=0, seed=1, reward=10.0,
                       success=True, crashed=False)
    path = tmp_path / "strata.sqlite"
    write_database(path, connection)
    connection.close()
    bundle = load_logs(path)
    restored = load_logs(export_jsonl(bundle, tmp_path / "strata.jsonl"))
    assert restored.episodes == bundle.episodes
    assert restored.attempts == bundle.attempts
    summaries = session_summaries(restored)
    groups = summarize_groups(summaries)
    assert sorted(row.n_sessions for row in groups) == [1, 2]
    assert sorted(row.n_experiments for row in groups) == [1, 2]
    figure = draw_reward_vs_revision(summaries)
    assert len(figure.axes[0].get_legend().get_texts()) == 2
    plt.close(figure)
    table = "\n".join(_target_table(summaries, (5.0,), "preliminary", 0.95))
    assert len([line for line in table.splitlines() if line.startswith("| 5 |")]) == 2
    for group in groups:
        assert config_label(group.environment_config) in table


def test_targets_separate_provider_and_environment_and_mock_is_explicit(tmp_path: Path) -> None:
    connection = connect_memory()
    insert_experiment(connection, experiment_id="exp", model_id="model", provider="mock")
    insert_session(connection, experiment_id="exp", session_id="session")
    _episode(connection, "session", 0, 0, 10.0)
    path = tmp_path / "mock.sqlite"
    write_database(path, connection)
    connection.close()
    bundle = load_logs(path)
    base, = session_summaries(bundle)
    rows = [base, replace(base, provider="other"), replace(base, environment_id="LunarLander-v4")]
    table = "\n".join(_target_table(rows, (5.0,), "preliminary", 0.95))
    assert len([line for line in table.splitlines() if line.startswith("| 5 |")]) == 3
    figure = draw_time_to_target(time_to_targets(rows, (5.0,)), target=5.0)
    assert len(figure.axes[0].get_yticklabels()) == 3
    plt.close(figure)
    report = write_report(bundle, tmp_path / "report").markdown_path.read_text()
    assert "scripted infrastructure checks, not LLM results" in report
    assert "mock (scripted infrastructure; not LLM)" in report
    assert "unrecorded settings are unknown" in report


def test_sealed_report_retains_provider_and_simulator_context(tmp_path: Path) -> None:
    import sqlite3

    from rewardbench.analysis.heldout import heldout_markdown, load_heldout_summaries

    path = tmp_path / "sealed.sqlite"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE frozen_controllers (
                freeze_id TEXT, feedback_condition TEXT, provider TEXT, model_id TEXT
            );
            CREATE TABLE heldout_evaluations (
                evaluation_id TEXT, freeze_id TEXT, source_experiment_id TEXT,
                controller_hash TEXT, environment_id TEXT, environment_version TEXT,
                start_schedule_version TEXT, vary_fuel INTEGER, max_episode_steps INTEGER,
                status TEXT, created_at TEXT
            );
            CREATE TABLE heldout_episodes (
                evaluation_id TEXT, episode_index INTEGER, total_reward REAL,
                success INTEGER, crashed INTEGER, truncated INTEGER, replay_path TEXT
            );
            INSERT INTO frozen_controllers VALUES ('freeze', 'numerical_reward', 'mock', 'scripted');
            INSERT INTO heldout_evaluations VALUES (
                'evaluation', 'freeze', 'exp', 'hash', 'ApolloLander-v1', 'sim.v1',
                'starts.v1', 1, 500, 'completed', '2026-01-01'
            );
        """)
    summaries = load_heldout_summaries(path)
    assert summaries[0].provider == "mock"
    assert summaries[0].model_id == "scripted"
    assert summaries[0].vary_fuel is True
    assert summaries[0].max_episode_steps == 500
    text = "\n".join(heldout_markdown(summaries))
    assert "scripted infrastructure checks, not LLM results" in text
    assert "vary_fuel `True`" in text
    assert "max_episode_steps `500`" in text
    assert "env `sim.v1`" in text


def test_legacy_rotating_and_matched_schedules_do_not_pool(tmp_path: Path) -> None:
    connection = connect_memory()
    for index, schedule in enumerate((None, 'matched-development.v2')):
        name = f'schedule-{index}'
        insert_experiment(connection, experiment_id=name, model_id='constant')
        insert_session(connection, experiment_id=name, session_id=name)
        payload = {'metadata': {'synthetic': True}, 'max_episode_steps': 100}
        if schedule is not None:
            payload['seed_schedule_version'] = schedule
        connection.execute('UPDATE experiments SET config_json=? WHERE experiment_id=?', (json.dumps(payload), name))
        for revision, reward in enumerate((0.0, 0.02 if index == 0 else 0.0)):
            insert_episode(connection, experiment_id=name, session_id=name, revision_index=revision,
                           episode_index=0, seed=1 if revision == 0 or index == 1 else 2,
                           reward=reward, success=False, crashed=False)
    path = tmp_path / 'schedules.sqlite'
    write_database(path, connection)
    connection.close()
    bundle = load_logs(path)
    restored = load_logs(export_jsonl(bundle, tmp_path / 'schedules.jsonl'))
    assert restored.episodes == bundle.episodes
    summaries = session_summaries(restored)
    groups = summarize_groups(summaries)
    assert len(groups) == 2
    assert {row.n_experiments for row in groups} == {1}
    assert {row.improvement.point for row in groups} == {0.0, 0.02}
    assert {json.loads(row.environment_config)['seed_schedule_version'] for row in groups} == {'unrecorded', 'matched-development.v2'}
    figure = draw_reward_vs_revision(summaries)
    assert len(figure.axes[0].get_legend().get_texts()) == 2
    plt.close(figure)
