#!/usr/bin/env python3
"""Spend remaining diagnostic budget on exploration-rate probes (no training)."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.starts import (  # noqa: E402
    PAD_MID_X,
    PAD_Y,
    PHYSICS_SCALE,
    derive_start,
)
from rewardbench.rl.continuous_policy import ROTATION_DELTAS  # noqa: E402
from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed  # noqa: E402
from rewardbench.rl.upstream_env import UpstreamSession  # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "CLEAN_L0_s21"
MAX_STEPS = 400
N = 40
SEED_START = 520000  # new non-reserved diagnostic seeds


def wilson(s: int, n: int) -> list[float]:
    if n <= 0:
        return [0.0, 0.0]
    z = 1.96
    p = s / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0.0, center - margin), min(1.0, center + margin)]


def run_probe(
    *,
    name: str,
    mode: str,
    start_fn,
    budget: DiagnosticBudget,
) -> dict:
    session = UpstreamSession.start()
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
    frames = 0
    try:
        for i in range(N):
            seed = SEED_START + i
            assert_seed_allowed(seed, context="probe")
            start = start_fn(seed)
            msg = session.call(
                {
                    "cmd": "reset",
                    "config": {
                        "maxSteps": MAX_STEPS,
                        "lockedCamera": True,
                        "bonuses": False,
                        "rewardMode": "touchdown_v1",
                        "start": start,
                    },
                }
            )
            cmd_rot = int(round(float(start["rotation"]) / 10.0) * 10)
            done = False
            while not done:
                if mode == "random_delta":
                    thrust = float(np.random.uniform(0, 1))
                    delta = int(ROTATION_DELTAS[int(np.random.randint(0, 3))])
                    cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                    cmd_rot = int(round(cmd_rot / 10.0) * 10)
                    command = {"thrust": thrust, "rotation": cmd_rot}
                elif mode == "random_absolute":
                    thrust = float(np.random.uniform(0, 1))
                    command = {
                        "thrust": thrust,
                        "rotation": int(np.random.randint(-9, 10) * 10),
                    }
                elif mode == "open_loop_soft_hold":
                    # Diagnostic solvability only — not a train prior.
                    command = {"thrust": 0.22, "rotation": 0}
                else:
                    raise ValueError(mode)
                msg = session.call({"cmd": "step", "action": command})
                frames += 1
                result = msg["result"]
                done = bool(result["done"])
                if done:
                    status = result.get("status") or msg.get("status") or ""
                    # Prefer native outcome classification from host
                    term = msg.get("terminal") or {}
                    st = term.get("status") or status
                    if st == "landed":
                        counts["perfect"] += 1
                    elif st == "hard_landing":
                        counts["hard"] += 1
                    elif st == "crashed":
                        counts["crash"] += 1
                    elif st in ("timeout", "timed_out") or result.get("timedOut"):
                        counts["timeout"] += 1
                    else:
                        # Fallback from done flags
                        if result.get("timedOut"):
                            counts["timeout"] += 1
                        else:
                            counts["crash"] += 1
    finally:
        session.close()

    budget.charge(frames, reason=f"probe:{name}")
    land = counts["perfect"] + counts["hard"]
    return {
        "name": name,
        "mode": mode,
        "n": N,
        "seed_start": SEED_START,
        "max_steps": MAX_STEPS,
        "counts": counts,
        "landing_rate": land / N,
        "landing_wilson95": wilson(land, N),
        "diagnostic_frames": frames,
    }


def main() -> None:
    prev = json.loads((OUT / "logs" / "diagnostic_budget.json").read_text())
    budget = DiagnosticBudget(hard_cap=int(prev["hard_cap"]), spent=int(prev["spent"]))
    np.random.seed(7)

    def l0_start(seed: int) -> dict:
        return derive_start(seed, version="apollolander.starts.curriculum_l0_v3", vary_fuel=False).as_dict()

    def near_start(seed: int) -> dict:
        # ~3–6 px above pad, upright, near-zero velocity (physically legitimate).
        u = (seed % 1000) / 1000.0
        return {
            "x": PAD_MID_X + (-2.0 + 4.0 * u),
            "y": PAD_Y - (6.0 + 3.0 * u),
            "vx": -0.005 + 0.01 * u,
            "vy": 0.01 + 0.01 * u,
            "rotation": 0.0,
            "fuel": 1000.0,
            "scale": PHYSICS_SCALE,
        }

    results = []
    probes = [
        ("L0_random_absolute", "random_absolute", l0_start),
        ("L0_near_random_delta", "random_delta", near_start),
        ("L0_open_loop_soft_hold_solvability", "open_loop_soft_hold", l0_start),
        ("L0_near_open_loop_soft_hold", "open_loop_soft_hold", near_start),
    ]
    for name, mode, fn in probes:
        if budget.remaining() < N * 50:
            print("skip", name, "remaining", budget.remaining())
            break
        try:
            row = run_probe(name=name, mode=mode, start_fn=fn, budget=budget)
        except DiagnosticBudgetExhausted as exc:
            print("budget exhausted:", exc)
            break
        results.append(row)
        print(name, row["counts"], "rate", row["landing_rate"], "frames", row["diagnostic_frames"])

    out = {
        "probes": results,
        "diagnostic_budget": budget.snapshot(),
        "note": (
            "Open-loop soft-hold is solvability diagnostic only; not used as a training prior. "
            "L0_near is a proposed closer start distribution for a future clean run."
        ),
    }
    (OUT / "logs" / "exploration_probes.json").write_text(json.dumps(out, indent=2) + "\n")
    (OUT / "logs" / "diagnostic_budget.json").write_text(
        json.dumps(budget.snapshot(), indent=2) + "\n"
    )
    print("wrote exploration_probes.json spent", budget.spent)


if __name__ == "__main__":
    main()
