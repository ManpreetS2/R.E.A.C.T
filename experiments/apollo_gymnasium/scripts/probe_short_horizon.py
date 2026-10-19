#!/usr/bin/env python3
"""Capped short-horizon start diagnostics (no PPO training)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import (  # noqa: E402
    noop_action,
    random_action,
    reference_continuous_command,
    reference_guidance_action,
)
from env.starts import SHORT_HORIZON_TEMPLATES, derive_short_horizon_start  # noqa: E402

OUT = ROOT / "outputs" / "root_cause" / "short_horizon"
N = 6
MAX_FRAMES = 2000


def run(env, policy: str, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    start = dict(info.get("start") or {})
    rng = np.random.default_rng(seed + 99)
    while True:
        if policy == "noop":
            obs, _, term, trunc, info = env.step(noop_action(obs))
        elif policy == "random":
            obs, _, term, trunc, info = env.step(random_action(rng))
        elif policy == "ref_cont":
            cmd = reference_continuous_command(info["raw"])
            obs, _, term, trunc, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
        elif policy == "ref_legal":
            # Exact learner legal controls (MultiDiscrete + env action_repeat)
            action = reference_guidance_action(info["raw"], env.cmd_angle)
            obs, _, term, trunc, info = env.step(action)
        else:
            raise ValueError(policy)
        if term or trunc:
            return {
                "policy": policy,
                "seed": seed,
                "start": start,
                "status": info.get("status"),
                "landed": bool(info.get("landed")),
                "perfect": bool(info.get("perfect")),
                "crashed": bool(info.get("crashed")),
                "physics_frames": int(info["physics_frames"]),
                "native_score": info.get("native_score"),
            }


def probe_template(template: str, action_repeat: int = 4) -> dict:
    rows = []
    # Use seed-derived start each reset via options
    env = ApolloLanderGym(
        action_repeat=action_repeat,
        max_physics_frames=MAX_FRAMES,
        start_mode="research",
        start_override=derive_short_horizon_start(template, 0, vary=False),
        reward_mode="progress_a",
        headless=True,
    )
    try:
        for policy in ("noop", "random", "ref_cont", "ref_legal"):
            for i in range(N):
                seed = 2000 + i
                start = derive_short_horizon_start(template, seed)
                env.start_override = start
                rows.append(run(env, policy, seed))
    finally:
        env.close()

    report: dict = {
        "template": template,
        "meta": SHORT_HORIZON_TEMPLATES[template],
        "action_repeat": action_repeat,
        "episodes": rows,
        "by_policy": {},
    }
    for policy in ("noop", "random", "ref_cont", "ref_legal"):
        sub = [r for r in rows if r["policy"] == policy]
        n = len(sub)
        frames = [r["physics_frames"] for r in sub]
        report["by_policy"][policy] = {
            "land_rate": sum(1 for r in sub if r["landed"]) / n,
            "crash_rate": sum(1 for r in sub if r["crashed"]) / n,
            "timeout_rate": sum(1 for r in sub if r["status"] == "timeout") / n,
            "mean_physics_frames": float(np.mean(frames)),
            "max_physics_frames": int(max(frames)),
            "statuses": sorted({r["status"] for r in sub}),
        }
    bp = report["by_policy"]
    report["gate_noop_fails"] = bp["noop"]["land_rate"] == 0.0
    report["gate_random_not_trivial"] = bp["random"]["land_rate"] < 0.35
    report["gate_ref_legal_lands"] = bp["ref_legal"]["land_rate"] >= 0.5
    report["gate_short"] = bp["ref_legal"]["mean_physics_frames"] <= 500
    report["gate_pass"] = bool(
        report["gate_noop_fails"]
        and report["gate_random_not_trivial"]
        and report["gate_ref_legal_lands"]
    )
    # Diversity of starts across seeds
    starts = [r["start"] for r in rows if r["policy"] == "noop"]
    report["start_diversity"] = {
        "unique_x": len({round(float(s["x"]), 3) for s in starts}),
        "unique_y": len({round(float(s["y"]), 3) for s in starts}),
        "unique_rotation": len({round(float(s["rotation"]), 1) for s in starts}),
        "x_range": [min(float(s["x"]) for s in starts), max(float(s["x"]) for s in starts)],
        "y_range": [min(float(s["y"]) for s in starts), max(float(s["y"]) for s in starts)],
    }
    return report


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"templates": [], "chosen": None}
    for name in SHORT_HORIZON_TEMPLATES:
        print(f"=== {name} ===", flush=True)
        # Primary: learner action_repeat=4; also note repeat=1 for analysis
        report = probe_template(name, action_repeat=4)
        (OUT / f"{name}_ar4.json").write_text(json.dumps(report, indent=2))
        slim = {
            "template": name,
            "gate_pass": report["gate_pass"],
            "gate_short": report["gate_short"],
            "noop_land": report["by_policy"]["noop"]["land_rate"],
            "random_land": report["by_policy"]["random"]["land_rate"],
            "ref_legal_land": report["by_policy"]["ref_legal"]["land_rate"],
            "ref_legal_mean_frames": report["by_policy"]["ref_legal"]["mean_physics_frames"],
            "start_diversity": report["start_diversity"],
        }
        summary["templates"].append(slim)
        print(json.dumps(slim, indent=2), flush=True)

    for row in summary["templates"]:
        if row["gate_pass"]:
            summary["chosen"] = row["template"]
            break
    # Prefer also short if available
    for row in summary["templates"]:
        if row["gate_pass"] and row["gate_short"]:
            summary["chosen"] = row["template"]
            break
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("SUMMARY", json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
