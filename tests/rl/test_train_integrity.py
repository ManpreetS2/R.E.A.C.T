"""Unit tests for clean-learning integrity fixes (a)(b)(c)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted
from rewardbench.rl.train_integrity import (
    count_learning_curve_rows,
    early_stop_reason_for_failed_check,
    load_first_landing_frames,
    preserve_resume_artifacts,
    should_early_stop_on_failed_check,
)


# ---------------------------------------------------------------------------
# (a) Failed learning / integrity check stops regardless of curriculum level
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("level_idx", [0, 1, 2, 4])
def test_failed_check_stops_at_any_level(level_idx: int) -> None:
    assert should_early_stop_on_failed_check(check_passed=False, level_idx=level_idx) is True
    assert early_stop_reason_for_failed_check() == "l0_basic_learning_check_failed"


@pytest.mark.parametrize("level_idx", [0, 1, 2])
def test_passed_check_does_not_stop(level_idx: int) -> None:
    assert should_early_stop_on_failed_check(check_passed=True, level_idx=level_idx) is False


def test_failed_check_ignores_level_idx_none() -> None:
    assert should_early_stop_on_failed_check(check_passed=False, level_idx=None) is True


# ---------------------------------------------------------------------------
# (b) Diagnostic frame counter with hard cap
# ---------------------------------------------------------------------------


def test_diagnostic_budget_charges_and_reports_remaining() -> None:
    budget = DiagnosticBudget(hard_cap=1000)
    budget.charge(400, reason="step0_eval")
    budget.charge(200, reason="gate")
    assert budget.spent == 600
    assert budget.remaining() == 400
    snap = budget.snapshot()
    assert snap["hard_cap"] == 1000
    assert snap["spent"] == 600
    assert len(snap["ledger"]) == 2


def test_diagnostic_budget_hard_cap_stops_without_raising_cap() -> None:
    budget = DiagnosticBudget(hard_cap=400_000)
    budget.charge(400_000, reason="fill")
    with pytest.raises(DiagnosticBudgetExhausted, match="hard cap 400000"):
        budget.charge(1, reason="overflow")
    assert budget.spent == 400_000
    assert budget.hard_cap == 400_000  # cap must not be raised


def test_diagnostic_budget_rejects_overspend_before_charge() -> None:
    budget = DiagnosticBudget(hard_cap=100)
    assert budget.can_afford(100)
    assert not budget.can_afford(101)
    with pytest.raises(DiagnosticBudgetExhausted):
        budget.charge(101, reason="too_big")
    assert budget.spent == 0


# ---------------------------------------------------------------------------
# (c) Resume preserves learning-curve rows and first-landing records
# ---------------------------------------------------------------------------


def _write_curve(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)


def test_resume_preserves_learning_curve_and_first_landings(tmp_path: Path) -> None:
    levels = [
        "apollolander.starts.curriculum_l0_v3",
        "apollolander.starts.curriculum_l1_v3",
    ]
    logs = tmp_path / "logs"
    logs.mkdir()
    curve = logs / "learning_curve.csv"
    landings = logs / "first_landings.jsonl"

    pre_rows = [
        {
            "global_step": "100",
            "level": levels[0],
            "level_idx": "0",
            "return": "-1.0",
            "status": "crashed",
            "landed": "False",
        },
        {
            "global_step": "250",
            "level": levels[0],
            "level_idx": "0",
            "return": "10.0",
            "status": "landed",
            "landed": "True",
        },
    ]
    _write_curve(curve, pre_rows)
    with landings.open("w", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {
                    "event": "first_train_landing",
                    "level": levels[0],
                    "frames": 250,
                    "status": "landed",
                }
            )
            + "\n"
        )

    # Simulate forced interrupt: artifacts on disk, then resume restore.
    preserved = preserve_resume_artifacts(tmp_path, levels=levels)
    assert preserved["learning_curve_rows_preserved"] == 2
    assert preserved["first_landing_frames"][levels[0]] == 250
    assert preserved["first_landing_frames"][levels[1]] is None

    # Resume must append, not truncate.
    with curve.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(pre_rows[0].keys()))
        w.writerow(
            {
                "global_step": "400",
                "level": levels[0],
                "level_idx": "0",
                "return": "-2.0",
                "status": "crashed",
                "landed": "False",
            }
        )
    assert count_learning_curve_rows(curve) == 3
    # Pre-resume rows still present as prefix.
    with curve.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["global_step"] == "100"
    assert rows[1]["global_step"] == "250"
    assert rows[1]["landed"] == "True"
    assert load_first_landing_frames(landings, levels=levels)[levels[0]] == 250


def test_preserve_resume_artifacts_empty_dir(tmp_path: Path) -> None:
    levels = ["apollolander.starts.curriculum_l0_v3"]
    preserved = preserve_resume_artifacts(tmp_path, levels=levels)
    assert preserved["learning_curve_rows_preserved"] == 0
    assert preserved["first_landing_frames"][levels[0]] is None
