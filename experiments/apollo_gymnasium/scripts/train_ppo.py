#!/usr/bin/env python3
"""Bounded PPO pilot on original ApolloLander (≤1M physics frames via action_repeat)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import BaseCallback, CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.starts import resolve_start  # noqa: E402


class PhysicsBudgetCallback(BaseCallback):
    """Stop when cumulative original-game physics frames hit the hard cap."""

    def __init__(self, max_physics_frames: int, action_repeat: int, verbose: int = 0):
        super().__init__(verbose)
        self.max_physics_frames = max_physics_frames
        self.action_repeat = action_repeat

    def _on_step(self) -> bool:
        # SB3 n_steps count Gym steps; convert to physics frames
        physics = int(self.num_timesteps) * self.action_repeat
        if physics >= self.max_physics_frames:
            if self.verbose:
                print(f"Physics budget reached: {physics} >= {self.max_physics_frames}")
            return False
        return True


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", default="pilot_near")
    p.add_argument("--reward-mode", default="progress_a")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--action-repeat", type=int, default=4)
    p.add_argument("--episode-max-frames", type=int, default=8000)
    p.add_argument("--max-physics-frames", type=int, default=200_000)
    p.add_argument("--n-envs", type=int, default=1)
    p.add_argument("--port", type=int, default=18770)
    p.add_argument("--run-name", default="ppo_pilot")
    p.add_argument("--learning-rate", type=float, default=3e-4)
    p.add_argument("--n-steps", type=int, default=256)
    p.add_argument("--batch-size", type=int, default=64)
    p.add_argument("--checkpoint-every-gym-steps", type=int, default=5_000)
    args = p.parse_args()

    # Cap gym timesteps so physics frames ≤ budget
    max_gym_steps = args.max_physics_frames // max(args.action_repeat, 1)
    out = ROOT / "outputs" / args.run_name
    models = ROOT / "models" / args.run_name
    monitor_dir = out / "monitor"
    out.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    monitor_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "start": args.start,
        "reward_mode": args.reward_mode,
        "seed": args.seed,
        "action_repeat": args.action_repeat,
        "max_physics_frames": args.max_physics_frames,
        "max_gym_steps": max_gym_steps,
        "engine": "upstream-original",
        "note": "Training reward is Python-only; native score unchanged.",
    }
    (out / "run_config.json").write_text(json.dumps(meta, indent=2))

    def make_env_logged(rank: int = 0):
        start = resolve_start(args.start)

        def _thunk():
            env = ApolloLanderGym(
                action_repeat=args.action_repeat,
                max_physics_frames=args.episode_max_frames,
                start_mode="research",
                start_override=start,
                reward_mode=args.reward_mode,
                headless=True,
                port=args.port + rank,
            )
            return Monitor(env, filename=str(monitor_dir / f"train_{rank}"))

        return _thunk

    env = DummyVecEnv([make_env_logged(rank=i) for i in range(args.n_envs)])
    # Save step-0 random init for later comparison
    model = PPO(
        "MlpPolicy",
        env,
        learning_rate=args.learning_rate,
        n_steps=args.n_steps,
        batch_size=args.batch_size,
        seed=args.seed,
        verbose=1,
        tensorboard_log=str(ROOT / "logs" / args.run_name),
    )
    init_path = models / "step0_random_init.zip"
    model.save(str(init_path))

    ckpt = CheckpointCallback(
        save_freq=max(args.checkpoint_every_gym_steps // max(args.n_envs, 1), 1),
        save_path=str(models / "checkpoints"),
        name_prefix="ppo_apollo",
    )
    budget = PhysicsBudgetCallback(args.max_physics_frames, args.action_repeat, verbose=1)

    t0 = time.time()
    model.learn(total_timesteps=max_gym_steps, callback=[ckpt, budget], progress_bar=False)
    elapsed = time.time() - t0
    final_path = models / "final_model.zip"
    model.save(str(final_path))
    (out / "train_summary.json").write_text(
        json.dumps(
            {
                **meta,
                "elapsed_sec": elapsed,
                "gym_timesteps": int(model.num_timesteps),
                "approx_physics_frames": int(model.num_timesteps) * args.action_repeat,
                "init_path": str(init_path),
                "final_path": str(final_path),
            },
            indent=2,
        )
    )
    env.close()
    print(f"Saved {final_path}")


if __name__ == "__main__":
    main()
