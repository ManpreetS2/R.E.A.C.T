#!/usr/bin/env python3
"""Phase 3: record rgb_array gameplay videos via Gymnasium RecordVideo."""

from __future__ import annotations

import argparse
from pathlib import Path

import gymnasium as gym
from gymnasium.wrappers import RecordVideo
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]


def run_episode(env, policy_fn, seed: int) -> float:
    obs, info = env.reset(seed=seed)
    done = truncated = False
    total = 0.0
    while not (done or truncated):
        action = policy_fn(obs)
        obs, reward, done, truncated, info = env.step(action)
        total += float(reward)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=None, help="PPO zip; omit for random")
    parser.add_argument("--label", type=str, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--episodes", type=int, default=1)
    parser.add_argument("--video-dir", type=Path, default=None)
    args = parser.parse_args()

    video_dir = args.video_dir or (ROOT / "videos" / args.label)
    video_dir.mkdir(parents=True, exist_ok=True)

    model = PPO.load(str(args.model)) if args.model else None

    def policy_fn(obs):
        if model is None:
            # Will be replaced per-env below with env.action_space.sample — need env.
            raise RuntimeError("internal")
        action, _ = model.predict(obs, deterministic=True)
        return int(action)

    for ep in range(args.episodes):
        env = gym.make("LunarLander-v3", render_mode="rgb_array")
        env = RecordVideo(
            env,
            video_folder=str(video_dir),
            name_prefix=f"{args.label}_ep{ep}",
            episode_trigger=lambda i: True,
            disable_logger=True,
        )

        def _policy(obs, _env=env):
            if model is None:
                return _env.action_space.sample()
            action, _ = model.predict(obs, deterministic=True)
            return int(action)

        total = run_episode(env, _policy, seed=args.seed + ep)
        print(f"{args.label} ep={ep} reward={total:.2f} videos -> {video_dir}")
        env.close()


if __name__ == "__main__":
    main()
