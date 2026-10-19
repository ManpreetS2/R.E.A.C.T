#!/usr/bin/env python3
"""Evaluation-only validation of frozen V3-40k on a preregistered ≥100 sh_contact pool.

No training. No checkpoint selection. No tuning. Results are descriptive only.
sh_contact ≠ original full-game start — do not relabel.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import noop_action, random_action, reference_guidance_action  # noqa: E402
from env.seeds import CHAMPION_VAL_SEEDS, DEV_EVAL_SEEDS, V5_HELD_OUT_SEEDS  # noqa: E402

OUT = ROOT / "outputs" / "champion_validation_v3_40k"
V3_40K = (
    ROOT
    / "models"
    / "ppo_pilot_v3_contact_Aprime"
    / "checkpoints"
    / "ppo_apollo_40000_steps.zip"
)
V3_STEP0 = ROOT / "models" / "ppo_pilot_v3_contact_Aprime" / "step0_random_init.zip"
FREEZE_MARKER = ROOT / "models" / "ppo_pilot_v3_contact_Aprime" / "V3_40K_INCUMBENT.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def make_env(port: int) -> ApolloLanderGym:
    return ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        commitment_shaping=False,
        timeout_as_terminated=True,
        headless=True,
        port=port,
    )


def classify_failure(info: dict, series: list[dict]) -> str | None:
    if info.get("landed"):
        return None
    if info.get("crashed"):
        raw = info["raw"]
        if abs(float(raw.get("rotation", 0))) > 15:
            return "crash_attitude"
        if abs(float(raw.get("vy", 0))) > 0.2 or abs(float(raw.get("vx", 0))) > 0.2:
            return "crash_velocity"
        if abs(float(raw.get("dx", 0))) > 40:
            return "crash_offpad_drift"
        return "crash"
    if info.get("timeout"):
        min_alt = min(s["alt"] for s in series)
        alt_last = series[-1]["alt"]
        if min_alt < 20 and alt_last > 50:
            return "timeout_post_approach_reascent"
        if alt_last > 100 and abs(series[-1]["vy"]) < 0.2:
            return "timeout_hover"
        if alt_last > 100:
            return "timeout_high_altitude"
        return "timeout"
    return "unknown"


def run_episode(env, policy: str, model, seed: int, *, rng) -> dict:
    obs, info = env.reset(seed=seed)
    start = dict(info.get("start") or {})
    series = []
    while True:
        if policy == "noop":
            a = noop_action(obs)
        elif policy == "random":
            a = random_action(rng)
        elif policy == "reference":
            a = reference_guidance_action(info["raw"], env.cmd_angle)
        elif policy == "ppo":
            a, _ = model.predict(obs, deterministic=True)
        else:
            raise ValueError(policy)
        obs, _, term, trunc, info = env.step(a)
        raw = info["raw"]
        series.append(
            {
                "t": info["physics_frames"],
                "alt": float(raw["altitude"]),
                "vy": float(raw["vy"]),
                "vx": float(raw["vx"]),
                "rot": float(raw["rotation"]),
                "dx": float(raw["dx"]),
            }
        )
        if term or trunc:
            break
    return {
        "seed": seed,
        "policy": policy,
        "status": info.get("status"),
        "landed": bool(info.get("landed")),
        "perfect": bool(info.get("perfect")),
        "hard_landing": bool(info.get("hard_landing")),
        "crashed": bool(info.get("crashed")),
        "timeout": bool(info.get("timeout")),
        "physics_frames": info.get("physics_frames"),
        "fuel_remaining": info.get("fuel_remaining"),
        "native_score": info.get("native_score"),
        "start": start,
        "min_alt": float(min(s["alt"] for s in series)),
        "max_alt": float(max(s["alt"] for s in series)),
        "failure_mode": classify_failure(info, series),
    }


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    land = sum(r["landed"] for r in rows)
    perfect = sum(r["perfect"] for r in rows)
    hard = sum(r["hard_landing"] for r in rows)
    crash = sum(r["crashed"] for r in rows)
    timeout = sum(r["timeout"] for r in rows)
    lo, hi = wilson_ci(land, n)
    modes: dict[str, int] = {}
    for r in rows:
        m = r.get("failure_mode")
        if m:
            modes[m] = modes.get(m, 0) + 1
    return {
        "n": n,
        "land_count": land,
        "perfect_count": perfect,
        "hard_landing_count": hard,
        "crash_count": crash,
        "timeout_count": timeout,
        "land_rate": land / n,
        "perfect_rate": perfect / n,
        "hard_landing_rate": hard / n,
        "crash_rate": crash / n,
        "timeout_rate": timeout / n,
        "land_rate_wilson95": [lo, hi],
        "mean_physics_frames": float(np.mean([r["physics_frames"] for r in rows])),
        "mean_fuel_remaining": float(
            np.mean([float(r["fuel_remaining"] or 0) for r in rows])
        ),
        "mean_native_score": float(
            np.mean([float(r["native_score"] or 0) for r in rows])
        ),
        "failure_modes": modes,
        "reascent_count": modes.get("timeout_post_approach_reascent", 0),
        "reascent_rate": modes.get("timeout_post_approach_reascent", 0) / max(n, 1),
    }


def eval_policy(label: str, policy: str, model_path: Path | None, seeds: list[int], port: int) -> dict:
    model = PPO.load(str(model_path)) if model_path else None
    env = make_env(port)
    rng = np.random.default_rng(0)
    rows = []
    try:
        for i, seed in enumerate(seeds):
            if i % 20 == 0:
                print(f"  {label} {i}/{len(seeds)}", flush=True)
            for attempt in range(3):
                try:
                    if attempt:
                        env.close()
                        env = make_env(port)
                    rows.append(run_episode(env, policy, model, seed, rng=rng))
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    print(f"retry {label} seed={seed}: {exc}", flush=True)
    finally:
        env.close()
    summary = summarize(rows)
    summary["label"] = label
    summary["model"] = str(model_path) if model_path else None
    summary["model_sha256"] = sha256(model_path) if model_path else None
    summary["episodes"] = rows
    return summary


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    seeds = list(CHAMPION_VAL_SEEDS)
    assert len(seeds) >= 100, len(seeds)
    # Disjoint from contaminated pools
    contaminated = set(DEV_EVAL_SEEDS) | set(range(300_000, 300_020)) | set(
        range(400_000, 400_020)
    ) | set(V5_HELD_OUT_SEEDS) | set(range(100_000, 100_000 + 60_000))
    overlap = set(seeds) & contaminated
    assert not overlap, f"champion val seeds overlap contaminated: {sorted(overlap)[:10]}"

    digest = sha256(V3_40K)
    marker = {
        "path": str(V3_40K),
        "sha256": digest,
        "role": "frozen_champion_evaluation_only",
        "do_not_overwrite": True,
        "start_distribution": "sh_contact",
        "not_original_full_game": True,
        "validation_pool": "CHAMPION_VAL_SEEDS",
        "n_validation_seeds": len(seeds),
        "seed_range": [min(seeds), max(seeds)],
    }
    FREEZE_MARKER.write_text(json.dumps(marker, indent=2))
    (OUT / "champion_freeze.json").write_text(json.dumps(marker, indent=2))

    results = {}
    specs = [
        ("v3_40k_det", "ppo", V3_40K, 19400),
        ("v3_step0_det", "ppo", V3_STEP0, 19401),
        ("noop", "noop", None, 19402),
        ("random", "random", None, 19403),
        ("reference", "reference", None, 19404),
    ]
    for label, policy, path, port in specs:
        print(f"=== {label} n={len(seeds)} ===", flush=True)
        s = eval_policy(label, policy, path, seeds, port)
        (OUT / f"{label}.json").write_text(json.dumps(s, indent=2))
        results[label] = {k: v for k, v in s.items() if k != "episodes"}

    report = {
        "purpose": "evaluation_only_champion_validation",
        "no_training": True,
        "no_tuning": True,
        "start_template": "sh_contact",
        "disclaimer": (
            "These results measure sh_contact short-horizon starts only. "
            "They are NOT original_fixed / full-game ApolloLander performance."
        ),
        "champion_model": marker,
        "seed_pool": {
            "name": "CHAMPION_VAL_SEEDS",
            "n": len(seeds),
            "first": seeds[0],
            "last": seeds[-1],
        },
        "by_policy": results,
        "v3_40k_land_wilson95": results["v3_40k_det"]["land_rate_wilson95"],
        "v3_40k_land_rate": results["v3_40k_det"]["land_rate"],
    }
    (OUT / "CHAMPION_VALIDATION.json").write_text(json.dumps(report, indent=2))

    v3 = results["v3_40k_det"]
    md = [
        "# Champion validation — frozen V3-40k (evaluation only)",
        "",
        f"**Model SHA-256:** `{digest}`",
        f"**Pool:** `CHAMPION_VAL_SEEDS` n={len(seeds)} (`{seeds[0]}`–`{seeds[-1]}`)",
        "**Start:** `sh_contact` only — **not** original full-game start.",
        "**No training / no tuning / no checkpoint selection.**",
        "",
        "| Policy | Land | Perfect | Hard | Crash | Timeout | Reascent | Mean frames | Mean fuel | Land Wilson 95% |",
        "|--------|-----:|--------:|-----:|------:|--------:|---------:|------------:|----------:|----------------:|",
    ]
    for key, label in [
        ("v3_40k_det", "V3-40k det"),
        ("v3_step0_det", "V3 step-0"),
        ("noop", "No-op"),
        ("random", "Random"),
        ("reference", "Legal reference"),
    ]:
        p = results[key]
        lo, hi = p["land_rate_wilson95"]
        md.append(
            f"| {label} | {p['land_count']}/{p['n']} ({100*p['land_rate']:.1f}%) | "
            f"{p['perfect_count']} | {p['hard_landing_count']} | {p['crash_count']} | "
            f"{p['timeout_count']} | {p.get('reascent_count', 0)} | "
            f"{p['mean_physics_frames']:.0f} | {p['mean_fuel_remaining']:.0f} | "
            f"[{100*lo:.1f}%, {100*hi:.1f}%] |"
        )
    md += [
        "",
        f"V3-40k failure modes: `{v3['failure_modes']}`",
        "",
        "## Claims we are not making",
        "",
        "- Not that V3-40k solves the original game from arbitrary starts.",
        "- Not an unbiased estimate of a fresh training run (checkpoint was DEV-selected).",
        "- Not license to tune hyperparameters on this pool.",
        "",
    ]
    (OUT / "CHAMPION_VALIDATION.md").write_text("\n".join(md))
    print(json.dumps(results["v3_40k_det"], indent=2, default=str)[:2000])
    print("Wrote", OUT / "CHAMPION_VALIDATION.md")


if __name__ == "__main__":
    main()
