"""Integrity helpers for curriculum / clean RL training loops.

(a) Failed learning or integrity checks must stop training regardless of level.
(c) Resume must reload episode metrics and first-landing records from disk.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def should_early_stop_on_failed_check(
    *,
    check_passed: bool,
    level_idx: int | None = None,  # retained for API clarity; intentionally unused
) -> bool:
    """Return True when training must stop after a failed integrity/learning check.

    ``level_idx`` is ignored: a failed check always stops, at any curriculum level.
    """
    _ = level_idx
    return not bool(check_passed)


def early_stop_reason_for_failed_check(check_name: str = "l0_basic_learning_check") -> str:
    return f"{check_name}_failed"


def load_first_landing_frames(
    path: Path,
    *,
    levels: list[str],
) -> dict[str, int | None]:
    """Rebuild first-landing frame map from ``first_landings.jsonl`` (append-only)."""
    out: dict[str, int | None] = {lv: None for lv in levels}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        level = row.get("level")
        frames = row.get("frames")
        if level in out and frames is not None and out[level] is None:
            out[level] = int(frames)
    return out


def count_learning_curve_rows(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return sum(1 for _ in reader)


def learning_curve_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def preserve_resume_artifacts(output_dir: Path, *, levels: list[str]) -> dict[str, Any]:
    """Load pre-resume episode metrics and first-landing records from disk.

    Learning-curve CSV is append-only and must not be truncated on resume.
    First-landing map is reconstructed from ``logs/first_landings.jsonl``.
    """
    logs = output_dir / "logs"
    curve = logs / "learning_curve.csv"
    landings = logs / "first_landings.jsonl"
    first = load_first_landing_frames(landings, levels=levels)
    n_rows = count_learning_curve_rows(curve)
    return {
        "learning_curve_path": str(curve),
        "learning_curve_rows_preserved": n_rows,
        "first_landing_frames": first,
        "first_landings_path": str(landings),
    }
