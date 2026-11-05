"""Baseline planning and (dry-label) execution through the isolated host. tmp_path only; no study directory."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rewardbench.blindplay import baselines, isolation, results


def test_plan_has_the_seven_protocol_runs():
    runs = baselines.official_plan("keyset.v2")
    assert [r["script"] for r in runs] == ["idle", "key-sweep"] + ["seeded-random"] * 5
    assert [r["script_seed"] for r in runs[2:]] == [0, 1, 2, 3, 4]
    assert len({r["subdir"] for r in runs}) == 7
    for r in runs:
        assert "--keyset" in r["host_args"] and r["host_args"][r["host_args"].index("--episodes") + 1] == "10"
    with pytest.raises(ValueError):
        baselines.official_plan("keyset.v9")


def test_plan_hash_is_deterministic_and_sensitive():
    a = baselines.plan_hash(baselines.official_plan("keyset.v2"))
    assert a == baselines.plan_hash(baselines.official_plan("keyset.v2"))
    assert a != baselines.plan_hash(baselines.official_plan("keyset.v1"))
    assert a != baselines.plan_hash(baselines.official_plan("keyset.v2", episodes=9))


def test_plan_cli_prints_commands_and_hash_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "out"
    assert baselines.main(["plan", "--keyset", "keyset.v2", "--out-root", str(root)]) == 0
    text = capsys.readouterr().out.splitlines()
    assert sum("rewardbench.blindplay.host" in line for line in text) == 7
    assert text[-1] == "plan_sha256 " + baselines.plan_hash(baselines.official_plan("keyset.v2"))
    assert not root.exists()


def test_run_refuses_without_approval_reference(tmp_path):
    with pytest.raises(baselines.PlanRefused):
        baselines.run_plan("keyset.v2", tmp_path / "o", approval_reference=None)
    with pytest.raises(baselines.PlanRefused):
        baselines.run_plan("keyset.v2", tmp_path / "o", approval_reference="   ")
    assert not (tmp_path / "o").exists()
    assert baselines.main(["run", "--keyset", "keyset.v2", "--out-root", str(tmp_path / "o")]) == 2


def test_run_refuses_to_overwrite_existing_root(tmp_path):
    (tmp_path / "o").mkdir()
    with pytest.raises(baselines.PlanRefused, match="exists"):
        baselines.run_plan("keyset.v2", tmp_path / "o", approval_reference="ref")
    (tmp_path / "x" / "NON-STUDY-t").mkdir(parents=True)
    with pytest.raises(baselines.PlanRefused, match="exists"):
        baselines.run_plan("keyset.v2", tmp_path / "x", approval_reference=None, dry_label="t")


def test_run_refuses_inside_populated_official_looking_dir(tmp_path):
    official = tmp_path / "runs" / "blind-visual"
    official.mkdir(parents=True)
    (official / "evidence.txt").write_text("x", encoding="utf-8")
    with pytest.raises(baselines.PlanRefused, match="official-looking"):
        baselines.run_plan("keyset.v2", official / "new", approval_reference="ref")
    assert not (official / "new").exists()


@pytest.mark.skipif(isolation.supported() is not None, reason="OS isolation needs Windows (AppContainer) or macOS (Seatbelt)")
def test_dry_label_executes_all_seven_runs_isolated(tmp_path):
    result = baselines.run_plan("keyset.v2", tmp_path, approval_reference=None, dry_label="pytest",
                                episodes=1, frame_budget=30)
    root = Path(result["out_root"])
    assert root.name == "NON-STUDY-pytest" and (root / baselines.FIXTURE_FILE).is_file()
    assert result["complete"] and result["executed_runs"] == 7
    assert result["plan_sha256"] == baselines.plan_hash(baselines.official_plan("keyset.v2", 1, 30))
    for run in baselines.official_plan("keyset.v2", 1, 30):
        s = results.summarize(root / run["subdir"])
        assert s["integrity"]["ok"] and s["completeness"]["flag"] == "complete"
        assert s["header"]["label"] == "scripted NON-AI baseline" and s["header"]["keyset"] == "keyset.v2"
        assert s["header"]["script"] == run["script"] and s["header"]["script_seed"] == run["script_seed"]
    assert json.loads((root / "baseline_run_log.json").read_text(encoding="utf-8"))["complete"] is True


def test_approved_run_records_reference_verbatim(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(baselines.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    r = baselines.run_plan("keyset.v2", tmp_path / "study", approval_reference="OWNER-MSG-123", episodes=1, frame_budget=30)
    assert len(calls) == 7 and r["complete"]
    assert "OWNER-MSG-123" in (tmp_path / "study" / "OWNER_APPROVAL_REFERENCE.txt").read_text(encoding="utf-8")
