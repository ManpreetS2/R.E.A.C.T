#!/usr/bin/env python3
"""Evaluate a saved PPO model with native LunarLander rewards (no shaping)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import gymnasium as gym
import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--deterministic", action="store_true", default=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    model = PPO.load(str(args.model))
    env = gym.make("LunarLander-v3")

    rewards: list[float] = []
    lengths: list[int] = []
    landings = 0  # native reward >= 200 is "solved"; also track >0 terminal as soft success

    for ep in range(args.episodes):
        obs, info = env.reset(seed=args.seed + ep)
        done = truncated = False
        total = 0.0
        steps = 0
        while not (done or truncated):
            action, _ = model.predict(obs, deterministic=args.deterministic)
            obs, reward, done, truncated, info = env.step(int(action))
            total += float(reward)
            steps += 1
        rewards.append(total)
        lengths.append(steps)
        if total >= 200:
            landings += 1
        print(f"ep {ep:02d}: reward={total:7.2f} steps={steps}")

    env.close()
    arr = np.asarray(rewards, dtype=np.float64)
    summary = {
        "model": str(args.model),
        "episodes": args.episodes,
        "seed": args.seed,
        "mean_reward": float(arr.mean()),
        "std_reward": float(arr.std()),
        "min_reward": float(arr.min()),
        "max_reward": float(arr.max()),
        "solved_count_ge_200": int(landings),
        "solved_rate": float(landings / args.episodes),
        "rewards": [float(x) for x in rewards],
        "lengths": lengths,
    }
    print("\n=== eval summary (native reward) ===")
    print(json.dumps({k: v for k, v in summary.items() if k != "rewards"}, indent=2))

    out = args.out or (ROOT / "outputs" / "eval" / f"{args.model.stem}_eval.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
