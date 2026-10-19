#!/usr/bin/env python3
"""Observation scaling + legal-control / action-repeat diagnostics (no training)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import STEER_DELTAS, THRUST_LEVELS, ApolloLanderGym  # noqa: E402
from env.controllers import reference_continuous_command, reference_guidance_action  # noqa: E402
from env.starts import derive_short_horizon_start, resolve_start  # noqa: E402

OUT = ROOT / "outputs" / "root_cause"


def obs_stats(env, start, seeds, label: str) -> dict:
    rows = []
    for seed in seeds:
        obs, info = env.reset(seed=seed)
        raw = info["raw"]
        rows.append(
            {
                "seed": seed,
                "obs": obs.tolist(),
                "raw": {
                    k: float(raw[k])
                    for k in ("dx", "altitude", "vx", "vy", "rotation", "fuel", "thrust", "pad_width")
                },
                "start": info.get("start"),
            }
        )
    arr = np.asarray([r["obs"] for r in rows])
    names = [
        "dx_n",
        "alt_n",
        "vx_n",
        "vy_n",
        "ang_n",
        "cmd_n",
        "fuel_n",
        "thrust_n",
        "pad_w_n",
        "dy_n",
    ]
    return {
        "label": label,
        "n": len(seeds),
        "feature_mean": {n: float(arr[:, i].mean()) for i, n in enumerate(names)},
        "feature_std": {n: float(arr[:, i].std()) for i, n in enumerate(names)},
        "feature_abs_mean": {n: float(np.abs(arr[:, i]).mean()) for i, n in enumerate(names)},
        "raw_vy_abs_mean": float(np.mean([abs(r["raw"]["vy"]) for r in rows])),
        "raw_vx_abs_mean": float(np.mean([abs(r["raw"]["vx"]) for r in rows])),
        "note": (
            "vx,vy divided by 2.0 → typical |vy|~0.1 becomes 0.05 in obs (small vs ang/alt). "
            "Angle /90 keeps O(0.1–1). Velocity features may be under-scaled for learning."
        ),
        "samples": rows[:3],
    }


def upright_reachability(action_repeat: int) -> dict:
    """From rotation=-30, can MultiDiscrete ±10° reach exact 0 under action_repeat?"""
    cmd = -30.0
    steps = 0
    path = [cmd]
    # greedy toward 0
    while abs(cmd) > 1e-9 and steps < 50:
        if cmd < 0:
            cmd = float(np.clip(cmd + 10.0, -90, 90))
        elif cmd > 0:
            cmd = float(np.clip(cmd - 10.0, -90, 90))
        path.append(cmd)
        steps += 1
    return {
        "action_repeat": action_repeat,
        "steer_deltas": STEER_DELTAS.tolist(),
        "thrust_levels": THRUST_LEVELS.tolist(),
        "from_minus_30_reaches_exact_zero": path[-1] == 0.0,
        "gym_steps_to_zero": steps,
        "physics_frames_to_zero": steps * action_repeat,
        "path": path,
        "note": (
            "setRotation snaps to 10° in upstream; ±10° relative steer can hit exactly 0. "
            "action_repeat holds the command for N physics frames (angle lerp still applies)."
        ),
    }


def compare_action_modes(template: str = "sh_tilt30_low") -> dict:
    results = []
    for ar in (1, 2, 4, 8):
        env = ApolloLanderGym(
            action_repeat=ar,
            max_physics_frames=2000,
            start_mode="research",
            start_override=derive_short_horizon_start(template, 0),
            headless=True,
        )
        try:
            lands_legal = 0
            lands_cont = 0
            frames_legal = []
            for i in range(4):
                seed = 3000 + i
                env.start_override = derive_short_horizon_start(template, seed)
                # legal MultiDiscrete reference
                obs, info = env.reset(seed=seed)
                while True:
                    a = reference_guidance_action(info["raw"], env.cmd_angle)
                    obs, _, term, trunc, info = env.step(a)
                    if term or trunc:
                        lands_legal += int(info["landed"])
                        frames_legal.append(info["physics_frames"])
                        break
                # continuous absolute (feasibility ceiling)
                env.start_override = derive_short_horizon_start(template, seed)
                obs, info = env.reset(seed=seed)
                while True:
                    cmd = reference_continuous_command(info["raw"])
                    obs, _, term, trunc, info = env.step_absolute(
                        cmd["thrust"], cmd["rotation"], repeats=1
                    )
                    if term or trunc:
                        lands_cont += int(info["landed"])
                        break
        finally:
            env.close()
        results.append(
            {
                "action_repeat": ar,
                "ref_legal_land_rate": lands_legal / 4,
                "ref_cont_land_rate": lands_cont / 4,
                "ref_legal_mean_frames": float(np.mean(frames_legal)) if frames_legal else None,
            }
        )
    return {"template": template, "action_repeat_sweep": results}


def start_variation_demo() -> dict:
    seeds = list(range(10))
    fixed = [resolve_start("pilot_near") for _ in seeds]
    varied = [derive_short_horizon_start("sh_tilt30_low", s) for s in seeds]
    # reproducibility
    a = derive_short_horizon_start("sh_tilt30_low", 7)
    b = derive_short_horizon_start("sh_tilt30_low", 7)
    return {
        "pilot_near_identical_across_seeds": all(fixed[0] == s for s in fixed),
        "short_horizon_unique_states": len({json.dumps(s, sort_keys=True) for s in varied}),
        "short_horizon_x_values": [round(s["x"], 2) for s in varied],
        "short_horizon_rotations": [s["rotation"] for s in varied],
        "reproducible_seed_7": a == b,
        "fixed_seed_repro": a,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=500,
        start_mode="research",
        start_override=resolve_start("pilot_near"),
        headless=True,
    )
    try:
        # Even with different seeds, pilot_near override is identical
        env.start_override = resolve_start("pilot_near")
        stats_fixed = obs_stats(env, resolve_start("pilot_near"), list(range(5)), "pilot_near")
        # Varied short horizon
        rows_stats = []
        for seed in range(8):
            env.start_override = derive_short_horizon_start("sh_tilt30_low", seed)
            obs, info = env.reset(seed=seed)
            rows_stats.append(obs)
        arr = np.asarray(rows_stats)
        stats_varied = {
            "label": "sh_tilt30_low_varied",
            "obs_std": arr.std(axis=0).tolist(),
            "obs_mean": arr.mean(axis=0).tolist(),
        }
    finally:
        env.close()

    report = {
        "obs_pilot_near": stats_fixed,
        "obs_short_varied": stats_varied,
        "upright_reachability": upright_reachability(4),
        "action_repeat_sweep": compare_action_modes(),
        "start_variation": start_variation_demo(),
        "scaling_recommendation": (
            "Consider vx,vy scale ÷0.5 or ÷0.3 (instead of ÷2) so velocity errors are "
            "O(0.1–1) like angle/altitude; keep potential coeffs retuned accordingly. "
            "Do not change scaling and action space in the same pilot."
        ),
    }
    (OUT / "obs_action_analysis.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: report[k] for k in report if k != "obs_pilot_near"}, indent=2))
    print("obs_std_varied", stats_varied["obs_std"])
    print("pilot_near_feature_std", stats_fixed["feature_std"])


if __name__ == "__main__":
    main()
