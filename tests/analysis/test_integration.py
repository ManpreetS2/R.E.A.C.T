"""Integration through the real runner and SQLite log.

Most tests use stand-in models and environments. They do not call a paid API.
``test_mock_model_completes_an_apollolander_episode`` drives the real
ApolloLander adapter with a scripted controller. That flight is not evidence
that a language model adapted.
"""

from __future__ import annotations

import importlib
import importlib.util
import shutil
from pathlib import Path

import pytest

from rewardbench.analysis.diagnostics import seed_leakage
from rewardbench.analysis.environments import APOLLO_LANDER, GYMNASIUM, environment_family
from rewardbench.analysis.load import load_logs
from rewardbench.analysis.plots import draw_reward_vs_revision
from rewardbench.analysis.report import write_report
from rewardbench.analysis.sessions import session_summaries
from rewardbench.contracts import ConfigError, FeedbackCondition, Split
from rewardbench.core.runner import ExperimentRunner
from rewardbench.environments.apollolander import ApolloLanderAdapter, constant_controller
from rewardbench.storage import SqliteStore

_FAKES_PATH = Path(__file__).resolve().parents[1] / "core" / "fakes.py"


def _fakes():
    spec = importlib.util.spec_from_file_location("rewardbench_core_fakes", _FAKES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {_FAKES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FailFirstEpisode:
    """Stand-in adapter that fails the first episode and delegates the rest."""

    def __init__(self, inner) -> None:
        self.inner = inner

    def describe(self):
        return self.inner.describe()

    def validate_policy(self, parameters):
        return self.inner.validate_policy(parameters)

    def run_episode(self, policy, *, seed, episode_index, revision_index, max_steps=None):
        if revision_index == 0 and episode_index == 0:
            raise RuntimeError("stand-in episode failed before a reward was produced")
        return self.inner.run_episode(
            policy,
            seed=seed,
            episode_index=episode_index,
            revision_index=revision_index,
            max_steps=max_steps,
        )


def test_mock_model_revises_from_stored_rewards(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    config = fakes.make_config(
        experiment_name="integration-numerical",
        num_revisions=2,
        episodes_per_revision=1,
        database_path=str(database),
    )
    model = fakes.FakeModel(
        [fakes.proposal({"gain": 1}), fakes.proposal({"gain": 3})]
    )
    env = fakes.FakeEnv()
    store = SqliteStore(database)
    summary = ExperimentRunner(config, model, env, store).run()
    assert summary.status.value == "completed"
    assert len(model.requests) == 2
    assert model.requests[0].history == ()
    feedback = model.requests[1].history[0].feedback
    assert feedback is not None
    assert len(feedback) == 1
    stored = store.fetch_episodes(summary.experiment_id)
    assert stored[0].total_reward == pytest.approx(feedback[0].total_reward)
    assert [attempt.revision_index for attempt in store.fetch_attempts(summary.experiment_id)] == [0, 1]
    bundle = load_logs(database)
    assert bundle.synthetic is False
    assert environment_family(bundle.episodes[0].environment_id) == GYMNASIUM
    store.close()


def test_no_feedback_hides_rewards_that_are_still_stored(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    config = fakes.make_config(
        experiment_name="integration-no-feedback",
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        num_revisions=2,
        episodes_per_revision=1,
        database_path=str(database),
    )
    model = fakes.FakeModel(
        [fakes.proposal({"gain": 1}), fakes.proposal({"gain": 2})]
    )
    store = SqliteStore(database)
    summary = ExperimentRunner(config, model, fakes.FakeEnv(), store).run()
    assert model.requests[1].history[0].feedback is None
    episodes = store.fetch_episodes(summary.experiment_id)
    assert episodes[0].total_reward is not None
    assert load_logs(database).episodes[0].total_reward == pytest.approx(episodes[0].total_reward)
    store.close()


def test_held_out_episodes_stay_out_of_development(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    store = SqliteStore(database)
    development = fakes.make_config(
        experiment_name="integration-development",
        split=Split.DEVELOPMENT,
        num_revisions=1,
        episodes_per_revision=2,
        database_path=str(database),
    )
    held_out = fakes.make_config(
        experiment_name="integration-held-out",
        split=Split.HELD_OUT,
        num_revisions=1,
        episodes_per_revision=2,
        database_path=str(database),
    )
    dev_env = fakes.FakeEnv()
    hold_env = fakes.FakeEnv()
    dev_summary = ExperimentRunner(
        development, fakes.FakeModel([fakes.proposal({"gain": 1})]), dev_env, store
    ).run()
    hold_model = fakes.FakeModel([fakes.proposal({"gain": 1})])
    with pytest.raises(ConfigError, match="split=development"):
        ExperimentRunner(held_out, hold_model, hold_env, store)
    assert not hold_model.requests
    dev_seeds = {episode.seed for episode in store.fetch_episodes(dev_summary.experiment_id)}
    assert dev_seeds.isdisjoint(development.held_out_seeds)
    assert {row.split for row in load_logs(database).episodes} == {"development"}
    assert seed_leakage(load_logs(database)) == []
    store.close()


def test_resume_does_not_duplicate_completed_attempts(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    config = fakes.make_config(
        experiment_name="integration-resume",
        num_revisions=2,
        episodes_per_revision=1,
        database_path=str(database),
    )
    env = fakes.FakeEnv()
    store = SqliteStore(database)
    first = ExperimentRunner(
        config,
        fakes.FakeModel([fakes.proposal({"gain": 1}), KeyboardInterrupt()]),
        env,
        store,
    )
    with pytest.raises(KeyboardInterrupt):
        first.run()
    before = store.fetch_attempts(first.experiment_id)
    assert [row.revision_index for row in before] == [0]
    ExperimentRunner(
        config,
        fakes.FakeModel([fakes.proposal({"gain": 4})]),
        env,
        store,
    ).run()
    after = store.fetch_attempts(first.experiment_id)
    revision_zero = [row for row in after if row.revision_index == 0]
    assert len(revision_zero) == 1
    assert revision_zero[0].call_index == before[0].call_index
    assert [row.revision_index for row in after] == [0, 1]
    store.close()


def test_failed_episode_is_stored_and_omitted_from_the_chart(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    config = fakes.make_config(
        experiment_name="integration-failure",
        num_revisions=1,
        episodes_per_revision=2,
        database_path=str(database),
    )
    store = SqliteStore(database)
    summary = ExperimentRunner(
        config,
        fakes.FakeModel([fakes.proposal({"gain": 2})]),
        _FailFirstEpisode(fakes.FakeEnv()),
        store,
    ).run()
    stored = store.fetch_episodes(summary.experiment_id)
    failed = [row for row in stored if row.error]
    scored = [row for row in stored if row.error is None]
    assert len(failed) == 1
    assert failed[0].total_reward is None
    assert len(scored) == 1
    bundle = load_logs(database)
    assert bundle.synthetic is False
    summary_row = session_summaries(bundle)[0]
    assert summary_row.n_episodes == 2
    assert summary_row.n_scored_episodes == 1
    assert summary_row.reward_by_revision[0][1] == pytest.approx(scored[0].total_reward)
    figure = draw_reward_vs_revision(session_summaries(bundle))
    plotted = figure.axes[0].lines[0].get_ydata()
    assert plotted[0] == pytest.approx(scored[0].total_reward)
    figure.clf()
    report = write_report(bundle, tmp_path / "report").markdown_path.read_text(encoding="utf-8")
    assert "Gymnasium LunarLander" in report
    assert "Stored error rows: 1." in report
    store.close()


def test_gymnasium_and_apollo_reports_stay_separate(tmp_path: Path) -> None:
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    store = SqliteStore(database)
    for name, environment_id in (
        ("integration-gym", "LunarLander-v3"),
        ("integration-apollo", "ApolloLander-v1"),
    ):
        config = fakes.make_config(
            experiment_name=name,
            environment_id=environment_id,
            num_revisions=1,
            episodes_per_revision=1,
            database_path=str(database),
        )
        ExperimentRunner(
            config,
            fakes.FakeModel([fakes.proposal({"gain": 1})]),
            fakes.FakeEnv(environment_id=environment_id),
            store,
        ).run()
    bundle = load_logs(database)
    families = {environment_family(row.environment_id) for row in bundle.episodes}
    assert families == {GYMNASIUM, APOLLO_LANDER}
    report = write_report(bundle, tmp_path / "report").markdown_path.read_text(encoding="utf-8")
    assert "### Gymnasium LunarLander" in report
    assert "### ApolloLander" in report
    assert "not pooled" in report
    store.close()


def test_mock_model_completes_an_apollolander_episode(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("ApolloLander physics runs in Node")
    fakes = _fakes()
    database = tmp_path / "rewardbench.sqlite"
    controller = constant_controller(0, -90)
    config = fakes.make_config(
        experiment_name="integration-apollolander",
        environment_id="apollolander",
        num_revisions=2,
        episodes_per_revision=1,
        database_path=str(database),
        max_episode_steps=8000,
    )
    model = fakes.FakeModel([fakes.proposal(controller), fakes.proposal(controller)])
    store = SqliteStore(database)
    summary = ExperimentRunner(config, model, ApolloLanderAdapter(), store).run()
    assert summary.status.value == "completed"
    assert len(model.requests) == 2
    stored = store.fetch_episodes(summary.experiment_id)
    assert len(stored) == 2
    assert all(row.total_reward is not None for row in stored)
    feedback = model.requests[1].history[0].feedback
    assert feedback is not None
    assert stored[0].total_reward == pytest.approx(feedback[0].total_reward)
    bundle = load_logs(database)
    assert bundle.synthetic is False
    assert {environment_family(row.environment_id) for row in bundle.episodes} == {APOLLO_LANDER}
    report = write_report(bundle, tmp_path / "report").markdown_path.read_text(encoding="utf-8")
    assert "### ApolloLander" in report
    assert "### Gymnasium LunarLander" not in report
    store.close()
