"""Held-out freeze and evaluation tests.

Uses scripted offline development runs and real ApolloLander physics.
No model is called during held-out scoring.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from rewardbench.contracts import ConfigError, ExperimentStatus, FeedbackCondition
from rewardbench.core.heldout import (
    GuardedModelClient,
    controller_hash,
    evaluate_frozen_controller,
    freeze_controller_from_experiment,
    select_final_controller,
)
from rewardbench.core.history import HistoryBuilder, RevisionHistoryEntry
from rewardbench.core.ids import experiment_id
from rewardbench.core.isolation import model_history
from rewardbench.environments.apollolander import ENVIRONMENT_VERSION
from rewardbench.environments.apollolander.starts import derive_start
from rewardbench.heldout.cli import main as heldout_main
from rewardbench.run.cli import main as run_main
from rewardbench.run.factory import prepare_config
from rewardbench.storage import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
NUMERICAL = ROOT / "configs" / "apollolander_offline_development_numerical.yaml"
NOFEEDBACK = ROOT / "configs" / "apollolander_offline_development_nofeedback.yaml"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")


def _complete_development(tmp_path: Path, config_path: Path, name: str) -> tuple[str, Path]:
    database = tmp_path / f"{name}.sqlite"
    code = run_main(
        [
            "--config",
            str(config_path),
            "--mode",
            "mock",
            "--database",
            str(database),
        ]
    )
    assert code == 0
    config = prepare_config(config_path, database_path=database)
    return experiment_id(config), database


def test_selection_uses_last_valid_selected_not_best_reward() -> None:
    from rewardbench.contracts import StoredAttempt

    attempts = [
        StoredAttempt(
            experiment_id="exp",
            session_id="ses",
            revision_index=0,
            call_index=0,
            selected=True,
            parameters={"a": 1},
            raw_response="{}",
            valid=True,
            validation_error=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            total_tokens=0,
            latency_seconds=0.0,
            estimated_cost_usd=0.0,
            model_id="m",
            provider="mock",
            error=None,
            created_at="t",
            attempt_id=1,
        ),
        StoredAttempt(
            experiment_id="exp",
            session_id="ses",
            revision_index=1,
            call_index=0,
            selected=True,
            parameters={"a": 2},
            raw_response="{}",
            valid=True,
            validation_error=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            total_tokens=0,
            latency_seconds=0.0,
            estimated_cost_usd=0.0,
            model_id="m",
            provider="mock",
            error=None,
            created_at="t",
            attempt_id=2,
        ),
    ]
    chosen = select_final_controller(attempts)
    assert chosen.parameters == {"a": 2}
    assert chosen.revision_index == 1


def test_guarded_model_client_forbids_propose() -> None:
    with pytest.raises(ConfigError, match="forbids ModelClient.propose"):
        GuardedModelClient().propose(object())


def test_heldout_cli_freezes_and_scores_without_model_calls(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source_id, database = _complete_development(tmp_path, NUMERICAL, "numerical")
    code = heldout_main(
        [
            "--database",
            str(database),
            "--source-experiment-id",
            source_id,
            "--selection-rule",
            "last_valid_selected",
            "--max-episode-steps",
            "40",
        ]
    )
    captured = capsys.readouterr()
    assert code == 0, captured.stderr
    assert "no model calls" in captured.out
    assert "heldout_evaluation" in captured.out
    assert "status: completed" in captured.out

    store = SqliteStore(database)
    try:
        frozen_rows = store._conn.execute("SELECT * FROM frozen_controllers").fetchall()
        assert len(frozen_rows) == 1
        frozen = store.get_frozen_controller(frozen_rows[0]["freeze_id"])
        assert frozen is not None
        assert frozen.source_experiment_id == source_id
        assert frozen.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
        assert frozen.controller_hash == controller_hash(frozen.parameters)

        evals = store._conn.execute("SELECT * FROM heldout_evaluations").fetchall()
        assert len(evals) == 1
        evaluation_id = evals[0]["evaluation_id"]
        episodes = store.fetch_heldout_episodes(evaluation_id)
        assert len(episodes) == 8  # held_out_seeds length in offline config
        assert [row["seed"] for row in episodes] == list(
            prepare_config(NUMERICAL).held_out_seeds
        )
        for row in episodes:
            assert row["initial_state"]
            assert "x" in row["initial_state"]
            expected = derive_start(row["seed"], version="apollolander.starts.v1", vary_fuel=False)
            assert row["initial_state"]["x"] == pytest.approx(expected.x)
            assert row["total_reward"] is not None

        # Development history must not include held-out episode rows.
        assert store.fetch_episodes(source_id)
        assert all(ep.seed < 1_000_000 for ep in store.fetch_episodes(source_id))
    finally:
        store.close()


def test_idempotent_refusal_on_repeat(tmp_path: Path) -> None:
    source_id, database = _complete_development(tmp_path, NUMERICAL, "idem")
    assert (
        heldout_main(
            [
                "--database",
                str(database),
                "--source-experiment-id",
                source_id,
                "--max-episode-steps",
                "40",
            ]
        )
        == 0
    )
    assert (
        heldout_main(
            [
                "--database",
                str(database),
                "--source-experiment-id",
                source_id,
                "--max-episode-steps",
                "40",
            ]
        )
        == 2
    )


def test_numerical_and_nofeedback_share_identical_heldout_starts(tmp_path: Path) -> None:
    num_id, num_db = _complete_development(tmp_path, NUMERICAL, "pair-num")
    nofb_id, nofb_db = _complete_development(tmp_path, NOFEEDBACK, "pair-nofb")
    assert (
        heldout_main(
            ["--database", str(num_db), "--source-experiment-id", num_id, "--max-episode-steps", "40"]
        )
        == 0
    )
    assert (
        heldout_main(
            ["--database", str(nofb_db), "--source-experiment-id", nofb_id, "--max-episode-steps", "40"]
        )
        == 0
    )

    num_store = SqliteStore(num_db)
    nofb_store = SqliteStore(nofb_db)
    try:
        num_eval = num_store._conn.execute("SELECT evaluation_id FROM heldout_evaluations").fetchone()
        nofb_eval = nofb_store._conn.execute("SELECT evaluation_id FROM heldout_evaluations").fetchone()
        num_eps = num_store.fetch_heldout_episodes(num_eval["evaluation_id"])
        nofb_eps = nofb_store.fetch_heldout_episodes(nofb_eval["evaluation_id"])
        assert [row["seed"] for row in num_eps] == [row["seed"] for row in nofb_eps]
        assert [row["initial_state"] for row in num_eps] == [row["initial_state"] for row in nofb_eps]
        num_frozen = num_store.get_frozen_controller(
            num_store._conn.execute("SELECT freeze_id FROM frozen_controllers").fetchone()["freeze_id"]
        )
        nofb_frozen = nofb_store.get_frozen_controller(
            nofb_store._conn.execute("SELECT freeze_id FROM frozen_controllers").fetchone()["freeze_id"]
        )
        assert num_frozen.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
        assert nofb_frozen.feedback_condition is FeedbackCondition.NO_FEEDBACK
        # Controllers may differ across conditions; starts must not.
        assert num_id != nofb_id
    finally:
        num_store.close()
        nofb_store.close()


def test_incomplete_development_is_rejected(tmp_path: Path) -> None:
    database = tmp_path / "incomplete.sqlite"
    # Create a pending experiment row without completing revisions.
    from rewardbench.contracts import ExperimentRecord, Split
    from rewardbench import CONTRACT_VERSION, SCHEMA_VERSION
    from rewardbench.storage.sqlite import utc_now

    store = SqliteStore(database)
    store.initialize()
    store.create_experiment(
        ExperimentRecord(
            experiment_id="exp_incomplete_heldout_test",
            experiment_name="incomplete",
            environment_id="apollolander",
            provider="mock",
            model_id="scripted",
            feedback_condition=FeedbackCondition.NUMERICAL_REWARD,
            split=Split.DEVELOPMENT,
            seed=1,
            contract_version=CONTRACT_VERSION,
            config_json="{}",
            config_hash="abc",
            status=ExperimentStatus.RUNNING,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
    )
    store.close()
    assert (
        heldout_main(
            [
                "--database",
                str(database),
                "--source-experiment-id",
                "exp_incomplete_heldout_test",
            ]
        )
        == 2
    )


def test_heldout_results_do_not_enter_model_history(tmp_path: Path) -> None:
    source_id, database = _complete_development(tmp_path, NUMERICAL, "hist")
    assert (
        heldout_main(
            ["--database", str(database), "--source-experiment-id", source_id, "--max-episode-steps", "40"]
        )
        == 0
    )
    store = SqliteStore(database)
    try:
        # Only development episodes exist under the source experiment id.
        dev_episodes = store.fetch_episodes(source_id)
        held_eval = store._conn.execute("SELECT evaluation_id FROM heldout_evaluations").fetchone()
        held_episodes = store.fetch_heldout_episodes(held_eval["evaluation_id"])
        assert held_episodes
        assert {ep.seed for ep in dev_episodes}.isdisjoint({row["seed"] for row in held_episodes})

        builder = HistoryBuilder(4, FeedbackCondition.NUMERICAL_REWARD)
        entries = [
            RevisionHistoryEntry(
                revision_index=ep.revision_index,
                parameters={},
                valid=True,
                validation_error=None,
                episodes=(ep.as_result(),),
            )
            for ep in dev_episodes
        ]
        history = model_history(builder, entries, prepare_config(NUMERICAL).development_seeds)
        # Held-out seeds must never appear in model-facing history.
        for prior in history:
            if prior.feedback:
                for item in prior.feedback:
                    assert item.episode_index >= 0
        leaked = [row["seed"] for row in held_episodes if row["seed"] in prepare_config(NUMERICAL).development_seeds]
        assert leaked == []
    finally:
        store.close()


def test_source_config_flag_resolves_experiment_id(tmp_path: Path) -> None:
    _source_id, database = _complete_development(tmp_path, NUMERICAL, "cfgflag")
    code = heldout_main(
        [
            "--database",
            str(database),
            "--source-config",
            str(NUMERICAL),
            "--max-episode-steps",
            "40",
        ]
    )
    assert code == 0


def test_recorded_heldout_replays_link_to_real_files_without_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rewardbench.analysis.heldout import load_heldout_summaries
    from rewardbench.environments import make_environment
    from rewardbench.environments.apollolander import load_flight_record
    import rewardbench.run.cli as run_cli

    source_id, database = _complete_development(tmp_path, NUMERICAL, "replays")
    with SqliteStore(database) as store:
        attempts_before = store.fetch_attempts(source_id)
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("held-out evaluation attempted to construct a model")
    monkeypatch.setattr(run_cli, "build_model", forbidden)
    output = tmp_path / "heldout-flights"
    assert heldout_main([
        "--database", str(database), "--source-experiment-id", source_id,
        "--max-episode-steps", "40", "--record-dir", str(output),
    ]) == 0
    adapter = make_environment("ApolloLander", research_mode=True)
    with SqliteStore(database) as store:
        assert store.fetch_attempts(source_id) == attempts_before
        evaluation = store._conn.execute("SELECT * FROM heldout_evaluations").fetchone()
        episodes = store.fetch_heldout_episodes(evaluation["evaluation_id"])
        for episode in episodes:
            path = Path(episode["replay_path"])
            assert path.is_file()
            record = load_flight_record(path)
            assert record["split"] == "held_out"
            assert record["origin"] == "deterministic_mock"
            assert record["experiment_id"] == source_id
            assert record["episode_seed"] == episode["seed"]
            assert record["terminal"]["reward"] == episode["total_reward"]
            assert record["initial_state"] == episode["initial_state"]
            assert adapter.verify_flight_record(path)["matched"]
    summaries = load_heldout_summaries(database)
    assert len(summaries[0].replay_paths) == 8


def test_forged_freeze_and_execution_settings_are_rejected_before_flights(tmp_path: Path) -> None:
    from dataclasses import replace
    from rewardbench.environments import make_environment
    source_id, database = _complete_development(tmp_path, NUMERICAL, "binding")
    config = prepare_config(NUMERICAL)
    with SqliteStore(database) as store:
        frozen = freeze_controller_from_experiment(store, source_id)
        settings = dict(
            held_out_seeds=config.held_out_seeds, development_seeds=config.development_seeds,
            max_episode_steps=40, environment_version=ENVIRONMENT_VERSION,
        )
        adapter = make_environment("ApolloLander", research_mode=True)
        parameters = {**dict(frozen.parameters), "thrust": 0.9}
        forged = replace(frozen, parameters=parameters, controller_hash=controller_hash(parameters))
        with pytest.raises(ConfigError, match="persisted freeze"):
            evaluate_frozen_controller(store, forged, adapter, **settings)
        wrong_fuel = make_environment("ApolloLander", research_mode=True, vary_fuel=True)
        with pytest.raises(ConfigError, match="vary_fuel"):
            evaluate_frozen_controller(store, frozen, wrong_fuel, **settings)
        with pytest.raises(ConfigError, match="environment_version"):
            evaluate_frozen_controller(store, frozen, adapter, **{**settings, "environment_version": "invented"})
        assert store._conn.execute("SELECT count(*) FROM heldout_evaluations").fetchone()[0] == 0


@pytest.mark.parametrize("failure", ["error", "nan", "indexes"])
def test_heldout_invalid_results_fail_closed(tmp_path: Path, failure: str) -> None:
    from dataclasses import replace
    from rewardbench.contracts import EpisodeResult
    from rewardbench.environments import make_environment
    source_id, database = _complete_development(tmp_path, NUMERICAL, failure)
    config = prepare_config(NUMERICAL)
    adapter = make_environment("ApolloLander", research_mode=True)
    def invalid(policy: object, *, seed: int, episode_index: int, revision_index: int, **kwargs: object) -> EpisodeResult:
        result = EpisodeResult(
            revision_index=revision_index, episode_index=episode_index, seed=seed,
            total_reward=1.0, success=False, crashed=False, steps=1,
            terminated=False, truncated=True, elapsed_seconds=0.0,
        )
        if failure == "error":
            return replace(result, error="simulator failed")
        if failure == "nan":
            return replace(result, total_reward=float("nan"))
        return replace(result, revision_index=999)
    adapter.run_episode = invalid
    with SqliteStore(database) as store:
        frozen = freeze_controller_from_experiment(store, source_id)
        with pytest.raises(ConfigError):
            evaluate_frozen_controller(
                store, frozen, adapter, held_out_seeds=config.held_out_seeds,
                development_seeds=config.development_seeds, max_episode_steps=40,
                environment_version=ENVIRONMENT_VERSION,
            )
        row = store._conn.execute("SELECT * FROM heldout_evaluations").fetchone()
        assert row["status"] == "failed"
        assert row["completed_episodes"] == 0
        assert row["error"]
