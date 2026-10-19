#!/usr/bin/env python3
"""Evaluate policies on native ApolloLander outcomes (training reward ignored for metrics)."""

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
    reference_guidance_action,
)
from env.seeds import DEV_EVAL_SEEDS, HELD_OUT_SEEDS, V4_HELD_OUT_SEEDS  # noqa: E402
from env.starts import SHORT_HORIZON_TEMPLATES, resolve_start  # noqa: E402


def run_episode(env, policy, model, rng, seed: int, deterministic: bool = True) -> dict:
    obs, info = env.reset(seed=seed)
    start = dict(info.get("start") or {})
    while True:
        if policy == "noop":
            action = noop_action(obs)
            obs, _r, term, trunc, info = env.step(action)
        elif policy == "random":
            action = random_action(rng)
            obs, _r, term, trunc, info = env.step(action)
        elif policy == "reference":
            # Legal MultiDiscrete expert (feasibility) — same action space as learner
            action = reference_guidance_action(info["raw"], env.cmd_angle)
            obs, _r, term, trunc, info = env.step(action)
        elif policy == "reference_continuous":
            cmd = reference_continuous_command(info["raw"])
            obs, _r, term, trunc, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
        elif policy == "ppo":
            action, _ = model.predict(obs, deterministic=deterministic)
            obs, _r, term, trunc, info = env.step(action)
        else:
            raise ValueError(policy)
        if term or trunc:
            return {
                "seed": seed,
                "episode_seed": info.get("episode_seed", seed),
                "start": start,
                "policy": policy,
                "deterministic": deterministic if policy == "ppo" else None,
                "status": info.get("status"),
                "landed": bool(info.get("landed")),
                "perfect": bool(info.get("perfect")),
                "hard_landing": bool(info.get("hard_landing")),
                "crashed": bool(info.get("crashed")),
                "timeout": bool(info.get("timeout")),
                "native_score": info.get("native_score"),
                "fuel_remaining": info.get("fuel_remaining"),
                "physics_frames": info.get("physics_frames"),
                "terminated": bool(term),
                "truncated": bool(trunc),
            }


def summarize(rows: list[dict], policies: list[str]) -> dict:
    by = {}
    for policy in policies:
        subset = [r for r in rows if r["policy"] == policy]
        # Split ppo det vs stochastic if mixed
        if policy == "ppo" and any(r.get("deterministic") is False for r in subset):
            for det, label in ((True, "ppo_deterministic"), (False, "ppo_stochastic")):
                sub = [r for r in subset if r.get("deterministic") is det]
                n = len(sub)
                if n == 0:
                    continue
                by[label] = _stats(sub, n)
        else:
            n = len(subset)
            by[policy] = _stats(subset, n)
    return by


def _stats(subset, n):
    return {
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="pilot_near")
    ap.add_argument("--start-template", default=None)
    ap.add_argument("--model", default=None, help="Path to PPO .zip")
    ap.add_argument("--policies", default="noop,random,reference,ppo")
    ap.add_argument(
        "--seed-pool",
        choices=["dev", "heldout", "v4_heldout", "custom"],
        default="dev",
    )
    ap.add_argument("--seed-start", type=int, default=None)
    ap.add_argument("--episodes", type=int, default=None)
    ap.add_argument("--action-repeat", type=int, default=4)
    ap.add_argument("--episode-max-frames", type=int, default=2000)
    ap.add_argument("--ppo-stochastic", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.seed_pool == "dev":
        seeds = list(DEV_EVAL_SEEDS)
    elif args.seed_pool == "heldout":
        seeds = list(HELD_OUT_SEEDS)
    elif args.seed_pool == "v4_heldout":
        seeds = list(V4_HELD_OUT_SEEDS)
    else:
        n = args.episodes or 20
        base = args.seed_start if args.seed_start is not None else 50_000
        seeds = list(range(base, base + n))
    if args.episodes is not None:
        seeds = seeds[: args.episodes]

    kwargs = dict(
        action_repeat=args.action_repeat,
        max_physics_frames=args.episode_max_frames,
        start_mode="research",
        reward_mode="progress_a_prime",  # flags only; metrics use native fields
        headless=True,
        timeout_as_terminated=True,
    )
    if args.start_template:
        if args.start_template not in SHORT_HORIZON_TEMPLATES:
            raise SystemExit(f"unknown template {args.start_template}")
        kwargs["start_template"] = args.start_template
    else:
        kwargs["start_override"] = resolve_start(args.start)

    env = ApolloLanderGym(**kwargs)
    model = PPO.load(args.model) if args.model else None
    policies = [p.strip() for p in args.policies.split(",") if p.strip()]
    if "ppo" in policies and model is None:
        raise SystemExit("--model required for ppo policy")

    rows = []
    try:
        for policy in policies:
            rng = np.random.default_rng(123)
            for seed in seeds:
                if policy == "ppo" and args.ppo_stochastic:
                    rows.append(
                        run_episode(env, policy, model, rng, seed, deterministic=False)
                    )
                    rows.append(
                        run_episode(env, policy, model, rng, seed, deterministic=True)
                    )
                else:
                    rows.append(
                        run_episode(
                            env,
                            policy,
                            model,
                            rng,
                            seed,
                            deterministic=True,
                        )
                    )
    finally:
        env.close()

    summary = {
        "start": args.start,
        "start_template": args.start_template,
        "seed_pool": args.seed_pool,
        "seeds": seeds,
        "episodes": rows,
        "by_policy": summarize(rows, policies),
    }
    out = (
        Path(args.out)
        if args.out
        else ROOT / "outputs" / "eval" / f"{args.start_template or args.start}_{args.seed_pool}.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary["by_policy"], indent=2))


if __name__ == "__main__":
    main()
