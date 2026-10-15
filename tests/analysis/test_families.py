from pathlib import Path

import pytest

from rewardbench.analysis.environments import APOLLO_LANDER, GYMNASIUM, environment_family
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.plots import draw_reward_vs_revision
from rewardbench.analysis.report import write_report
from rewardbench.analysis.sessions import experiment_rollups, session_summaries, summarize_groups
from fixtures import (
    connect_memory,
    insert_attempt,
    insert_episode,
    insert_experiment,
    insert_session,
    write_database,
)


def test_apollo_is_not_classified_as_gymnasium() -> None:
    assert environment_family("LunarLander-v3") == GYMNASIUM
    assert environment_family("Gymnasium/LunarLander-v3") == GYMNASIUM
    assert environment_family("ApolloLander-v1") == APOLLO_LANDER
    assert environment_family("apollo_lander") == APOLLO_LANDER
    assert environment_family("ApolloLander-Gymnasium-bridge") == APOLLO_LANDER
    assert environment_family("Minecraft-civilization") == "Minecraft-civilization"


def _scored(connection, experiment_id: str, session_id: str, environment_id: str, reward: float) -> None:
    insert_experiment(
        connection,
        experiment_id=experiment_id,
        model_id="model-a",
        environment_id=environment_id,
        synthetic=True,
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
        reward=reward,
        success=False,
        crashed=False,
    )


def test_families_are_not_pooled_and_resumes_are_one_experiment(tmp_path: Path) -> None:
    connection = connect_memory()
    _scored(connection, "exp-lunar-1", "ses-lunar-1", "LunarLander-v3", 1.0)
    _scored(connection, "exp-lunar-2", "ses-lunar-2", "LunarLander-v3", 3.0)
    _scored(connection, "exp-apollo", "ses-apollo", "ApolloLander-v1", 100.0)
    insert_session(connection, session_id="ses-lunar-1b", experiment_id="exp-lunar-1")
    insert_episode(
        connection,
        experiment_id="exp-lunar-1",
        session_id="ses-lunar-1b",
        revision_index=1,
        episode_index=1,
        seed=2,
        reward=5.0,
        success=False,
        crashed=False,
    )
    database = tmp_path / "families.sqlite"
    write_database(database, connection)
    connection.close()
    summaries = session_summaries(load_logs(database))
    groups = summarize_groups(summaries)
    assert {group.environment_id for group in groups} == {"LunarLander-v3", "ApolloLander-v1"}
    lunar = next(group for group in groups if group.environment_id == "LunarLander-v3")
    apollo = next(group for group in groups if group.environment_id == "ApolloLander-v1")
    assert lunar.n_sessions == 3
    assert lunar.n_experiments == 2
    assert apollo.n_sessions == 1
    assert apollo.initial_reward.point == pytest.approx(100.0)
    rollups = experiment_rollups(summaries)
    lunar_rollups = [row for row in rollups if row.environment_id == "LunarLander-v3"]
    assert len(lunar_rollups) == 2
    continued = next(row for row in lunar_rollups if row.experiment_id == "exp-lunar-1")
    assert continued.final_mean_reward == pytest.approx(5.0)
    replicated = summarize_groups(lunar_rollups)
    assert replicated[0].n_sessions == 2
    assert replicated[0].n_experiments == 2
    assert replicated[0].improvement.defined is False or replicated[0].initial_reward.defined

    figure = draw_reward_vs_revision(
        [row for row in summaries if row.environment_id == "ApolloLander-v1"]
    )
    assert figure.axes[0].get_title().startswith("ApolloLander:")
    figure.clf()

    report = write_report(load_logs(database), tmp_path / "report").markdown_path.read_text(encoding="utf-8")
    assert "### Gymnasium LunarLander" in report
    assert "### ApolloLander" in report
    assert report.index("### Gymnasium LunarLander") != report.index("### ApolloLander")
    assert "not pooled" in report
