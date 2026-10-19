#!/usr/bin/env python3
"""Outcome-level fidelity: perfect / hard / crash / timeout via original bridge.

Distinguishes:
- Directly tested here (scripted action sequences → native status + score fields)
- Inherited from prior validation (upstream Lander.js collision rules; Landscape seed 12039)

Does not claim pixel-identical browser vs headless GPU rendering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import reference_continuous_command  # noqa: E402
from env.starts import PAD_MID_X, derive_short_horizon_start, resolve_start  # noqa: E402

OUT = ROOT / "outputs" / "parity"


def open_env(max_frames: int = 8000) -> ApolloLanderGym:
    return ApolloLanderGym(
        action_repeat=1,
        max_physics_frames=max_frames,
        start_mode="research",
        start_override=resolve_start("pilot_near"),
        headless=True,
        port=18770,
    )


def run_until_done(env, controller) -> dict:
    while True:
        obs, reward, term, trunc, info = controller()
        if term or trunc:
            return {
                "status": info.get("status"),
                "landed": bool(info.get("landed")),
                "perfect": bool(info.get("perfect")),
                "hard_landing": bool(info.get("hard_landing")),
                "crashed": bool(info.get("crashed")),
                "timeout": bool(info.get("result", {}).get("timeout")),
                "native_score": info.get("native_score"),
                "physics_frames": info.get("physics_frames"),
                "fuel_remaining": info.get("fuel_remaining"),
                "terminated": bool(term),
                "truncated": bool(trunc),
            }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    env = open_env()
    results: dict = {
        "engine": "upstream-original",
        "directly_tested": [],
        "inherited_assumptions": [
            "Collision / LANDED rules from vendored Lander.js (rotation==0, vy thresholds)",
            "Terrain from Landscape.js noise.seed(12039) — pad x∈[6873.6,7052.8]",
            "Headless Chromium uses same JS as browser page; GPU raster may differ cosmetically",
        ],
        "outcomes": {},
        "passed": True,
        "failures": [],
    }
    try:
        # A) Perfect landing via continuous reference
        env.start_override = resolve_start("pilot_near")
        obs, info = env.reset(seed=0)

        def ref_step():
            nonlocal obs, info
            cmd = reference_continuous_command(info["raw"])
            obs, r, term, trunc, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
            return obs, r, term, trunc, info

        perfect = run_until_done(env, ref_step)
        results["outcomes"]["reference_perfect_or_land"] = perfect
        results["directly_tested"].append("reference_continuous → native landed/perfect + score")
        if not perfect["landed"]:
            results["passed"] = False
            results["failures"].append("reference_did_not_land")

        # B) Crash: no-op from pilot_near
        env.start_override = resolve_start("pilot_near")
        obs, info = env.reset(seed=1)

        def noop_step():
            nonlocal obs, info
            obs, r, term, trunc, info = env.step(np.array([0, 1], dtype=np.int64))
            return obs, r, term, trunc, info

        crash = run_until_done(env, noop_step)
        results["outcomes"]["noop_crash"] = crash
        results["directly_tested"].append("noop → crash")
        if not crash["crashed"]:
            results["passed"] = False
            results["failures"].append("noop_not_crash")

        # C) Timeout: max_physics_frames small, hover thrust
        env_short = ApolloLanderGym(
            action_repeat=1,
            max_physics_frames=40,
            start_mode="research",
            start_override={
                "x": PAD_MID_X,
                "y": 400.0,
                "vx": 0.0,
                "vy": 0.0,
                "rotation": 0.0,
                "fuel": 1000.0,
                "scale": 0.25,
            },
            headless=True,
            port=18770,
        )
        try:
            obs, info = env_short.reset(seed=2)

            def hover_step():
                nonlocal obs, info
                # partial thrust upright — delay contact past frame budget
                obs, r, term, trunc, info = env_short.step_absolute(0.35, 0.0, repeats=1)
                return obs, r, term, trunc, info

            timeout = run_until_done(env_short, hover_step)
        finally:
            env_short.close()
        results["outcomes"]["forced_timeout"] = timeout
        results["directly_tested"].append("short max_frames + hover → truncated timeout")
        if not timeout["timeout"] or not timeout["truncated"]:
            results["passed"] = False
            results["failures"].append("timeout_not_observed")

        # D) Hard landing attempt: upright with high vy near pad (scripted)
        # Drop from low altitude with zero thrust, upright — may hard-land or crash
        env.start_override = {
            "x": PAD_MID_X,
            "y": 640.0,
            "vx": 0.0,
            "vy": 0.20,
            "rotation": 0.0,
            "fuel": 1000.0,
            "scale": 0.25,
        }
        obs, info = env.reset(seed=3)

        def drop_step():
            nonlocal obs, info
            obs, r, term, trunc, info = env.step_absolute(0.0, 0.0, repeats=1)
            return obs, r, term, trunc, info

        hard = run_until_done(env, drop_step)
        results["outcomes"]["upright_drop"] = hard
        results["directly_tested"].append(
            "upright free-drop near pad → hard_landing or crash (native classifier)"
        )
        if hard["status"] not in ("hard_landing", "crashed", "landed"):
            results["passed"] = False
            results["failures"].append("unexpected_drop_status")

        # E) Reset reproducibility under varied short-horizon schedule
        s1 = derive_short_horizon_start("sh_tilt30_low", 42)
        s2 = derive_short_horizon_start("sh_tilt30_low", 42)
        s3 = derive_short_horizon_start("sh_tilt30_low", 43)
        results["start_schedule"] = {
            "seed42_repro": s1 == s2,
            "seed42_vs_43_differ": s1 != s3,
            "sample_42": s1,
            "sample_43": s3,
        }
        results["directly_tested"].append("short_horizon.v1 seed reproducibility + variation")
        if s1 != s2 or s1 == s3:
            results["passed"] = False
            results["failures"].append("start_schedule_broken")

        # F) Dual reset same seed same start → identical raw x after 10 steps
        env.start_override = s1
        obs, info = env.reset(seed=42)
        traj = []
        for _ in range(10):
            obs, _, term, trunc, info = env.step(np.array([2, 1], dtype=np.int64))
            traj.append((float(info["raw"]["x"]), float(info["raw"]["vy"])))
            if term or trunc:
                break
        env.start_override = s1
        obs, info = env.reset(seed=42)
        traj2 = []
        for _ in range(10):
            obs, _, term, trunc, info = env.step(np.array([2, 1], dtype=np.int64))
            traj2.append((float(info["raw"]["x"]), float(info["raw"]["vy"])))
            if term or trunc:
                break
        results["trace_repro"] = {"match": traj == traj2, "len": len(traj)}
        results["directly_tested"].append("action-trace reproducibility (physics fields)")
        if traj != traj2:
            results["passed"] = False
            results["failures"].append("trace_not_reproducible")

    finally:
        env.close()

    path = OUT / "parity_outcomes.json"
    path.write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    if not results["passed"]:
        raise SystemExit("parity outcomes failed")


if __name__ == "__main__":
    main()
