#!/usr/bin/env python3
"""Resume V3 audit: final_model DEV eval + timeout autopsy on best checkpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from audit_v3 import (  # noqa: E402
    MODELS,
    OUT,
    checkpoint_dev_sweep,
    timeout_autopsy,
)

def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== checkpoint DEV sweep (resume) ===", flush=True)
    sweep = checkpoint_dev_sweep(resume=True)
    best = sweep["best_by_land_rate"]
    best_name = best["label"]
    if best_name == "step0_random_init":
        best_path = MODELS / "step0_random_init.zip"
    elif best_name == "final_model":
        best_path = MODELS / "final_model.zip"
    else:
        best_path = MODELS / "checkpoints" / f"{best_name}.zip"
    print(f"=== timeout autopsy on {best_path.name} (best DEV) ===", flush=True)
    autopsy = timeout_autopsy(best_path)
    # Also autopsy final for contrast
    print("=== timeout autopsy on final_model ===", flush=True)
    autopsy_final = timeout_autopsy(MODELS / "final_model.zip")
    (OUT / "timeout_autopsy_final.json").write_text(json.dumps(autopsy_final, indent=2))

    summary = {
        "best_dev_checkpoint": best,
        "final_dev_land_rate": sweep["final_land_rate"],
        "best_beats_final": sweep["best_beats_final"],
        "timeout_diagnosis_best": autopsy["diagnosis"],
        "timeout_means_best": autopsy.get("timeout_means"),
        "land_means_best": autopsy.get("land_means"),
        "timeout_diagnosis_final": autopsy_final["diagnosis"],
        "timeout_means_final": autopsy_final.get("timeout_means"),
        "land_means_final": autopsy_final.get("land_means"),
        "checkpoint_table": sweep["checkpoints"],
    }
    (OUT / "audit_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
