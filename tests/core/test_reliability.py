import json
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path

import pytest

from rewardbench.contracts import BudgetLimits, ExperimentStatus, FeedbackCondition, Split
from rewardbench.core.budget import BudgetLimiter
from rewardbench.core.locking import ExperimentBusy, ExperimentRunLock
from rewardbench.core.runner import ExperimentRunner
from rewardbench.storage import SqliteStore

from fakes import FakeEnv, FakeModel, make_config, proposal


class _CountingModel:
    provider = "fake"
    model_id = "fake-1"

    def __init__(self, calls: list[str], cost: float) -> None:
        self.calls = calls
        self.cost = cost

    def propose(self, request):
        self.calls.append(request.experiment_id)
        time.sleep(0.2)
        return proposal({"gain": 1}, estimated_cost_usd=self.cost)


def test_overlapping_runs_cannot_both_pass_a_one_call_cap(tmp_path: Path) -> None:
    shared = BudgetLimiter(BudgetLimits(max_cost_usd=0.05))
    calls: list[str] = []
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def worker(name: str) -> None:
        try:
            barrier.wait(timeout=5)
            config = make_config(
                experiment_name=name,
                num_revisions=1,
                episodes_per_revision=1,
                budget=BudgetLimits(),
            )
            runner = ExperimentRunner(
                config,
                _CountingModel(calls, 0.05),
                FakeEnv(),
                SqliteStore(tmp_path / "rewardbench.sqlite"),
                global_budget=shared,
            )
            runner.run()
        except BaseException as exc:  # noqa: BLE001 - re-raised from the test thread
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("alpha", "beta")]
    for thread in threads:
        thread.start()
    for thread in threads:
        # Allow enough time for schema init + global budget reservation under load.
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert errors == []
    assert len(calls) == 1
    assert shared.cost_usd == pytest.approx(0.05)


def test_a_second_experiment_stops_before_spending_past_the_shared_cap(tmp_path: Path) -> None:
    shared = BudgetLimiter(BudgetLimits(max_cost_usd=0.02))
    database = tmp_path / "rewardbench.sqlite"
    first = FakeModel([proposal({"gain": 1}, estimated_cost_usd=0.02)])
    first_summary, first_store, _runner = _execute(
        database,
        make_config(experiment_name="first", num_revisions=1, episodes_per_revision=1),
        first,
        FakeEnv(),
        global_budget=shared,
    )
    assert first_summary.status is ExperimentStatus.COMPLETED
    second = FakeModel([proposal({"gain": 1}, estimated_cost_usd=0.02)])
    second_summary, second_store, _runner = _execute(
        database,
        make_config(experiment_name="second", num_revisions=1, episodes_per_revision=1),
        second,
        FakeEnv(),
        global_budget=shared,
    )
    assert second.requests == []
    assert second_summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert second_summary.model_calls == 0
    assert shared.cost_usd == pytest.approx(0.02)
    first_store.close()
    second_store.close()


def test_resume_with_a_fresh_limiter_counts_stored_spend(tmp_path: Path) -> None:
    database = tmp_path / "rewardbench.sqlite"
    config = make_config(num_revisions=2, episodes_per_revision=1, budget=BudgetLimits())
    spent = BudgetLimiter(BudgetLimits(max_cost_usd=1))
    stopping = FakeModel([proposal({"gain": 1}, estimated_cost_usd=0.01), KeyboardInterrupt()])
    store = SqliteStore(database)
    runner = ExperimentRunner(config, stopping, FakeEnv(), store, global_budget=spent)
    with pytest.raises(KeyboardInterrupt):
        runner.run()
    assert spent.cost_usd == pytest.approx(0.01)
    fresh = BudgetLimiter(BudgetLimits(max_cost_usd=0.01))
    resumed = FakeModel([proposal({"gain": 9}, estimated_cost_usd=0.01)])
    summary = ExperimentRunner(config, resumed, FakeEnv(), store, global_budget=fresh).run()
    assert resumed.requests == []
    assert summary.model_calls == 1
    assert summary.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert fresh.cost_usd == pytest.approx(0.01)
    assert spent.cost_usd == pytest.approx(0.01)
    store.close()


def test_same_limiter_is_not_charged_twice_on_resume(tmp_path: Path) -> None:
    database = tmp_path / "rewardbench.sqlite"
    config = make_config(num_revisions=2, episodes_per_revision=1, budget=BudgetLimits())
    shared = BudgetLimiter(BudgetLimits(max_cost_usd=1))
    store = SqliteStore(database)
    with pytest.raises(KeyboardInterrupt):
        ExperimentRunner(
            config,
            FakeModel([proposal({"gain": 1}, estimated_cost_usd=0.01), KeyboardInterrupt()]),
            FakeEnv(),
            store,
            global_budget=shared,
        ).run()
    resumed = FakeModel([proposal({"gain": 9}, estimated_cost_usd=0.01)])
    summary = ExperimentRunner(config, resumed, FakeEnv(), store, global_budget=shared).run()
    assert len(resumed.requests) == 1
    assert summary.status is ExperimentStatus.COMPLETED
    assert shared.cost_usd == pytest.approx(0.02)
    assert shared.model_calls == 2
    store.close()


def test_repeated_completed_run_does_not_call_the_model(tmp_path: Path) -> None:
    database = tmp_path / "rewardbench.sqlite"
    config = make_config(num_revisions=1, episodes_per_revision=1)
    first, store, _runner = _execute(database, config, FakeModel([proposal({"gain": 2})]), FakeEnv())
    assert first.status is ExperimentStatus.COMPLETED
    again = FakeModel([proposal({"gain": 8})])
    second = ExperimentRunner(config, again, FakeEnv(), store).run()
    assert again.requests == []
    assert second.model_calls == 1
    assert second.status is ExperimentStatus.COMPLETED
    store.close()


def test_local_budget_stop_does_not_resume_into_more_spend(tmp_path: Path) -> None:
    database = tmp_path / "rewardbench.sqlite"
    config = make_config(
        num_revisions=2,
        episodes_per_revision=1,
        budget=BudgetLimits(max_episodes=1),
    )
    _summary, store, _runner = _execute(
        database,
        config,
        FakeModel([proposal({"gain": 1}), proposal({"gain": 2})]),
        FakeEnv(),
    )
    resumed = FakeModel([proposal({"gain": 3})])
    second = ExperimentRunner(config, resumed, FakeEnv(), store).run()
    assert resumed.requests == []
    assert second.status is ExperimentStatus.BUDGET_EXHAUSTED
    assert second.episodes_recorded == 1
    store.close()


def test_paid_controller_is_still_simulated_after_the_dollar_cap_is_met(tmp_path: Path) -> None:
    shared = BudgetLimiter(BudgetLimits(max_cost_usd=0.02))
    summary, store, _runner = _execute(
        tmp_path / "rewardbench.sqlite",
        make_config(num_revisions=1, episodes_per_revision=1, budget=BudgetLimits()),
        FakeModel([proposal({"gain": 4}, estimated_cost_usd=0.02)]),
        FakeEnv(),
        global_budget=shared,
    )
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.episodes_recorded == 1
    assert summary.model_calls == 1
    store.close()


def test_partial_episode_resume_does_not_repeat_the_model_call(tmp_path: Path) -> None:
    seen = {"count": 0}

    def interrupt_second_episode() -> None:
        seen["count"] += 1
        if seen["count"] == 2:
            raise KeyboardInterrupt()

    database = tmp_path / "rewardbench.sqlite"
    config = make_config(num_revisions=1, episodes_per_revision=2)
    store = SqliteStore(database)
    first_model = FakeModel([proposal({"gain": 2})])
    with pytest.raises(KeyboardInterrupt):
        ExperimentRunner(config, first_model, FakeEnv(on_episode=interrupt_second_episode), store).run()
    assert len(first_model.requests) == 1
    assert len(store.fetch_episodes(store.get_experiment(first_model.requests[0].experiment_id).experiment_id)) == 1
    resumed = FakeModel([proposal({"gain": 9})])
    summary = ExperimentRunner(config, resumed, FakeEnv(), store).run()
    assert resumed.requests == []
    assert summary.status is ExperimentStatus.COMPLETED
    assert summary.episodes_recorded == 2
    assert summary.model_calls == 1
    store.close()


def test_concurrent_same_experiment_calls_the_model_once(tmp_path: Path) -> None:
    calls: list[int] = []
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    config = make_config(num_revisions=1, episodes_per_revision=1)
    database = tmp_path / "rewardbench.sqlite"

    class SlowModel:
        provider = "fake"
        model_id = "fake-1"

        def propose(self, request):
            calls.append(request.revision_index)
            time.sleep(0.2)
            return proposal({"gain": 1})

    def worker() -> None:
        try:
            barrier.wait(timeout=5)
            ExperimentRunner(config, SlowModel(), FakeEnv(), SqliteStore(database)).run()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert errors == []
    assert calls == [0]


def test_no_feedback_hides_rewards_and_held_out_results(tmp_path: Path) -> None:
    database = tmp_path / "rewardbench.sqlite"
    held_out = make_config(
        experiment_name="held-out-marker",
        split=Split.DEVELOPMENT,
        num_revisions=1,
        episodes_per_revision=1,
        development_seeds=(909090,),
        held_out_seeds=(101, 102, 103, 104),
        seed=4,
    )
    held_summary, store, _runner = _execute(
        database,
        held_out,
        FakeModel([proposal({"gain": 424242.5})]),
        FakeEnv(),
    )
    held_reward = store.fetch_episodes(held_summary.experiment_id)[0].total_reward
    # Synthetic legacy held-out row: adaptation on this split is now forbidden.
    store._conn.execute("UPDATE experiments SET split='held_out' WHERE experiment_id=?", (held_summary.experiment_id,))
    store._conn.commit()
    assert held_reward is not None
    assert held_reward > 400000

    dev = make_config(
        experiment_name="development-hidden",
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        num_revisions=2,
        episodes_per_revision=1,
        history_window=5,
    )
    env = FakeEnv()

    def poison() -> None:
        env.task_description = f"total_reward={held_reward} seed 909090 fuel_used=2.5"

    env.on_episode = poison
    model = FakeModel([proposal({"gain": 1}), proposal({"gain": 2})])
    summary = ExperimentRunner(dev, model, env, store).run()
    assert summary.status is ExperimentStatus.COMPLETED
    assert store.fetch_episodes(summary.experiment_id)[0].total_reward is not None
    second = model.requests[1]
    assert second.history[0].feedback is None
    payload = json.dumps(_plain(second), sort_keys=True)
    assert "total_reward" not in payload
    assert "fuel_used" not in payload
    assert "909090" not in payload
    assert str(held_reward) not in payload
    assert second.environment.task_description == "Land the vehicle."
    store.close()


def test_another_process_cannot_lock_a_running_experiment(tmp_path: Path) -> None:
    lock = ExperimentRunLock("exp_file", tmp_path)
    lock.acquire()
    try:
        root = Path(__file__).resolve().parents[2]
        code = (
            "from rewardbench.core.locking import ExperimentBusy, ExperimentRunLock\n"
            f"lock = ExperimentRunLock('exp_file', {str(tmp_path)!r})\n"
            "try:\n"
            "    lock.acquire(blocking=False)\n"
            "except ExperimentBusy:\n"
            "    raise SystemExit(0)\n"
            "raise SystemExit(1)\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            env={**__import__("os").environ, "PYTHONPATH": str(root / "src")},
        )
        assert completed.returncode == 0, completed.stderr
    finally:
        lock.release()


def _plain(value):
    if is_dataclass(value):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _execute(database: Path, config, model, env, **kwargs):
    store = SqliteStore(database)
    runner = ExperimentRunner(config, model, env, store, **kwargs)
    return runner.run(), store, runner
