"""Offline multi-revision loop through real ApolloLander physics.

These checks prove the ExperimentRunner can revise controllers against the
vendored ApolloLander simulator, store numerical rewards in SQLite, and pass
those scores into the next ModelRequest. A scripted model that reacts to
feedback only validates the experiment machinery. It is not evidence of LLM
learning.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Mapping

import pytest

from rewardbench.contracts import (
    BudgetLimits,
    CandidatePolicy,
    ExperimentStatus,
    FeedbackCondition,
    ModelResponse,
)
from rewardbench.core.ids import experiment_id
from rewardbench.core.runner import ExperimentRunner
from rewardbench.environments.apollolander import ApolloLanderAdapter, constant_controller
from rewardbench.storage import SqliteStore

from fakes import FakeModel, make_config, proposal

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")

WEAK = constant_controller(0.0, -90)
REVISED = constant_controller(1.0, 0)
INVALID = {
    "schema": "rewardbench.apollolander.controller.v1",
    "policy": "constant",
    "thrust": 2.0,
    "rotation": 0,
}


def _apollo_config(tmp_path: Path, **overrides: Any):
    values: dict[str, Any] = {
        "experiment_name": "core-offline-apollo",
        "environment_id": "apollolander",
        "provider": "scripted",
        "model_id": "feedback-script",
        "num_revisions": 2,
        "episodes_per_revision": 1,
        "history_window": 4,
        "development_seeds": (0, 1, 2, 3),
        "held_out_seeds": (1_000_000, 1_000_001, 1_000_002, 1_000_003),
        "max_episode_steps": 120,
        "max_model_retries": 1,
        "database_path": str(tmp_path / "rewardbench.sqlite"),
        "budget": BudgetLimits(),
        "metadata": {"purpose": "offline_loop_proof"},
    }
    values.update(overrides)
    return make_config(**values)


def _feedback_script(request) -> ModelResponse:
    """Propose a weak controller first; revise only when numerical feedback arrives."""

    if not request.history:
        return proposal(WEAK, model_id="feedback-script", provider="scripted")
    prior = request.history[-1]
    if prior.feedback is None:
        return proposal(WEAK, model_id="feedback-script", provider="scripted")
    assert prior.feedback, "numerical condition must expose at least one scored episode"
    assert all(item.total_reward is not None for item in prior.feedback)
    return proposal(REVISED, model_id="feedback-script", provider="scripted")


class _FailFirstEpisode:
    def __init__(self, inner: ApolloLanderAdapter) -> None:
        self.inner = inner

    def describe(self):
        return self.inner.describe()

    def validate_policy(self, parameters: Mapping[str, Any]):
        return self.inner.validate_policy(parameters)

    def run_episode(
        self,
        policy: CandidatePolicy,
        *,
        seed: int,
        episode_index: int,
        revision_index: int,
        max_steps: int | None = None,
    ):
        if revision_index == 0 and episode_index == 0:
            raise RuntimeError("forced episode failure before a reward was produced")
        return self.inner.run_episode(
            policy,
            seed=seed,
            episode_index=episode_index,
            revision_index=revision_index,
            max_steps=max_steps,
        )


def test_multi_revision_numerical_feedback_changes_controller(tmp_path: Path) -> None:
    config = _apollo_config(tmp_path)
    model = FakeModel([_feedback_script, _feedback_script])
    store = SqliteStore(config.database_path)
    env = ApolloLanderAdapter(max_steps=120)
    summary = ExperimentRunner(config, model, env, store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.revisions_completed == 2
    assert summary.episodes_recorded == 2
    assert summary.invalid_revisions == 0
    assert len(model.requests) == 2

    first_request, second_request = model.requests
    assert first_request.history == ()
    assert first_request.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
    assert second_request.history
    feedback = second_request.history[0].feedback
    assert feedback is not None
    assert len(feedback) == 1

    attempts = [item for item in store.fetch_attempts(summary.experiment_id) if item.selected]
    assert [item.revision_index for item in attempts] == [0, 1]
    assert attempts[0].parameters == WEAK
    assert attempts[1].parameters == REVISED
    assert attempts[0].parameters != attempts[1].parameters

    episodes = store.fetch_episodes(summary.experiment_id)
    assert len(episodes) == 2
    assert episodes[0].total_reward == pytest.approx(feedback[0].total_reward)
    assert episodes[0].error is None
    assert episodes[1].error is None
    assert episodes[0].total_reward != pytest.approx(episodes[1].total_reward)
    assert "seed" not in feedback[0].__dict__
    scores = store.fetch_scores(summary.experiment_id)
    assert [row["score"] for row in scores] == [
        pytest.approx(episodes[0].total_reward),
        pytest.approx(episodes[1].total_reward),
    ]
    store.close()


def test_no_feedback_hides_outcomes_while_sqlite_keeps_rewards(tmp_path: Path) -> None:
    config = _apollo_config(
        tmp_path,
        experiment_name="core-offline-apollo-nofeedback",
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
    )
    model = FakeModel([_feedback_script, _feedback_script])
    store = SqliteStore(config.database_path)
    summary = ExperimentRunner(config, model, ApolloLanderAdapter(max_steps=120), store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert model.requests[1].history[0].feedback is None
    attempts = [item for item in store.fetch_attempts(summary.experiment_id) if item.selected]
    assert attempts[0].parameters == WEAK
    assert attempts[1].parameters == WEAK
    episodes = store.fetch_episodes(summary.experiment_id)
    assert len(episodes) == 2
    assert all(row.total_reward is not None for row in episodes)
    assert all(row.error is None for row in episodes)
    store.close()


def test_invalid_policy_skips_physics_and_records_attempt(tmp_path: Path) -> None:
    config = _apollo_config(
        tmp_path,
        experiment_name="core-offline-apollo-invalid",
        num_revisions=1,
        max_model_retries=0,
    )
    model = FakeModel([proposal(INVALID, model_id="feedback-script", provider="scripted")])
    env = ApolloLanderAdapter(max_steps=120)
    store = SqliteStore(config.database_path)
    summary = ExperimentRunner(config, model, env, store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.invalid_revisions == 1
    assert summary.episodes_recorded == 0
    attempts = store.fetch_attempts(summary.experiment_id)
    assert len(attempts) == 1
    assert attempts[0].selected is True
    assert attempts[0].valid is False
    assert store.fetch_episodes(summary.experiment_id) == []
    assert any(item.phase == "validation" for item in store.fetch_errors(summary.experiment_id))
    store.close()


def test_failed_episode_is_logged_and_omitted_from_feedback(tmp_path: Path) -> None:
    config = _apollo_config(
        tmp_path,
        experiment_name="core-offline-apollo-failed-episode",
        num_revisions=2,
        episodes_per_revision=2,
        max_episode_steps=80,
    )
    model = FakeModel([_feedback_script, _feedback_script])
    store = SqliteStore(config.database_path)
    env = _FailFirstEpisode(ApolloLanderAdapter(max_steps=80))
    summary = ExperimentRunner(config, model, env, store).run()

    assert summary.status is ExperimentStatus.COMPLETED
    episodes = store.fetch_episodes(summary.experiment_id)
    assert len(episodes) == 4
    failed = [row for row in episodes if row.error is not None]
    scored = [row for row in episodes if row.error is None]
    assert len(failed) == 1
    assert failed[0].revision_index == 0
    assert failed[0].episode_index == 0
    assert failed[0].total_reward is None
    assert len(scored) == 3

    feedback = model.requests[1].history[0].feedback
    assert feedback is not None
    assert len(feedback) == 1
    assert feedback[0].episode_index == 1
    assert feedback[0].total_reward == pytest.approx(
        next(row.total_reward for row in scored if row.revision_index == 0)
    )
    store.close()


def test_resume_reuses_selected_controller_and_skips_finished_episodes(tmp_path: Path) -> None:
    config = _apollo_config(tmp_path, experiment_name="core-offline-apollo-resume")
    store = SqliteStore(config.database_path)
    env = ApolloLanderAdapter(max_steps=120)
    interrupting = FakeModel(
        [
            proposal(WEAK, model_id="feedback-script", provider="scripted"),
            KeyboardInterrupt(),
        ]
    )
    with pytest.raises(KeyboardInterrupt):
        ExperimentRunner(config, interrupting, env, store).run()

    exp_id = experiment_id(config)
    assert store.get_experiment(exp_id).status is ExperimentStatus.INTERRUPTED
    assert len(store.fetch_attempts(exp_id)) == 1
    assert len(store.fetch_episodes(exp_id)) == 1

    resumed_model = FakeModel([_feedback_script])
    summary = ExperimentRunner(config, resumed_model, env, store).run()
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.experiment_id == exp_id
    assert len(resumed_model.requests) == 1
    assert resumed_model.requests[0].revision_index == 1
    attempts = [item for item in store.fetch_attempts(exp_id) if item.selected]
    assert [item.parameters for item in attempts] == [WEAK, REVISED]
    assert len(store.fetch_episodes(exp_id)) == 2

    again = ExperimentRunner(config, FakeModel([proposal(REVISED)]), env, store).run()
    assert again.status is ExperimentStatus.COMPLETED
    assert again.model_calls == 2
    store.close()


def test_spending_cap_stops_without_corrupting_completed_rows(tmp_path: Path) -> None:
    config = _apollo_config(
        tmp_path,
        experiment_name="core-offline-apollo-budget",
        num_revisions=2,
        episodes_per_revision=2,
        budget=BudgetLimits(max_episodes=1),
        max_episode_steps=80,
    )
    model = FakeModel([_feedback_script, _feedback_script])
    store = SqliteStore(config.database_path)
    summary = ExperimentRunner(config, model, ApolloLanderAdapter(max_steps=80), store).run()

    assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert summary.episodes_recorded == 1
    assert summary.model_calls == 1
    episodes = store.fetch_episodes(summary.experiment_id)
    assert len(episodes) == 1
    assert episodes[0].total_reward is not None
    attempts = store.fetch_attempts(summary.experiment_id)
    assert len(attempts) == 1
    assert attempts[0].valid is True
    assert store.fetch_errors(summary.experiment_id)[0].phase == "budget"

    # A second run must not invent new spend once the experiment is terminal.
    repeat = ExperimentRunner(
        config,
        FakeModel([proposal(REVISED)]),
        ApolloLanderAdapter(max_steps=80),
        store,
    ).run()
    assert repeat.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert len(store.fetch_attempts(summary.experiment_id)) == 1
    assert len(store.fetch_episodes(summary.experiment_id)) == 1
    store.close()
