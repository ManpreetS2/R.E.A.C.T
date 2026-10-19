#!/usr/bin/env python3
"""Document held-out native outcomes for trained V5 checkpoints vs selected step-0.

Not used for selection or tuning — corrects the reporting ambiguity that
'V5 selected' == step0 after a zero-land DEV sweep.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.seeds import V5_HELD_OUT_SEEDS  # noqa: E402

OUT = ROOT / "outputs" / "ppo_pilot_v5_commitment"
MODELS = ROOT / "models" / "ppo_pilot_v5_commitment"


def _load_eval_model():
    path = ROOT / "scripts" / "run_v5_eval.py"
    spec = importlib.util.spec_from_file_location("run_v5_eval_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.eval_model


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    eval_model = _load_eval_model()
    seeds = list(V5_HELD_OUT_SEEDS)
    specs = [
        ("heldout_v5_selected_step0_det", MODELS / "step0_random_init.zip", 19500),
        ("heldout_v5_trained_final_det", MODELS / "final_model.zip", 19501),
        (
            "heldout_v5_trained_25k_det",
            MODELS / "checkpoints" / "ppo_apollo_25000_steps.zip",
            19502,
        ),
    ]
    rows = {}
    for label, path, port in specs:
        print(f"eval {label}...", flush=True)
        s = eval_model(
            path, seeds, label, deterministic=True, commitment=True, port=port
        )
        (OUT / f"{label}.json").write_text(json.dumps(s, indent=2))
        rows[label] = {k: v for k, v in s.items() if k != "episodes"}
        rows[label]["sha256"] = sha256(path)

    sel = MODELS / "selected" / "selected_model.zip"
    assert sha256(sel) == sha256(MODELS / "step0_random_init.zip")

    report = {
        "purpose": "distinguish_selected_step0_from_trained_v5",
        "seed_pool": "V5_HELD_OUT_SEEDS",
        "selected_is_step0": True,
        "by_checkpoint": rows,
        "note": (
            "DEV land rate was 0% for every checkpoint, so selection rule chose step0. "
            "Trained checkpoints are reported here for honesty; they were NOT selected."
        ),
    }
    (OUT / "heldout_trained_vs_selected.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
