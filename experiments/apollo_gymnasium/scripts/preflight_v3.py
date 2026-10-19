#!/usr/bin/env python3
"""V3 preflight: must pass before ppo_pilot_v3_contact_Aprime may launch."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym, _potential  # noqa: E402
from env.controllers import noop_action, reference_guidance_action  # noqa: E402
from env.seeds import DEV_EVAL_SEEDS, HELD_OUT_SEEDS, TRAIN_SEED_BASE  # noqa: E402
from env.starts import derive_short_horizon_start  # noqa: E402

OUT = ROOT / "outputs" / "preflight_v3"


def run_unit_tests() -> dict:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(ROOT / "tests" / "test_a_prime_reward.py"),
            "-q",
        ],
        cwd=str(ROOT.parents[1]),
        capture_output=True,
        text=True,
    )
    return {
        "passed": proc.returncode == 0,
        "stdout": proc.stdout[-2000:],
        "stderr": proc.stderr[-2000:],
    }


def test_seed_variation_and_repro() -> dict:
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        timeout_as_terminated=True,
        auto_seed_base=TRAIN_SEED_BASE,
        headless=True,
    )
    failures = []
    try:
        # Same seed → same start
        _, i1 = env.reset(seed=200_000)
        _, i2 = env.reset(seed=200_000)
        if i1["start"] != i2["start"]:
            failures.append("same_seed_different_start")
        # Different seeds → different starts
        _, i3 = env.reset(seed=200_001)
        if i1["start"] == i3["start"]:
            failures.append("different_seeds_same_start")
        # Bare reset() advances and changes start
        starts = []
        for _ in range(5):
            _, info = env.reset()  # no seed
            starts.append(json.dumps(info["start"], sort_keys=True))
        if len(set(starts)) < 2:
            failures.append("bare_reset_reuses_start")
        # derive helper matches env
        expected = derive_short_horizon_start("sh_contact", 200_000)
        if abs(float(i1["start"]["x"]) - expected["x"]) > 1e-6:
            failures.append("env_start_mismatch_vs_derive")
    finally:
        env.close()
    return {"passed": len(failures) == 0, "failures": failures, "bare_reset_unique": len(set(starts))}


def test_trajectory_rewards() -> dict:
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        timeout_as_terminated=True,
        headless=True,
    )
    report: dict = {"passed": True, "failures": [], "cases": {}}
    try:
        # No-op → crash, terminal -100
        obs, info = env.reset(seed=int(DEV_EVAL_SEEDS[0]))
        prev_phi = _potential(obs)
        rewards = []
        while True:
            obs, r, term, trunc, info = env.step(noop_action())
            rewards.append(r)
            if term or trunc:
                break
        report["cases"]["noop"] = {
            "status": info["status"],
            "landed": info["landed"],
            "crashed": info["crashed"],
            "terminal_reward": rewards[-1],
            "terminated": term,
            "truncated": trunc,
            "frames": info["physics_frames"],
        }
        if not info["crashed"] or rewards[-1] != -100.0 or not term or trunc:
            report["passed"] = False
            report["failures"].append("noop_crash_reward")

        # Legal expert → prefer land; if land, terminal +100 or +40
        obs, info = env.reset(seed=int(DEV_EVAL_SEEDS[1]))
        rewards = []
        while True:
            a = reference_guidance_action(info["raw"], env.cmd_angle)
            obs, r, term, trunc, info = env.step(a)
            rewards.append(float(r))
            if term or trunc:
                break
        report["cases"]["ref_legal"] = {
            "status": info["status"],
            "landed": info["landed"],
            "perfect": info["perfect"],
            "terminal_reward": rewards[-1],
            "terminated": term,
            "truncated": trunc,
            "frames": info["physics_frames"],
            "native_score": info.get("native_score"),
            "nonterminal_sample": rewards[0] if len(rewards) > 1 else None,
        }
        if info["landed"]:
            expected_term = 100.0 if info["perfect"] else 40.0
            if rewards[-1] != expected_term or not term or trunc:
                report["passed"] = False
                report["failures"].append("ref_land_reward")
            # Spot-check one nonterminal ≈ 10*dphi - 0.005 (loose: just finite and not ±100)
            if len(rewards) > 1 and abs(rewards[0]) >= 100:
                report["passed"] = False
                report["failures"].append("ref_nonterminal_looks_terminal")
        else:
            # Feasibility soft-fail: record but do not hard-fail preflight if one seed misses
            report["cases"]["ref_legal"]["note"] = "did_not_land_on_this_dev_seed"

        # Forced timeout
        env_t = ApolloLanderGym(
            action_repeat=1,
            max_physics_frames=30,
            start_mode="research",
            start_template="sh_contact",
            reward_mode="progress_a_prime",
            headless=True,
            port=18771,
        )
        try:
            obs, info = env_t.reset(seed=int(DEV_EVAL_SEEDS[2]))
            while True:
                obs, r, term, trunc, info = env_t.step(np.array([2, 1], dtype=np.int64))
                if term or trunc:
                    break
            report["cases"]["timeout"] = {
                "status": info["status"],
                "reward": r,
                "terminated": term,
                "truncated": trunc,
                "timeout": info.get("timeout"),
            }
            if (
                info["status"] != "timeout"
                or r != -100.0
                or not term
                or trunc
                or info["landed"]
                or info["crashed"]
            ):
                report["passed"] = False
                report["failures"].append("timeout_semantics")
        finally:
            env_t.close()
    finally:
        env.close()

    # Seed pool hygiene
    diag = set(range(0, 10_000)) | set(range(50_000, 50_100))
    if set(DEV_EVAL_SEEDS) & diag or set(HELD_OUT_SEEDS) & diag:
        report["passed"] = False
        report["failures"].append("seed_pool_overlaps_diagnostics")
    report["seed_pools"] = {
        "train_base": TRAIN_SEED_BASE,
        "dev": list(DEV_EVAL_SEEDS[:3]) + ["..."],
        "heldout": list(HELD_OUT_SEEDS[:3]) + ["..."],
    }
    return report


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {
        "unit_tests": run_unit_tests(),
        "seed_variation": test_seed_variation_and_repro(),
        "trajectories": test_trajectory_rewards(),
    }
    results["all_passed"] = all(
        results[k]["passed"] for k in ("unit_tests", "seed_variation", "trajectories")
    )
    (OUT / "preflight_report.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    if not results["all_passed"]:
        raise SystemExit("PREFLIGHT FAILED — do not launch PPO")
    print("PREFLIGHT PASSED", flush=True)


if __name__ == "__main__":
    main()
