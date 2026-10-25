"""The first real-model study package: matched arms, bounded spend, no accidental paid or reserved use."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path

import pytest
import yaml

from rewardbench import operate, study
from rewardbench.config import load_config
from rewardbench.contracts import FeedbackCondition
from rewardbench.providers.pricing import load_catalog

ROOT = Path(__file__).resolve().parents[2]
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")


def _arms(tier: str = "pilot") -> dict[str, dict]:
    return {c: yaml.safe_load(study.config_path(tier, c).read_text(encoding="utf-8")) for c in study.CONDITIONS}


def test_committed_configs_are_exactly_what_the_generator_produces() -> None:
    study.write_configs("pilot", study.CONFIG_DIR, check=True)


def test_arms_are_matched_except_condition_and_names() -> None:
    arms = _arms()
    study.check_matched(arms)
    first = arms["no_feedback"]
    for condition, config in arms.items():
        assert config["feedback_condition"] == condition
        differing = study.arm_differences(first, config)
        assert differing <= study.ALLOWED_ARM_DIFFERENCES, differing
        assert config["budget"] == first["budget"]
        assert config["model_settings"] == first["model_settings"]
    assert {c["feedback_condition"] for c in arms.values()} == {f.value for f in FeedbackCondition}


def test_a_mismatched_arm_is_detected() -> None:
    arms = _arms()
    arms["reward_only"]["history_window"] += 1
    with pytest.raises(Exception, match="history_window"):
        study.check_matched(arms)


def test_design_protects_the_reserved_final_cohort() -> None:
    pilot = study.study_config("pilot", "reward_only")
    final = study.study_config("study", "reward_only")
    assert pilot["held_out_seeds"] == list(range(1_000_000, 1_000_008))  # engineering only
    assert not set(pilot["held_out_seeds"]) & set(study.RESERVED_FINAL_SEEDS)
    assert final["held_out_seeds"] == list(range(2_000_000, 2_000_016))
    for config in (pilot, final):
        assert not set(config["development_seeds"]) & set(config["held_out_seeds"])
        assert config["development_seeds"] == list(range(8))
        assert config["episodes_per_revision"] == len(config["development_seeds"])  # same panel every revision
        assert config["max_model_retries"] == 0
        assert config["metadata"]["adapter_kwargs"]["research_mode"] is True
    for path in (ROOT / "configs" / "study").glob("*.yaml"):
        assert load_config(path).split.value == "development"
        assert "2000000" not in path.read_text() or "study_" in path.name


def test_study_replicates_differ_only_by_master_seed_and_names() -> None:
    first = study.study_config("study", "reward_only", replicate=1)
    third = study.study_config("study", "reward_only", replicate=3)
    assert study.arm_differences(first, third) == {"seed", "experiment_name", "database_path", "metadata", "notes"}
    assert first["metadata"] | {"replicate": 3} == third["metadata"]
    assert study.study_config("study", "no_feedback", replicate=3)["seed"] == third["seed"]


def test_offline_preflight_passes_without_network_or_credentials(monkeypatch) -> None:
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "XAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("preflight must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    rows = study.preflight("pilot")
    assert [r["arm"] for r in rows] == list(study.CONDITIONS)
    assert all(r["retries"] == 0 and r["first_call_worst_case_usd"] < r["budget_usd"] for r in rows)


@pytest.mark.parametrize("tier", ["pilot", "study"])
def test_experiment_ceiling_covers_the_worst_case_of_every_call(tier) -> None:
    catalog = load_catalog()
    ceiling = study.ceilings(tier)
    for condition in study.CONDITIONS:
        config = study.study_config(tier, condition)
        calls = study.worst_case_calls(config, study._spec(config), catalog)
        assert len(calls) == study.TIERS[tier]["revisions"] == ceiling["max_model_calls"]
        assert sum(c["usd"] for c in calls) <= ceiling["max_cost_usd"] + 1e-9
        assert sum(c["tokens"] for c in calls) <= ceiling["max_tokens"]
        assert all(c["completion_tokens"] == 800 for c in calls)


def test_budget_document_matches_the_calculator() -> None:
    text = (ROOT / "docs" / "FIRST_LLM_STUDY_BUDGET.md").read_text(encoding="utf-8")
    assert study.budget_markdown() in text


def test_launch_guide_contains_the_exact_first_paid_command() -> None:
    text = (ROOT / "docs" / "FIRST_LLM_STUDY_LAUNCH.md").read_text(encoding="utf-8")
    assert FIRST_PAID_COMMAND in text
    assert "NOT EXECUTED" in text


FIRST_PAID_COMMAND = (
    "python -m rewardbench.operate run --mode live --i-authorize-paid-api-calls "
    '--total-usd-ceiling "$APPROVED_CEILING_USD" '
    "--config configs/study/pilot_no_feedback.yaml --out runs/first-llm-study/pilot"
)


def test_live_study_is_refused_without_authorization_and_makes_no_attempt(tmp_path: Path, capsys, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    code = operate.main(["run", "--mode", "live", "--total-usd-ceiling", "1",
                         "--config", str(study.config_path("pilot", "no_feedback")), "--out", str(tmp_path)])
    assert code != 0
    import sqlite3
    with sqlite3.connect(next(tmp_path.glob("*.sqlite"))) as db:
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0


def test_study_config_in_mock_mode_is_refused_so_it_cannot_masquerade(tmp_path: Path, capsys) -> None:
    code = operate.main(["run", "--config", str(study.config_path("pilot", "reward_only")), "--out", str(tmp_path)])
    assert code == 2 and "use --mode live" in capsys.readouterr().err


def test_operator_refuses_final_evaluation_of_the_reserved_cohort(tmp_path: Path, capsys, monkeypatch) -> None:
    """Even a completed live study cannot be final-evaluated through the convenience flag."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    code = operate.main(["run", "--mode", "live", "--heldout", "--total-usd-ceiling", "1",
                         "--config", str(study.config_path("pilot", "no_feedback")), "--out", str(tmp_path)])
    assert code != 0  # no authorization flag -> nothing runs; the reserved guard is covered in test_operate


@needs_node
def test_first_paid_call_path_with_mocked_transport_pauses_after_one_call_and_isolates_feedback(tmp_path: Path, monkeypatch) -> None:
    from tests.core.test_live_cli import TEST_KEY, _transport
    from tests.providers.e2e_helpers import stronger_controller, weak_controller

    transport = _transport([weak_controller(), stronger_controller()])
    real = operate.run_main
    monkeypatch.setattr(operate, "run_main", lambda argv, **kw: real(
        argv, _api_key=TEST_KEY, _transport=transport, _sleeper=lambda _s: None, **kw))
    config = str(study.config_path("pilot", "reward_only"))
    out = str(tmp_path / "o")
    assert operate.main(["run", "--mode", "live", "--i-authorize-paid-api-calls", "--total-usd-ceiling", "1",
                         "--config", config, "--out", out]) == 0
    assert len(transport.requests) == 1  # one paid call, then the session gate pauses
    assert operate.main(["run", "--mode", "live", "--i-authorize-paid-api-calls", "--authorize-continuation",
                         "--total-usd-ceiling", "1", "--config", config, "--out", out]) == 0
    assert len(transport.requests) == 2
    second = json.loads(transport.requests[1].body)["messages"][1]["content"]
    assert "reward=" in second and not any(t in second for t in ("success=", "steps=", "metrics="))
    assert "2000000" not in second and "1000000" not in second
    logged = "".join(p.read_text(errors="ignore") for p in Path(out).rglob("*.txt"))
    assert TEST_KEY not in logged


def test_rehearsal_twin_keeps_design_fields_and_never_lists_the_reserved_cohort() -> None:
    live = study.build_study_config("pilot", "numerical_reward")
    twin = study.rehearsal_config(live)
    assert twin["provider"] == "mock" and twin["held_out_seeds"] == list(study.ENGINEERING_HELDOUT_SEEDS)
    for key in ("num_revisions", "episodes_per_revision", "history_window", "max_episode_steps", "seed",
                "development_seeds", "feedback_condition", "max_model_retries"):
        assert twin[key] == live[key]
    assert not set(twin["held_out_seeds"]) & set(study.RESERVED_FINAL_SEEDS)


@needs_node
def test_end_to_end_rehearsal_audit_passes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setitem(study.TIERS, "pilot", {"revisions": 2, "replicates": 1})
    summary = study.rehearse(tmp_path / "r", "pilot")
    assert summary["isolation"] == "verified"
    # The budget's worst-case history assumes METRIC_KEYS; real episodes must not carry more.
    import sqlite3
    keys: set[str] = set()
    for database in (tmp_path / "r").glob("*.sqlite"):
        with sqlite3.connect(database) as db:
            for (blob,) in db.execute("SELECT metrics_json FROM episodes"):
                keys |= set(json.loads(blob))
    assert keys and keys <= set(study.METRIC_KEYS), keys - set(study.METRIC_KEYS)
    for arm in summary["arms"].values():
        assert arm["model_calls"] == 2 and arm["replays_verified"] >= 2 * 8 + 8
