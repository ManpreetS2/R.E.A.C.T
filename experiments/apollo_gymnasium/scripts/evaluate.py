#!/usr/bin/env python3
"""Evaluate policies on native ApolloLander outcomes (training reward ignored)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import (  # noqa: E402
    noop_action,
    random_action,
    reference_continuous_command,
)
from env.starts import resolve_start  # noqa: E402


def run_episode(env, policy, model, rng, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    while True:
        if policy == "noop":
            action = noop_action(obs)
        elif policy == "random":
            action = random_action(rng)
        elif policy == "reference":
            cmd = reference_continuous_command(info["raw"])
            obs, _r, term, trunc, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
            if term or trunc:
                return {
                    "seed": seed,
                    "policy": policy,
                    "status": info.get("status"),
                    "landed": bool(info.get("landed")),
                    "perfect": bool(info.get("perfect")),
                    "hard_landing": bool(info.get("hard_landing")),
                    "crashed": bool(info.get("crashed")),
                    "timeout": bool(info.get("result", {}).get("timeout")),
                    "native_score": info.get("native_score"),
                    "fuel_remaining": info.get("fuel_remaining"),
                    "physics_frames": info.get("physics_frames"),
                }
            continue
        elif policy == "ppo":
            action, _ = model.predict(obs, deterministic=True)
        else:
            raise ValueError(policy)
        obs, _r, term, trunc, info = env.step(action)
        if term or trunc:
            return {
                "seed": seed,
                "policy": policy,
                "status": info.get("status"),
                "landed": bool(info.get("landed")),
                "perfect": bool(info.get("perfect")),
                "hard_landing": bool(info.get("hard_landing")),
                "crashed": bool(info.get("crashed")),
                "timeout": bool(info.get("result", {}).get("timeout")),
                "native_score": info.get("native_score"),
                "fuel_remaining": info.get("fuel_remaining"),
                "physics_frames": info.get("physics_frames"),
            }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="pilot_near")
    ap.add_argument("--model", default=None, help="Path to PPO .zip")
    ap.add_argument("--policies", default="noop,random,reference,ppo")
    ap.add_argument("--episodes", type=int, default=20)
    ap.add_argument("--seed-start", type=int, default=50_000)
    ap.add_argument("--action-repeat", type=int, default=4)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    start = resolve_start(args.start)
    env = ApolloLanderGym(
        action_repeat=args.action_repeat,
        max_physics_frames=8000,
        start_mode="research",
        start_override=start,
        reward_mode="progress_a",  # unused for reporting; native fields only
        headless=True,
    )
    model = PPO.load(args.model) if args.model else None
    policies = [p.strip() for p in args.policies.split(",") if p.strip()]
    if "ppo" in policies and model is None:
        raise SystemExit("--model required for ppo policy")

    rows = []
    try:
        for policy in policies:
            rng = np.random.default_rng(123)
            for i in range(args.episodes):
                seed = args.seed_start + i
                rows.append(run_episode(env, policy, model, rng, seed))
    finally:
        env.close()

    summary: dict = {"start": args.start, "episodes": rows, "by_policy": {}}
    for policy in policies:
        subset = [r for r in rows if r["policy"] == policy]
        n = len(subset)
        summary["by_policy"][policy] = {
            "n": n,
            "land_rate": sum(1 for r in subset if r["landed"]) / max(n, 1),
            "perfect_rate": sum(1 for r in subset if r["perfect"]) / max(n, 1),
            "hard_landing_rate": sum(1 for r in subset if r["hard_landing"]) / max(n, 1),
            "crash_rate": sum(1 for r in subset if r["crashed"]) / max(n, 1),
            "timeout_rate": sum(1 for r in subset if r["timeout"]) / max(n, 1),
            "mean_physics_frames": float(np.mean([r["physics_frames"] for r in subset])),
            "mean_fuel_remaining": float(
                np.mean([float(r["fuel_remaining"] or 0) for r in subset])
            ),
        }

    out = Path(args.out) if args.out else ROOT / "outputs" / "eval" / f"{args.start}_eval.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["by_policy"], indent=2))


if __name__ == "__main__":
    main()
