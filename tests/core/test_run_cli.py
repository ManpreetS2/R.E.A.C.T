"""Tests for the rewardbench.run experiment launcher."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from rewardbench.config import load_config
from rewardbench.contracts import ConfigError, ExperimentStatus, FeedbackCondition
from rewardbench.core.ids import experiment_id
from rewardbench.core.seeds import build_seed_schedule
from rewardbench.run.cli import main
from rewardbench.run.factory import (
    adapter_kwargs_from_metadata,
    build_environment,
    build_model,
    prepare_config,
)
from rewardbench.run.mock_model import INITIAL_CONTROLLER, REVISED_CONTROLLER, ScriptedFeedbackModel
from rewardbench.storage import SqliteStore

ROOT = Path(__file__).resolve().parents[2]
NUMERICAL = ROOT / "configs" / "apollolander_offline_development_numerical.yaml"
NOFEEDBACK = ROOT / "configs" / "apollolander_offline_development_nofeedback.yaml"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")


def test_paired_offline_configs_match_except_feedback() -> None:
    numerical = load_config(NUMERICAL)
    withheld = load_config(NOFEEDBACK)
    assert numerical.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
    assert withheld.feedback_condition is FeedbackCondition.NO_FEEDBACK
    assert numerical.seed == withheld.seed
    assert numerical.num_revisions == withheld.num_revisions
    assert numerical.episodes_per_revision == withheld.episodes_per_revision
    assert numerical.history_window == withheld.history_window
    assert numerical.max_episode_steps == withheld.max_episode_steps
    assert numerical.development_seeds == withheld.development_seeds
    assert numerical.held_out_seeds == withheld.held_out_seeds
    assert numerical.metadata["adapter_kwargs"] == withheld.metadata["adapter_kwargs"]
    assert experiment_id(numerical) != experiment_id(withheld)
    schedule_a = build_seed_schedule(
        numerical.seed,
        numerical.development_seeds,
        numerical.num_revisions,
        numerical.episodes_per_revision,
    )
    schedule_b = build_seed_schedule(
        withheld.seed,
        withheld.development_seeds,
        withheld.num_revisions,
        withheld.episodes_per_revision,
    )
    assert schedule_a == schedule_b


def test_prepare_config_rejects_invalid_budget(tmp_path: Path) -> None:
    payload = yaml.safe_load(NUMERICAL.read_text(encoding="utf-8"))
    payload["budget"]["max_episodes"] = 0
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="positive"):
        prepare_config(path)


def test_prepare_config_rejects_bad_adapter_kwargs(tmp_path: Path) -> None:
    payload = yaml.safe_load(NUMERICAL.read_text(encoding="utf-8"))
    payload["metadata"]["adapter_kwargs"] = ["not", "a", "mapping"]
    path = tmp_path / "bad-kwargs.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="adapter_kwargs"):
        prepare_config(path)


def test_live_mode_is_disabled_without_api_calls() -> None:
    config = load_config(NUMERICAL)
    with pytest.raises(ConfigError, match="disabled"):
        build_model(config, mode="live")


def test_adapter_kwargs_reach_research_mode_on_apollo_adapter() -> None:
    config = load_config(NUMERICAL)
    kwargs = adapter_kwargs_from_metadata(config.metadata)
    assert kwargs["research_mode"] is True
    assert kwargs["max_steps"] == 120
    assert kwargs["start_schedule_version"] == "apollolander.starts.v1"
    env = build_environment(config)
    assert env.describe().environment_id == "apollolander"
    assert env.max_steps == 120
    assert env.research_mode is True
    assert env.start_schedule_version == "apollolander.starts.v1"
    env.close()


def test_unsupported_adapter_kwargs_fail_closed(tmp_path: Path) -> None:
    payload = yaml.safe_load(NUMERICAL.read_text(encoding="utf-8"))
    payload["metadata"]["adapter_kwargs"]["not_a_real_kwarg"] = True
    path = tmp_path / "bad-research.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config = prepare_config(path)
    with pytest.raises(ConfigError, match="does not accept metadata.adapter_kwargs"):
        build_environment(config)


def test_record_flights_override_does_not_change_experiment_id(tmp_path: Path) -> None:
    from rewardbench.run.cli import _flight_adapter_overrides

    database = tmp_path / "numerical.sqlite"
    config = prepare_config(NUMERICAL, database_path=database)
    before = experiment_id(config)
    overrides = _flight_adapter_overrides(config, experiment_id=before, database=database)
    assert overrides["experiment_id"] == before
    assert Path(overrides["record_dir"]).is_dir()
    assert overrides.get("record_video") is False
    env = build_environment(config, adapter_overrides=overrides)
    try:
        assert env.research_mode is True
        assert env.experiment_id == before
        assert env.record_dir == Path(overrides["record_dir"])
    finally:
        env.close()
    assert experiment_id(config) == before


def test_mock_cli_runs_numerical_and_nofeedback(tmp_path: Path) -> None:
    numerical_db = tmp_path / "numerical.sqlite"
    withheld_db = tmp_path / "nofeedback.sqlite"

    assert main(["--config", str(NUMERICAL), "--mode", "mock", "--database", str(numerical_db)]) == 0
    assert main(["--config", str(NOFEEDBACK), "--mode", "mock", "--database", str(withheld_db)]) == 0

    numerical_store = SqliteStore(numerical_db)
    withheld_store = SqliteStore(withheld_db)
    try:
        numerical_id = experiment_id(prepare_config(NUMERICAL, database_path=numerical_db))
        withheld_id = experiment_id(prepare_config(NOFEEDBACK, database_path=withheld_db))

        numerical_attempts = [row for row in numerical_store.fetch_attempts(numerical_id) if row.selected]
        withheld_attempts = [row for row in withheld_store.fetch_attempts(withheld_id) if row.selected]
        assert [row.parameters for row in numerical_attempts] == [INITIAL_CONTROLLER, REVISED_CONTROLLER]
        assert [row.parameters for row in withheld_attempts] == [INITIAL_CONTROLLER, INITIAL_CONTROLLER]

        numerical_episodes = numerical_store.fetch_episodes(numerical_id)
        withheld_episodes = withheld_store.fetch_episodes(withheld_id)
        assert len(numerical_episodes) == 2
        assert len(withheld_episodes) == 2
        assert all(row.total_reward is not None for row in numerical_episodes)
        assert all(row.total_reward is not None for row in withheld_episodes)
        assert numerical_episodes[0].total_reward != pytest.approx(numerical_episodes[1].total_reward)

        numerical_exp = numerical_store.get_experiment(numerical_id)
        withheld_exp = withheld_store.get_experiment(withheld_id)
        assert numerical_exp is not None and numerical_exp.status is ExperimentStatus.COMPLETED
        assert withheld_exp is not None and withheld_exp.status is ExperimentStatus.COMPLETED
    finally:
        numerical_store.close()
        withheld_store.close()


def test_scripted_model_refuses_leaked_nofeedback_rewards() -> None:
    from rewardbench import CONTRACT_VERSION
    from rewardbench.contracts import (
        EnvironmentSpec,
        FeedbackCondition,
        ModelRequest,
        PriorAttempt,
        RewardFeedback,
        Split,
    )

    model = ScriptedFeedbackModel()
    leaked = PriorAttempt(
        revision_index=0,
        parameters=dict(INITIAL_CONTROLLER),
        valid=True,
        validation_error=None,
        feedback=(
            RewardFeedback(
                revision_index=0,
                episode_index=0,
                total_reward=-1.0,
                success=False,
                crashed=True,
                steps=10,
            ),
        ),
    )
    bad = ModelRequest(
        contract_version=CONTRACT_VERSION,
        experiment_id="exp_test",
        session_id="ses_test",
        revision_index=1,
        feedback_condition=FeedbackCondition.NO_FEEDBACK,
        split=Split.DEVELOPMENT,
        environment=EnvironmentSpec(
            environment_id="apollolander",
            display_name="ApolloLander",
            task_description="test",
            controller_schema={},
            action_space_summary="thrust/rotation",
            observation_space_summary="state",
        ),
        history=(leaked,),
    )
    with pytest.raises(RuntimeError, match="leaked"):
        model.propose(bad)


def test_cli_smoke_subprocess(tmp_path: Path) -> None:
    database = tmp_path / "smoke.sqlite"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "rewardbench.run",
            "--config",
            str(NUMERICAL),
            "--mode",
            "mock",
            "--database",
            str(database),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert "infrastructure test" in completed.stdout
    assert "status: completed" in completed.stdout
    assert database.is_file()
    store = SqliteStore(database)
    try:
        exp_id = experiment_id(prepare_config(NUMERICAL, database_path=database))
        attempts = store.fetch_attempts(exp_id)
        episodes = store.fetch_episodes(exp_id)
        assert len(attempts) == 2
        assert len(episodes) == 2
        assert attempts[0].revision_index == episodes[0].revision_index == 0
        assert attempts[1].revision_index == episodes[1].revision_index == 1
        assert attempts[0].parameters == INITIAL_CONTROLLER
        assert attempts[1].parameters == REVISED_CONTROLLER
    finally:
        store.close()


def test_cli_live_mode_exits_config_error() -> None:
    code = main(["--config", str(NUMERICAL), "--mode", "live"])
    assert code == 2
