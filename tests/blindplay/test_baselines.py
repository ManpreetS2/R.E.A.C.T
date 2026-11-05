"""Baseline planning and (dry-label) execution through the isolated host. tmp_path only; no study directory."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from rewardbench.blindplay import baselines, isolation, results

needs_isolation = pytest.mark.skipif(isolation.supported() is not None,
                                     reason="OS isolation needs Windows (AppContainer) or macOS (Seatbelt)")


def _arg(run, flag):
    return run["host_args"][run["host_args"].index(flag) + 1]


def test_plan_has_two_conditions_of_the_seven_protocol_runs():
    runs = baselines.official_plan("keyset.v2")
    assert len(runs) == 14 and len({r["subdir"] for r in runs}) == 14
    for cond, limit in (("matched-1000", 1000), ("diagnostic-20000", 20000)):
        sub = [r for r in runs if r["condition"] == cond]
        assert [r["script"] for r in sub] == ["idle", "key-sweep"] + ["seeded-random"] * 5
        assert [r["script_seed"] for r in sub[2:]] == [0, 1, 2, 3, 4]
        for r in sub:
            assert r["max_requests"] == limit and _arg(r, "--max-requests") == str(limit)
            assert _arg(r, "--episodes") == "10" and _arg(r, "--episode-frame-budget") == "8000"
            assert _arg(r, "--keyset") == "keyset.v2" and cond in r["subdir"]
    assert {r["condition_role"] for r in runs if r["condition"] == "matched-1000"} == {"budget-matched control"}
    assert all("NOT budget-matched" in r["condition_role"] for r in runs if r["condition"] == "diagnostic-20000")
    with pytest.raises(ValueError):
        baselines.official_plan("keyset.v9")
    with pytest.raises(ValueError):
        baselines.official_plan("keyset.v2", conditions=["nope"])


def test_single_condition_can_be_selected_but_default_covers_both():
    one = baselines.official_plan("keyset.v2", conditions=["matched-1000"])
    assert len(one) == 7 and {r["condition"] for r in one} == {"matched-1000"}
    assert baselines.plan_hash(one) != baselines.plan_hash(baselines.official_plan("keyset.v2"))


def test_plan_hash_is_deterministic_and_sensitive():
    full = baselines.official_plan("keyset.v2")
    a = baselines.plan_hash(full)
    assert a == baselines.plan_hash(baselines.official_plan("keyset.v2"))
    assert a != baselines.plan_hash(baselines.official_plan("keyset.v1"))
    assert a != baselines.plan_hash(baselines.official_plan("keyset.v2", episodes=9))
    c3 = baselines.plan_hash(baselines.official_plan("keyset.v2", conditions={"custom-3": 3}, dry_label="t"))
    assert a != c3 and c3 != baselines.plan_hash(baselines.official_plan("keyset.v2", conditions={"custom-3": 4}, dry_label="t"))
    assert a != baselines.plan_hash(baselines.official_plan("keyset.v2", conditions=["diagnostic-20000"]))
    assert a != baselines.plan_hash([r for r in full if r["name"] != "07_seeded-random_seed4"])


def test_plan_hash_does_not_depend_on_the_output_path(tmp_path, capsys):
    hashes = []
    for name in ("a", "much/longer/other"):
        assert baselines.main(["plan", "--keyset", "keyset.v2", "--out-root", str(tmp_path / name)]) == 0
        hashes.append(capsys.readouterr().out.splitlines()[-1])
    assert hashes[0] == hashes[1] == "plan_sha256 " + baselines.plan_hash(baselines.official_plan("keyset.v2"))


def test_plan_cli_prints_both_conditions_and_writes_nothing(tmp_path, capsys):
    root = tmp_path / "out"
    assert baselines.main(["plan", "--keyset", "keyset.v2", "--out-root", str(root)]) == 0
    text = capsys.readouterr().out
    lines = text.splitlines()
    assert sum("rewardbench.blindplay.host" in line for line in lines) == 14
    assert sum("--max-requests 1000" in line for line in lines) == 7 and sum("--max-requests 20000" in line for line in lines) == 7
    assert "matched-1000" in text and "budget-matched control" in text
    assert "diagnostic-20000" in text and "NOT budget-matched" in text
    assert lines[-1] == "plan_sha256 " + baselines.plan_hash(baselines.official_plan("keyset.v2"))
    assert not root.exists()
    assert baselines.main(["plan", "--keyset", "keyset.v2", "--out-root", str(root), "--condition", "matched-1000"]) == 0
    assert sum("rewardbench.blindplay.host" in line for line in capsys.readouterr().out.splitlines()) == 7


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


@needs_isolation
def test_dry_label_executes_the_matched_condition_isolated(tmp_path):
    result = baselines.run_plan("keyset.v2", tmp_path, approval_reference=None, dry_label="pytest",
                                episodes=1, frame_budget=30, conditions=["matched-1000"])
    root = Path(result["out_root"])
    assert root.name == "NON-STUDY-pytest" and (root / baselines.FIXTURE_FILE).is_file()
    assert result["complete"] and result["executed_runs"] == 7
    plan = baselines.official_plan("keyset.v2", 1, 30, conditions=["matched-1000"])
    assert result["plan_sha256"] == baselines.plan_hash(plan)
    log = json.loads((root / "baseline_run_log.json").read_text(encoding="utf-8"))
    assert log["complete"] is True and log["conditions"] == {"matched-1000": 1000}
    for run, entry in zip(plan, log["runs"]):
        assert entry["condition"] == "matched-1000" and entry["max_requests"] == 1000 and entry["subdir"] == run["subdir"]
        s = results.summarize(root / run["subdir"])
        assert s["integrity"]["ok"] and s["completeness"]["flag"] == "complete"
        assert s["completeness"]["censoring"]["flag"] == "not_censored"
        assert s["header"]["max_requests"] == 1000 and s["header"]["condition"] == "matched-1000"
        assert s["header"]["condition_max_requests_agrees"] is True
        assert s["header"]["label"] == "scripted NON-AI baseline" and s["header"]["keyset"] == "keyset.v2"
        assert s["header"]["script"] == run["script"] and s["header"]["script_seed"] == run["script_seed"]


@needs_isolation
def test_dry_label_run_with_a_tiny_limit_is_censored_and_recorded(tmp_path):
    result = baselines.run_plan("keyset.v2", tmp_path, approval_reference=None, dry_label="pytest-censor",
                                episodes=2, frame_budget=30, conditions={"custom-3": 3}, only_scripts=["idle"])
    root = Path(result["out_root"])
    assert result["executed_runs"] == 1
    s = results.summarize(root / "custom-3_01_idle", run_replay=True)
    assert s["completeness"]["censoring"]["flag"] == "CENSORED_BY_REQUEST_LIMIT"
    assert s["completeness"]["censoring"]["max_requests"] == 3 and s["header"]["condition"] == "custom-3"
    assert s["integrity"]["ok"] and s["integrity"]["replay_receipt"]["reproduced"] is True


def test_approved_run_records_reference_verbatim_and_condition(tmp_path, monkeypatch):
    calls = []

    class Done:
        returncode, stdout, stderr = 0, "", ""

    monkeypatch.setattr(baselines.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or Done())
    r = baselines.run_plan("keyset.v2", tmp_path / "study", approval_reference="OWNER-MSG-123", episodes=1, frame_budget=30)
    assert len(calls) == 14 and r["complete"]
    assert sum(c[c.index("--max-requests") + 1] == "1000" for c in calls) == 7
    assert "OWNER-MSG-123" in (tmp_path / "study" / "OWNER_APPROVAL_REFERENCE.txt").read_text(encoding="utf-8")
    log = json.loads((tmp_path / "study" / "baseline_run_log.json").read_text(encoding="utf-8"))
    assert {(e["condition"], e["max_requests"]) for e in log["runs"]} == {("matched-1000", 1000), ("diagnostic-20000", 20000)}
    assert log["conditions"] == {"matched-1000": 1000, "diagnostic-20000": 20000}


def test_known_labels_cannot_carry_a_non_canonical_limit():
    for bad in ({"matched-1000": 20000}, {"diagnostic-20000": 1000}, {"matched-1000": 1001, "diagnostic-20000": 20000}):
        with pytest.raises(ValueError, match="canonically"):
            baselines.official_plan("keyset.v2", conditions=bad)
        with pytest.raises(ValueError, match="canonically"):
            baselines.official_plan("keyset.v2", conditions=bad, dry_label="t")


def test_custom_labels_need_dry_label_and_get_a_non_official_role():
    with pytest.raises(baselines.PlanRefused):
        baselines.official_plan("keyset.v2", conditions={"custom-3": 3})
    with pytest.raises(baselines.PlanRefused):
        baselines.run_plan("keyset.v2", Path("unused-x"), approval_reference="ref", conditions={"custom-3": 3})
    runs = baselines.official_plan("keyset.v2", conditions={"custom-3": 3}, dry_label="t")
    assert {r["condition_role"] for r in runs} == {"custom-3 (NOT budget-matched, NOT an official condition)"}


def test_only_scripts_refused_on_an_approved_run(tmp_path):
    with pytest.raises(baselines.PlanRefused, match="only_scripts"):
        baselines.official_plan("keyset.v2", only_scripts=["idle"])
    with pytest.raises(baselines.PlanRefused, match="only_scripts"):
        baselines.run_plan("keyset.v2", tmp_path / "o", approval_reference="ref", only_scripts=["idle"])
    assert not (tmp_path / "o").exists()

# The plan the owner will be asked to authorize (docs/BASELINE_EXECUTION_CARD.md). If ANY of this changes, the frozen hash changes:
# that must be a deliberate, reviewed edit of this test AND of the card and the protocol, never a side effect.
FROZEN_PLAN_SHA256_KEYSET_V2 = "bb527a18a5ad88e82769ee800d97b2bfe8c9de73d856be688024e0286d6922dd"
FROZEN_SUBDIRS = [
    f"{cond}_{name}" for cond in ("matched-1000", "diagnostic-20000")
    for name in ("01_idle", "02_key-sweep", "03_seeded-random_seed0", "04_seeded-random_seed1", "05_seeded-random_seed2",
                 "06_seeded-random_seed3", "07_seeded-random_seed4")]


def test_the_frozen_official_baseline_plan():
    runs = baselines.official_plan("keyset.v2")
    assert baselines.plan_hash(runs) == FROZEN_PLAN_SHA256_KEYSET_V2
    assert [r["subdir"] for r in runs] == FROZEN_SUBDIRS
    assert {(r["condition"], r["max_requests"]) for r in runs} == {("matched-1000", 1000), ("diagnostic-20000", 20000)}
    assert all(_arg(r, "--seed") == "0" and _arg(r, "--episodes") == "10" and _arg(r, "--episode-frame-budget") == "8000"
               and _arg(r, "--keyset") == "keyset.v2" for r in runs)
