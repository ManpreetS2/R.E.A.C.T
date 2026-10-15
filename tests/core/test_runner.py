from pathlib import Path

import pytest

from rewardbench.contracts import (
    BudgetExceeded,
    BudgetLimits,
    ExperimentStatus,
    FailurePolicy,
    FeedbackCondition,
    ModelClientError,
    ResumeError,
    Split,
)
from rewardbench.core.budget import BudgetLimiter
from rewardbench.core.runner import ExperimentRunner
from rewardbench.core.seeds import build_seed_schedule
from rewardbench.storage import SqliteStore

from fakes import FakeEnv, FakeModel, make_config, proposal


def _run(tmp_path: Path, config, model, env, **kwargs):
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    runner = ExperimentRunner(config, model, env, store, **kwargs)
    summary = runner.run()
    return summary, store, runner


def test_numerical_feedback_is_shown_and_no_feedback_is_withheld(tmp_path: Path) -> None:
    model = FakeModel([proposal({"gain": 1}), proposal({"gain": 3})])
    env = FakeEnv()
    config = make_config(num_revisions=2, episodes_per_revision=1, history_window=4)
    summary, store, _runner = _run(tmp_path, config, model, env)
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.episodes_recorded == 2
    assert model.requests[0].history == ()
    assert model.requests[1].history[0].feedback is not None
    assert model.requests[1].history[0].feedback[0].total_reward == pytest.approx(
        store.fetch_episodes(summary.experiment_id)[0].total_reward
    )
    assert "seed" not in model.requests[1].history[0].feedback[0].__dict__
    hidden = FakeModel([proposal({"gain": 1}), proposal({"gain": 3})])
    hidden_config = make_config(
        num_revisions=2,
        episodes_per_revision=1,
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
    )
    hidden_summary, hidden_store, _runner = _run(tmp_path / "hidden", hidden_config, hidden, FakeEnv())
    assert hidden.requests[1].history[0].feedback is None
    assert hidden_store.fetch_episodes(hidden_summary.experiment_id)[0].total_reward is not None
    assert summary.total_tokens == 24
    assert summary.total_cost_usd == pytest.approx(0.02)
    store.close()
    hidden_store.close()


def test_invalid_controller_is_not_simulated(tmp_path: Path) -> None:
    env = FakeEnv()
    model = FakeModel([proposal({}), proposal({})])
    config = make_config(num_revisions=1, episodes_per_revision=2, max_model_retries=1)
    summary, store, _runner = _run(tmp_path, config, model, env)
    assert env.episodes == []
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.invalid_revisions == 1
    attempts = store.fetch_attempts(summary.experiment_id)
    assert [item.selected for item in attempts] == [False, True]
    assert store.fetch_episodes(summary.experiment_id) == []
    errors = store.fetch_errors(summary.experiment_id)
    assert any(item.phase == "validation" for item in errors)
    store.close()


def test_resume_does_not_repeat_the_model_call(tmp_path: Path) -> None:
    stopping = FakeModel([proposal({"gain": 2}), KeyboardInterrupt()])
    env = FakeEnv()
    config = make_config(num_revisions=2, episodes_per_revision=1)
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    runner = ExperimentRunner(config, stopping, env, store)
    with pytest.raises(KeyboardInterrupt):
        runner.run()
    assert store.get_experiment(runner.experiment_id).status is ExperimentStatus.INTERRUPTED
    assert len(store.fetch_episodes(runner.experiment_id)) == 1
    resumed_model = FakeModel([proposal({"gain": 4})])
    resumed = ExperimentRunner(config, resumed_model, env, store)
    summary = resumed.run()
    assert summary.status is ExperimentStatus.COMPLETED
    assert len(resumed_model.requests) == 1
    assert resumed_model.requests[0].revision_index == 1
    assert len(store.fetch_episodes(runner.experiment_id)) == 2
    again = ExperimentRunner(config, FakeModel([proposal({"gain": 9})]), env, store)
    repeat = again.run()
    assert repeat.status is ExperimentStatus.COMPLETED
    assert repeat.model_calls == 2
    store.close()


def test_episode_budget_stops_cleanly(tmp_path: Path) -> None:
    config = make_config(
        num_revisions=2,
        episodes_per_revision=2,
        budget=BudgetLimits(max_episodes=1),
    )
    summary, store, _runner = _run(
        tmp_path,
        config,
        FakeModel([proposal({"gain": 1}), proposal({"gain": 2})]),
        FakeEnv(),
    )
    assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert summary.episodes_recorded == 1
    assert summary.model_calls == 1
    assert store.fetch_errors(summary.experiment_id)[0].phase == "budget"
    store.close()


def test_global_budget_counts_new_spend_only(tmp_path: Path) -> None:
    clock = {"now": 0.0}
    global_budget = BudgetLimiter(BudgetLimits(max_cost_usd=0.015), clock=lambda: clock["now"])
    config = make_config(num_revisions=2, episodes_per_revision=1, budget=BudgetLimits())
    model = FakeModel(
        [
            proposal({"gain": 1}, estimated_cost_usd=0.01),
            proposal({"gain": 2}, estimated_cost_usd=0.01),
        ]
    )
    summary, store, _runner = _run(
        tmp_path,
        config,
        model,
        FakeEnv(),
        global_budget=global_budget,
    )
    assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert summary.model_calls == 2
    assert summary.episodes_recorded == 1
    assert global_budget.cost_usd == pytest.approx(0.02)
    assert global_budget.episodes == 1
    store.close()


def test_held_out_run_uses_only_held_out_seeds(tmp_path: Path) -> None:
    config = make_config(
        split=Split.HELD_OUT,
        num_revisions=1,
        episodes_per_revision=3,
        development_seeds=(1, 2, 3, 4),
        held_out_seeds=(101, 102, 103, 104),
    )
    env = FakeEnv()
    summary, store, _runner = _run(tmp_path, config, FakeModel([proposal({"gain": 1})]), env)
    seeds = [seed for _revision, _episode, seed in env.episodes]
    assert seeds
    assert set(seeds).isdisjoint(config.development_seeds)
    assert set(seeds) <= set(config.held_out_seeds)
    episodes = store.fetch_episodes(summary.experiment_id)
    assert [episode.seed for episode in episodes] == seeds
    store.close()


def test_environment_id_mismatch_raises(tmp_path: Path) -> None:
    config = make_config(num_revisions=1, episodes_per_revision=1)
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    runner = ExperimentRunner(config, FakeModel([proposal({"gain": 1})]), FakeEnv(environment_id="other"), store)
    from rewardbench.contracts import ConfigError

    with pytest.raises(ConfigError):
        runner.run()
    store.close()


def test_retryable_model_error_then_success(tmp_path: Path) -> None:
    model = FakeModel(
        [
            ModelClientError("timeout", retryable=True),
            proposal({"gain": 2}),
        ]
    )
    config = make_config(num_revisions=1, episodes_per_revision=1, max_model_retries=1)
    summary, store, _runner = _run(tmp_path, config, model, FakeEnv())
    assert summary.status is ExperimentStatus.COMPLETED
    attempts = store.fetch_attempts(summary.experiment_id)
    assert [(item.call_index, item.selected, item.valid) for item in attempts] == [
        (0, False, False),
        (1, True, True),
    ]
    assert summary.episodes_recorded == 1
    store.close()


def test_non_retryable_model_error_aborts(tmp_path: Path) -> None:
    model = FakeModel([ModelClientError("denied", retryable=False)])
    config = make_config(num_revisions=2, episodes_per_revision=1, max_model_retries=3)
    summary, store, _runner = _run(tmp_path, config, model, FakeEnv())
    assert summary.status is ExperimentStatus.FAILED
    assert summary.episodes_recorded == 0
    assert summary.model_calls == 1
    assert "denied" in (summary.error or "")
    store.close()


def test_episode_failure_can_skip_or_abort(tmp_path: Path) -> None:
    skip_config = make_config(num_revisions=1, episodes_per_revision=1, seed=3)
    failing_seed = build_seed_schedule(
        skip_config.seed,
        skip_config.development_seeds,
        skip_config.num_revisions,
        skip_config.episodes_per_revision,
    )[0][0]
    summary, store, _runner = _run(
        tmp_path / "skip",
        skip_config,
        FakeModel([proposal({"gain": 1})]),
        FakeEnv(fail_seeds={failing_seed}),
    )
    assert summary.status is ExperimentStatus.COMPLETED
    assert store.fetch_episodes(summary.experiment_id)[0].error
    store.close()

    abort_config = make_config(
        num_revisions=1,
        episodes_per_revision=1,
        seed=3,
        on_episode_failure=FailurePolicy.ABORT,
        experiment_name="abort-episode",
    )
    abort_summary, abort_store, _runner = _run(
        tmp_path / "abort",
        abort_config,
        FakeModel([proposal({"gain": 1})]),
        FakeEnv(fail_seeds={failing_seed}),
    )
    assert abort_summary.status is ExperimentStatus.FAILED
    assert abort_store.fetch_errors(abort_summary.experiment_id)[0].phase == "episode"
    abort_store.close()


def test_checkpoint_schedule_mismatch_refuses_resume(tmp_path: Path) -> None:
    config = make_config(num_revisions=2, episodes_per_revision=1)
    store = SqliteStore(tmp_path / "rewardbench.sqlite")
    model = FakeModel([proposal({"gain": 1}), KeyboardInterrupt()])
    runner = ExperimentRunner(config, model, FakeEnv(), store)
    with pytest.raises(KeyboardInterrupt):
        runner.run()
    checkpoint = store.load_checkpoint(runner.experiment_id)
    assert checkpoint is not None
    from rewardbench.contracts import Checkpoint

    store.save_checkpoint(
        Checkpoint(
            experiment_id=checkpoint.experiment_id,
            next_revision_index=checkpoint.next_revision_index,
            budget=checkpoint.budget,
            seed_schedule=((999,), (998,)),
            updated_at=checkpoint.updated_at,
        )
    )
    with pytest.raises(ResumeError, match="seed schedule"):
        ExperimentRunner(config, FakeModel([proposal({"gain": 1})]), FakeEnv(), store).run()
    store.close()


def test_revisions_and_episodes_stay_in_separate_tables(tmp_path: Path) -> None:
    summary, store, _runner = _run(
        tmp_path,
        make_config(num_revisions=1, episodes_per_revision=1),
        FakeModel([proposal({"gain": 5}, reasoning_tokens=6, total_tokens=18)]),
        FakeEnv(),
    )
    attempt = store.fetch_attempts(summary.experiment_id)[0]
    episode = store.fetch_episodes(summary.experiment_id)[0]
    assert attempt.revision_index == episode.revision_index
    assert attempt.reasoning_tokens == 6
    assert attempt.latency_seconds == pytest.approx(0.2)
    assert episode.seed not in attempt.parameters.values()
    assert store.fetch_scores(summary.experiment_id)[0]["score"] == pytest.approx(episode.total_reward)
    store.close()
