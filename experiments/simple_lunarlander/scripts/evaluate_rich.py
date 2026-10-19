#!/usr/bin/env python3
"""Held-out native evaluation with outcome / hover diagnostics.

Always uses LunarLander-v3 with NO reward wrappers.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]

# Hover definition matches Experiment B thresholds (for diagnostics only).
UPRIGHT = 0.2
SLOW = 0.5


def classify_outcome(terminated: bool, truncated: bool, last_obs: np.ndarray, ep_reward: float) -> str:
    if truncated and not terminated:
        return "timeout"
    if not terminated:
        return "unknown"
    # Heuristic: resting on both legs near pad with small vertical speed ≈ land.
    legs = float(last_obs[6]) > 0.5 and float(last_obs[7]) > 0.5
    near_pad = abs(float(last_obs[0])) < 0.5 and abs(float(last_obs[1])) < 0.2
    slow_y = abs(float(last_obs[3])) < 0.2
    if legs and near_pad and slow_y:
        return "land_heuristic"
    # Strong signal from native score band (not definitive alone).
    if ep_reward >= 200:
        return "solved_score"
    if ep_reward <= -50:
        return "crash_likely"
    return "terminated_other"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--label", type=str, required=True)
    parser.add_argument("--episodes", type=int, default=50)
    parser.add_argument("--seed-start", type=int, default=50_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    model = PPO.load(str(args.model))
    env = gym.make("LunarLander-v3")

    rows = []
    for i in range(args.episodes):
        seed = args.seed_start + i
        obs, info = env.reset(seed=seed)
        done = truncated = False
        total = 0.0
        steps = 0
        hover_steps = 0
        main_engine = 0
        side_engine = 0
        while not (done or truncated):
            action, _ = model.predict(obs, deterministic=True)
            action = int(action)
            obs, reward, done, truncated, info = env.step(action)
            total += float(reward)
            steps += 1
            angle = abs(float(obs[4]))
            speed = float(np.sqrt(obs[2] ** 2 + obs[3] ** 2))
            if angle < UPRIGHT and speed < SLOW:
                hover_steps += 1
            if action == 2:
                main_engine += 1
            elif action in (1, 3):
                side_engine += 1

        outcome = classify_outcome(done, truncated, obs, total)
        rows.append(
            {
                "seed": seed,
                "reward": total,
                "steps": steps,
                "terminated": bool(done),
                "truncated": bool(truncated),
                "outcome": outcome,
                "hover_steps": hover_steps,
                "hover_fraction": hover_steps / max(steps, 1),
                "main_engine_steps": main_engine,
                "side_engine_steps": side_engine,
                "solved_ge_200": total >= 200,
            }
        )
        print(
            f"{args.label} ep{i:02d} seed={seed} R={total:7.2f} steps={steps:4d} "
            f"hover={hover_steps/max(steps,1):.2f} out={outcome}"
        )

    env.close()
    rewards = np.array([r["reward"] for r in rows], dtype=np.float64)
    steps = np.array([r["steps"] for r in rows], dtype=np.float64)
    hover_frac = np.array([r["hover_fraction"] for r in rows], dtype=np.float64)
    # 95% CI for mean (normal approx)
    se = float(rewards.std(ddof=1) / np.sqrt(len(rewards))) if len(rewards) > 1 else 0.0
    ci95 = 1.96 * se

    outcome_counts = {}
    for r in rows:
        outcome_counts[r["outcome"]] = outcome_counts.get(r["outcome"], 0) + 1

    summary = {
        "label": args.label,
        "model": str(args.model),
        "episodes": args.episodes,
        "seed_start": args.seed_start,
        "eval_reward": "native_only",
        "mean_reward": float(rewards.mean()),
        "median_reward": float(np.median(rewards)),
        "std_reward": float(rewards.std(ddof=1)),
        "ci95_mean": ci95,
        "min_reward": float(rewards.min()),
        "max_reward": float(rewards.max()),
        "solved_ge_200": int(sum(r["solved_ge_200"] for r in rows)),
        "solved_rate": float(np.mean([r["solved_ge_200"] for r in rows])),
        "mean_steps": float(steps.mean()),
        "median_steps": float(np.median(steps)),
        "timeout_count": int(sum(1 for r in rows if r["outcome"] == "timeout")),
        "timeout_rate": float(np.mean([r["outcome"] == "timeout" for r in rows])),
        "mean_hover_fraction": float(hover_frac.mean()),
        "long_episode_ge_800": int(sum(1 for s in steps if s >= 800)),
        "outcome_counts": outcome_counts,
        "fuel_note": "LunarLander-v3 has infinite fuel; engine firings reported instead.",
        "mean_main_engine_steps": float(np.mean([r["main_engine_steps"] for r in rows])),
        "mean_side_engine_steps": float(np.mean([r["side_engine_steps"] for r in rows])),
        "episodes_detail": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n")
    print("\n=== summary ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "episodes_detail"}, indent=2))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
