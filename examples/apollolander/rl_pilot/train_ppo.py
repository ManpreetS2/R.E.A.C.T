#!/usr/bin/env python3
"""Train a randomly initialized PPO policy on ApolloLander (CPU, state obs).

Uses the verified Python physics port for speed. Does not use pretrained
weights, imitation, or demonstration_guidance_controller for training.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from rewardbench.rl.env import EnvConfig
from rewardbench.rl.ppo import PPOConfig, PPOTrainer

HERE = Path(__file__).resolve().parent


def load_configs(path: Path) -> tuple[EnvConfig, PPOConfig, dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    env_raw = dict(raw["env"])
    # Strip documentation-only keys not on EnvConfig.
    for key in ("action_space", "physics_backend_train", "physics_backend_eval"):
        env_raw.pop(key, None)
    env_cfg = EnvConfig(
        max_steps=int(env_raw["max_steps"]),
        research_mode=bool(env_raw["research_mode"]),
        start_schedule_version=str(env_raw["start_schedule_version"]),
        vary_fuel=bool(env_raw["vary_fuel"]),
        action_repeat=int(env_raw["action_repeat"]),
        bonuses=bool(env_raw["bonuses"]),
        locked_camera=bool(env_raw["locked_camera"]),
        observation_kind=str(raw.get("observation_kind", "state-observation RL pilot, not visual learning")),
    )
    ppo_raw = dict(raw["ppo"])
    ppo_cfg = PPOConfig(**{k: ppo_raw[k] for k in PPOConfig.__dataclass_fields__ if k in ppo_raw})
    return env_cfg, ppo_cfg, raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.yaml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--total-env-steps", type=int, default=None)
    parser.add_argument("--run-name", type=str, default=None)
    args = parser.parse_args()

    env_cfg, ppo_cfg, raw = load_configs(args.config)
    if args.total_env_steps is not None:
        ppo_cfg.total_env_steps = args.total_env_steps
    if args.run_name is not None:
        ppo_cfg.run_name = args.run_name
    out = args.output or (HERE / "results" / ppo_cfg.run_name)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config_snapshot.yaml").write_text(args.config.read_text(encoding="utf-8"), encoding="utf-8")

    print("observation_kind:", env_cfg.observation_kind)
    print("env_config_hash:", env_cfg.config_hash())
    print("output:", out)
    trainer = PPOTrainer(env_cfg, ppo_cfg, out)
    summary = trainer.train()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
