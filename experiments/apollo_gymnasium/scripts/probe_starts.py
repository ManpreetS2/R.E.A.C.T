#!/usr/bin/env python3
"""Gate: no-input must fail; continuous reference can land; random is weak."""

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
from env.starts import START_DISTRIBUTIONS, resolve_start  # noqa: E402

OUT = ROOT / "outputs" / "start_gate"
N_EPISODES = 6
MAX_FRAMES = 8000
ACTION_REPEAT = 4


def run_policy(env: ApolloLanderGym, policy: str, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    rng = np.random.default_rng(seed + 17)
    while True:
        if policy == "noop":
            obs, _reward, terminated, truncated, info = env.step(noop_action(obs))
        elif policy == "random":
            obs, _reward, terminated, truncated, info = env.step(random_action(rng))
        elif policy == "reference_continuous":
            # Feasibility only — absolute original-game controls each physics frame.
            cmd = reference_continuous_command(info["raw"])
            obs, _reward, terminated, truncated, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
        elif policy == "reference_multidiscrete":
            action = reference_guidance_action(info["raw"], env.cmd_angle)
            obs, _reward, terminated, truncated, info = env.step(action)
        else:
            raise ValueError(policy)
        if terminated or truncated:
            return {
                "policy": policy,
                "seed": seed,
                "status": info.get("status"),
                "landed": bool(info.get("landed")),
                "perfect": bool(info.get("perfect")),
                "hard_landing": bool(info.get("hard_landing")),
                "crashed": bool(info.get("crashed")),
                "physics_frames": int(info["physics_frames"]),
                "fuel_remaining": info.get("fuel_remaining"),
                "native_score": info.get("native_score"),
            }


def evaluate_distribution(name: str) -> dict:
    start = resolve_start(name)
    env = ApolloLanderGym(
        action_repeat=ACTION_REPEAT,
        max_physics_frames=MAX_FRAMES,
        start_mode="research",
        start_override=start,
        reward_mode="progress_a",
        headless=True,
    )
    rows = []
    policies = ("noop", "random", "reference_continuous", "reference_multidiscrete")
    try:
        for policy in policies:
            for i in range(N_EPISODES):
                rows.append(run_policy(env, policy, seed=1000 + i))
    finally:
        env.close()

    summary = {
        "distribution": name,
        "start": start,
        "meta": START_DISTRIBUTIONS[name],
        "episodes": rows,
    }
    for policy in policies:
        subset = [r for r in rows if r["policy"] == policy]
        land = sum(1 for r in subset if r["landed"])
        summary[f"{policy}_land_rate"] = land / max(len(subset), 1)
        summary[f"{policy}_crash_rate"] = sum(1 for r in subset if r["crashed"]) / max(
            len(subset), 1
        )
        summary[f"{policy}_timeout_rate"] = sum(
            1 for r in subset if r["status"] == "timeout"
        ) / max(len(subset), 1)
        summary[f"{policy}_statuses"] = sorted({r["status"] for r in subset})
    summary["gate_noop_fails"] = summary["noop_land_rate"] == 0.0
    summary["gate_reference_can_land"] = summary["reference_continuous_land_rate"] >= 0.5
    summary["gate_pass"] = bool(
        summary["gate_noop_fails"] and summary["gate_reference_can_land"]
    )
    return summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    reports = []
    for name in ("pilot_near", "pilot_offset", "original_fixed"):
        print(f"=== probing {name} ===", flush=True)
        report = evaluate_distribution(name)
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(report, indent=2))
        reports.append(
            {
                "name": name,
                "gate_pass": report["gate_pass"],
                "noop_land_rate": report["noop_land_rate"],
                "random_land_rate": report["random_land_rate"],
                "reference_continuous_land_rate": report["reference_continuous_land_rate"],
                "reference_multidiscrete_land_rate": report[
                    "reference_multidiscrete_land_rate"
                ],
            }
        )
        print(json.dumps(reports[-1], indent=2), flush=True)

    chosen = None
    for name in ("pilot_near", "pilot_offset", "original_fixed"):
        row = next(r for r in reports if r["name"] == name)
        if row["gate_pass"]:
            chosen = name
            break
    summary = {"reports": reports, "chosen_pilot_start": chosen}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print("SUMMARY", json.dumps(summary, indent=2), flush=True)
    if chosen is None:
        raise SystemExit("No start distribution passed the nontrivial+solvable gate")


if __name__ == "__main__":
    main()
