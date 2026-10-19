#!/usr/bin/env python3
"""Phase 1: random LunarLander-v3 episodes + one recorded clip.

Prints the 8 observations and episode rewards. No learned policy.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import gymnasium as gym
from gymnasium.wrappers import RecordVideo

ROOT = Path(__file__).resolve().parents[1]
OBS_NAMES = [
    "x_pos",
    "y_pos",
    "x_vel",
    "y_vel",
    "angle",
    "ang_vel",
    "leg_left",
    "leg_right",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--episodes", type=int, default=5)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--record-episode", type=int, default=0, help="0-based index to record")
    parser.add_argument(
        "--video-dir",
        type=Path,
        default=ROOT / "videos" / "phase1_random",
    )
    args = parser.parse_args()

    args.video_dir.mkdir(parents=True, exist_ok=True)

    print("=== Phase 1: random LunarLander-v3 ===")
    print(f"gymnasium env: LunarLander-v3 | episodes={args.episodes} | seed={args.seed}")
    print("observation fields:", ", ".join(f"{i}:{n}" for i, n in enumerate(OBS_NAMES)))
    print()

    totals: list[float] = []

    for ep in range(args.episodes):
        record = ep == args.record_episode
        env = gym.make("LunarLander-v3", render_mode="rgb_array")
        if record:
            env = RecordVideo(
                env,
                video_folder=str(args.video_dir),
                name_prefix=f"random_ep{ep}",
                episode_trigger=lambda i: True,
                disable_logger=True,
            )

        obs, info = env.reset(seed=args.seed + ep)
        done = False
        truncated = False
        ep_reward = 0.0
        steps = 0

        print(f"--- episode {ep} ---")
        print("t=0 obs:", {OBS_NAMES[i]: float(obs[i]) for i in range(8)})

        while not (done or truncated):
            action = env.action_space.sample()
            obs, reward, done, truncated, info = env.step(action)
            ep_reward += float(reward)
            steps += 1
            # Print a few mid-episode snapshots so the 8 numbers are visible.
            if steps in (1, 25, 50) or done or truncated:
                print(
                    f"t={steps} action={action} reward={reward:+.3f} "
                    f"cum={ep_reward:+.2f} "
                    f"obs={[round(float(x), 4) for x in obs]}"
                )

        totals.append(ep_reward)
        print(
            f"episode {ep} finished: steps={steps} total_reward={ep_reward:.2f} "
            f"terminated={done} truncated={truncated}"
        )
        if record:
            print(f"recorded video under: {args.video_dir.resolve()}")
        print()
        env.close()

    print("=== summary ===")
    print(f"episode rewards: {[round(r, 2) for r in totals]}")
    print(f"mean reward: {sum(totals) / len(totals):.2f}")


if __name__ == "__main__":
    main()
