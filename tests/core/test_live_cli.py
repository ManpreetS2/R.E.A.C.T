"""Offline tests for the authorized live CLI path.

All provider HTTP is FakeTransport. ApolloLander physics is real (Node).
No live API keys. No paid calls. A scripted/mocked provider response is not
evidence of LLM learning.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rewardbench.contracts import ConfigError, ExperimentStatus, FeedbackCondition
from rewardbench.core.ids import experiment_id
from rewardbench.run.cli import main
from rewardbench.run.factory import build_environment, build_model, prepare_config
from rewardbench.run.live import (
    SESSION_CALL_RESOURCE,
    SessionPaidCallGate,
    is_session_pause,
    preflight_live,
    validate_live_authorization,
)
from rewardbench.storage import SqliteStore

from tests.providers.conftest import FakeTransport, http_json
from tests.providers.e2e_helpers import openai_reply, stronger_controller, weak_controller
from tests.providers.test_adapters import _chat

ROOT = Path(__file__).resolve().parents[2]
PILOT = ROOT / "configs" / "apollolander_pilot_openai_gpt54mini.yaml"
PILOT_NOFB = ROOT / "configs" / "apollolander_pilot_openai_gpt54mini_nofeedback.yaml"
OFFLINE = ROOT / "configs" / "apollolander_offline_development_numerical.yaml"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")

TEST_KEY = "sk-test-live-cli-not-a-real-key"


def _pilot_config(tmp_path: Path, source: Path = PILOT, **yaml_overrides):
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    payload["database_path"] = str(tmp_path / "pilot.sqlite")
    payload["max_episode_steps"] = 40
    meta = dict(payload.get("metadata") or {})
    adapter = dict(meta.get("adapter_kwargs") or {})
    adapter["max_steps"] = 40
    adapter.setdefault("research_mode", False)
    meta["adapter_kwargs"] = adapter
    payload["metadata"] = meta
    payload.update(yaml_overrides)
    path = tmp_path / "pilot.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _transport(controllers):
    return FakeTransport([http_json(openai_reply(ctrl)) for ctrl in controllers])


def test_live_requires_explicit_paid_acknowledgment() -> None:
    with pytest.raises(ConfigError, match="i-authorize-paid-api-calls"):
        validate_live_authorization(
            authorize_paid=False,
            authorize_continuation=False,
            resume_selected_attempts=0,
        )


def test_continuation_requires_second_acknowledgment() -> None:
    with pytest.raises(ConfigError, match="authorize-continuation"):
        validate_live_authorization(
            authorize_paid=True,
            authorize_continuation=False,
            resume_selected_attempts=1,
        )


def test_cli_live_without_ack_exits_config_error(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path)
    assert main(["--config", str(path), "--mode", "live"]) == 2


def test_cli_live_rejects_max_new_paid_calls_above_one(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path)
    code = main(
        [
            "--config",
            str(path),
            "--mode",
            "live",
            "--i-authorize-paid-api-calls",
            "--max-new-paid-calls",
            "2",
        ],
        _api_key=TEST_KEY,
        _transport=_transport([weak_controller()]),
    )
    assert code == 2


def test_preflight_rejects_unpriced_model(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path, model_id="not-a-real-model-id")
    config = prepare_config(path)
    env = build_environment(config)
    with pytest.raises(ConfigError, match="unpriced"):
        preflight_live(config, env, api_key=TEST_KEY)
    env.close()


def test_preflight_rejects_missing_cost_ceiling(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    payload["budget"]["max_cost_usd"] = None
    # YAML null becomes None; rewrite without the key by setting invalid via replace after load.
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    # ExperimentConfig may reject None if loader omits — force via prepare after editing file
    # to drop the field entirely:
    del payload["budget"]["max_cost_usd"]
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config = prepare_config(path)
    env = build_environment(config)
    with pytest.raises(ConfigError, match="max_cost_usd"):
        preflight_live(config, env, api_key=TEST_KEY)
    env.close()


def test_preflight_rejects_retries(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path, max_model_retries=1)
    config = prepare_config(path)
    env = build_environment(config)
    with pytest.raises(ConfigError, match="max_model_retries"):
        preflight_live(config, env, api_key=TEST_KEY)
    env.close()


def test_preflight_rejects_missing_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _pilot_config(tmp_path)
    config = prepare_config(path)
    env = build_environment(config)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="API key"):
        preflight_live(config, env, api_key=None)
    env.close()


def test_one_call_pilot_pauses_and_does_not_claim_completion(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _pilot_config(tmp_path)
    transport = _transport([weak_controller(), stronger_controller()])
    code = main(
        [
            "--config",
            str(path),
            "--mode",
            "live",
            "--i-authorize-paid-api-calls",
            "--database",
            str(tmp_path / "one.sqlite"),
        ],
        _api_key=TEST_KEY,
        _transport=transport,
        _sleeper=lambda _s: None,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "run_state: paused" in captured.out
    assert "not a completed learning experiment" in captured.out
    assert "status: interrupted" in captured.out
    assert len(transport.requests) == 1

    config = prepare_config(path, database_path=tmp_path / "one.sqlite")
    store = SqliteStore(config.database_path)
    try:
        exp = store.get_experiment(experiment_id(config))
        assert exp is not None
        assert exp.status is ExperimentStatus.INTERRUPTED
        assert "live session paid-call limit" in (exp.error or "")
        attempts = [row for row in store.fetch_attempts(exp.experiment_id) if row.selected]
        episodes = store.fetch_episodes(exp.experiment_id)
        assert len(attempts) == 1
        assert len(episodes) == 1
        assert attempts[0].provider == "openai"
        assert attempts[0].model_id == "gpt-5.4-mini"
        assert attempts[0].parameters == weak_controller()
        assert episodes[0].total_reward is not None
        assert episodes[0].revision_index == 0
        assert is_session_pause(exp.error, status_value=exp.status.value)
    finally:
        store.close()


def test_authorized_continuation_resumes_without_repeating_first_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _pilot_config(tmp_path)
    database = tmp_path / "resume.sqlite"
    first_transport = _transport([weak_controller()])
    assert (
        main(
            [
                "--config",
                str(path),
                "--mode",
                "live",
                "--i-authorize-paid-api-calls",
                "--database",
                str(database),
            ],
            _api_key=TEST_KEY,
            _transport=first_transport,
            _sleeper=lambda _s: None,
        )
        == 0
    )
    assert len(first_transport.requests) == 1

    # Continuation without acknowledgment must fail closed.
    assert (
        main(
            [
                "--config",
                str(path),
                "--mode",
                "live",
                "--i-authorize-paid-api-calls",
                "--database",
                str(database),
            ],
            _api_key=TEST_KEY,
            _transport=_transport([stronger_controller()]),
            _sleeper=lambda _s: None,
        )
        == 2
    )

    second_transport = _transport([stronger_controller()])
    code = main(
        [
            "--config",
            str(path),
            "--mode",
            "live",
            "--i-authorize-paid-api-calls",
            "--authorize-continuation",
            "--database",
            str(database),
        ],
        _api_key=TEST_KEY,
        _transport=second_transport,
        _sleeper=lambda _s: None,
    )
    captured = capsys.readouterr()
    assert code == 0
    assert "run_state: completed" in captured.out
    assert len(second_transport.requests) == 1

    config = prepare_config(path, database_path=database)
    store = SqliteStore(database)
    try:
        eid = experiment_id(config)
        attempts = [row for row in store.fetch_attempts(eid) if row.selected]
        episodes = store.fetch_episodes(eid)
        assert len(attempts) == 2
        assert len(episodes) == 2
        assert attempts[0].parameters == weak_controller()
        assert attempts[1].parameters == stronger_controller()
        assert store.get_experiment(eid).status is ExperimentStatus.COMPLETED
        # Feedback from revision 0 must be visible on the second HTTP body.
        body = json.loads(second_transport.requests[0].body)
        user = body["messages"][1]["content"]
        assert "reward=" in user
        assert str(episodes[0].total_reward) in user or "reward=" in user
    finally:
        store.close()


def test_nofeedback_live_cli_hides_rewards_in_continuation_prompt(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path, source=PILOT_NOFB)
    database = tmp_path / "nofb.sqlite"
    assert (
        main(
            [
                "--config",
                str(path),
                "--mode",
                "live",
                "--i-authorize-paid-api-calls",
                "--database",
                str(database),
            ],
            _api_key=TEST_KEY,
            _transport=_transport([weak_controller()]),
            _sleeper=lambda _s: None,
        )
        == 0
    )
    second = _transport([stronger_controller()])
    assert (
        main(
            [
                "--config",
                str(path),
                "--mode",
                "live",
                "--i-authorize-paid-api-calls",
                "--authorize-continuation",
                "--database",
                str(database),
            ],
            _api_key=TEST_KEY,
            _transport=second,
            _sleeper=lambda _s: None,
        )
        == 0
    )
    body = json.loads(second.requests[0].body)
    user = body["messages"][1]["content"].lower()
    assert "reward=" not in user
    assert "total_reward" not in user
    store = SqliteStore(database)
    try:
        config = prepare_config(path, database_path=database)
        episodes = store.fetch_episodes(experiment_id(config))
        assert len(episodes) == 2
        assert all(row.total_reward is not None for row in episodes)
        assert store.get_experiment(experiment_id(config)).feedback_condition is FeedbackCondition.NO_FEEDBACK
    finally:
        store.close()


def test_mock_mode_unchanged_still_works(tmp_path: Path) -> None:
    database = tmp_path / "mock.sqlite"
    assert (
        main(
            [
                "--config",
                str(OFFLINE),
                "--mode",
                "mock",
                "--database",
                str(database),
            ]
        )
        == 0
    )
    store = SqliteStore(database)
    try:
        config = prepare_config(OFFLINE, database_path=database)
        assert store.get_experiment(experiment_id(config)).status is ExperimentStatus.COMPLETED
        assert len(store.fetch_attempts(experiment_id(config))) == 2
    finally:
        store.close()


def test_session_gate_blocks_second_propose_without_runner() -> None:
    class _Inner:
        provider = "openai"
        model_id = "gpt-5.4-mini"

        def propose(self, request):
            return request

    gate = SessionPaidCallGate(_Inner(), max_new_calls=1)
    gate.propose(object())
    with pytest.raises(Exception) as exc:
        gate.propose(object())
    assert getattr(exc.value, "resource", None) == SESSION_CALL_RESOURCE


def test_paired_pilot_configs_differ_only_by_feedback() -> None:
    numerical = prepare_config(PILOT)
    withheld = prepare_config(PILOT_NOFB)
    assert numerical.feedback_condition is FeedbackCondition.NUMERICAL_REWARD
    assert withheld.feedback_condition is FeedbackCondition.NO_FEEDBACK
    assert numerical.seed == withheld.seed
    assert numerical.num_revisions == withheld.num_revisions
    assert numerical.max_model_retries == withheld.max_model_retries == 0
    assert numerical.budget.max_cost_usd == withheld.budget.max_cost_usd
    assert numerical.development_seeds == withheld.development_seeds
    assert experiment_id(numerical) != experiment_id(withheld)


def test_live_build_model_uses_provider_factory_not_scripted(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path)
    config = prepare_config(path)
    env = build_environment(config)
    model = build_model(
        config,
        mode="live",
        authorize_paid=True,
        environment=env,
        api_key=TEST_KEY,
        transport=_transport([weak_controller()]),
        sleeper=lambda _s: None,
    )
    assert isinstance(model, SessionPaidCallGate)
    assert model.provider == "openai"
    assert model.model_id == "gpt-5.4-mini"
    env.close()


def test_invalid_controller_from_provider_is_logged_not_flown(tmp_path: Path) -> None:
    path = _pilot_config(tmp_path, num_revisions=1)
    transport = FakeTransport([http_json(_chat("not-json-controller"))])
    code = main(
        [
            "--config",
            str(path),
            "--mode",
            "live",
            "--i-authorize-paid-api-calls",
            "--database",
            str(tmp_path / "bad.sqlite"),
        ],
        _api_key=TEST_KEY,
        _transport=transport,
        _sleeper=lambda _s: None,
    )
    assert code == 0
    store = SqliteStore(tmp_path / "bad.sqlite")
    try:
        config = prepare_config(path, database_path=tmp_path / "bad.sqlite")
        eid = experiment_id(config)
        assert store.fetch_episodes(eid) == []
        attempts = store.fetch_attempts(eid)
        assert len(attempts) == 1
        assert attempts[0].valid is False
        assert store.get_experiment(eid).status is ExperimentStatus.COMPLETED
    finally:
        store.close()
