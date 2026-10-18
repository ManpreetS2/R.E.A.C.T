#!/usr/bin/env python3
"""Play / render a trained PPO policy on any ApolloLander research seed (Node path)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rewardbench.environments.apollolander import ApolloLanderAdapter
from rewardbench.rl.env import EnvConfig
from rewardbench.rl.node_eval import load_policy, policy_action_fn, run_episode_node


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True, help="Episode seed (development or held-out)")
    parser.add_argument("--max-steps", type=int, default=8000)
    parser.add_argument("--render", action="store_true", help="Write MP4 + flight record")
    parser.add_argument("--output", type=Path, default=Path("examples/apollolander/rl_pilot/output/play"))
    parser.add_argument("--deterministic", action="store_true", default=True)
    parser.add_argument("--stochastic", action="store_true")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    policy, payload = load_policy(args.checkpoint, device=args.device)
    env_cfg = EnvConfig(**{k: v for k, v in (payload.get("env_config") or {}).items() if k in EnvConfig.__dataclass_fields__})
    env_cfg = EnvConfig(
        max_steps=args.max_steps,
        research_mode=env_cfg.research_mode,
        start_schedule_version=env_cfg.start_schedule_version,
        vary_fuel=env_cfg.vary_fuel,
        action_repeat=env_cfg.action_repeat,
    )
    action_fn = policy_action_fn(
        policy,
        device=args.device,
        deterministic=not args.stochastic,
    )
    args.output.mkdir(parents=True, exist_ok=True)
    episode = run_episode_node(
        action_fn,
        seed=args.seed,
        max_steps=args.max_steps,
        research_mode=True,
        record=args.render,
        output=args.output if args.render else None,
        model=f"play-{args.checkpoint.stem}",
        origin="rl_ppo_play",
    )
    if episode.get("flight_record_path"):
        adapter = ApolloLanderAdapter(research_mode=True, max_steps=args.max_steps)
        verify = adapter.verify_flight_record(episode["flight_record_path"])
        episode["replay_matched"] = verify["matched"]
        print("replay_matched:", verify["matched"])
    summary = {
        "seed": episode["seed"],
        "reward": episode["reward"],
        "status": episode["status"],
        "landed": episode["landed"],
        "crashed": episode["crashed"],
        "timed_out": episode["timed_out"],
        "steps": episode["steps"],
        "fuel_used": episode["fuel_used"],
        "video_path": episode.get("video_path"),
        "flight_record_path": episode.get("flight_record_path"),
        "observation_kind": "state-observation RL pilot, not visual learning",
        "checkpoint": str(args.checkpoint),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
