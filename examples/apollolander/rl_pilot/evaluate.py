#!/usr/bin/env python3
"""Evaluate checkpoints on development and held-out seeds via the Node adapter.

Includes random-policy and (separately labeled) hand-tuned guidance baselines.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from rewardbench.environments.apollolander import (
    ORIGIN_DETERMINISTIC_MOCK,
    ORIGIN_HAND_SPECIFIED,
    ApolloLanderAdapter,
    demonstration_guidance_controller,
    random_controller,
)
from rewardbench.rl.env import EnvConfig
from rewardbench.rl.node_eval import (
    evaluate_policy_node,
    load_policy,
    policy_action_fn,
    random_network_action_fn,
)
from rewardbench.rl.reserved_seeds import assert_seeds_allowed

HERE = Path(__file__).resolve().parent


def env_from_config(raw: dict[str, Any]) -> EnvConfig:
    env_raw = dict(raw["env"])
    return EnvConfig(
        max_steps=int(env_raw["max_steps"]),
        research_mode=bool(env_raw["research_mode"]),
        start_schedule_version=str(env_raw["start_schedule_version"]),
        vary_fuel=bool(env_raw["vary_fuel"]),
        action_repeat=int(env_raw.get("action_repeat", 1)),
        bonuses=bool(env_raw["bonuses"]),
        locked_camera=bool(env_raw["locked_camera"]),
        observation_kind=str(raw.get("observation_kind", "state-observation RL pilot, not visual learning")),
    )


def evaluate_scripted(
    controller: dict[str, Any],
    seeds: list[int],
    *,
    split: str,
    max_steps: int,
    origin: str,
    model: str,
    research_mode: bool = True,
) -> dict[str, Any]:
    adapter = ApolloLanderAdapter(research_mode=research_mode, max_steps=max_steps)
    assert_seeds_allowed(seeds, context=f"evaluate_scripted.{split}")
    report = adapter.evaluate(
        controller,
        seeds,
        revision=1,
        split=split,
        origin=origin,
        model=model,
        max_steps=max_steps,
    )
    episodes = report["episodes"]
    n = len(episodes)
    land = sum(1 for e in episodes if e["landed"])
    crash = sum(1 for e in episodes if e["crashed"])
    timeout = sum(1 for e in episodes if e["timed_out"])
    rewards = [float(e["reward"]) for e in episodes]
    fuels = [float(e["fuel_used"]) for e in episodes]
    import math

    import numpy as np

    z = 1.96
    mean_r = sum(rewards) / n
    reward_se = float(np.std(rewards, ddof=1) / math.sqrt(n)) if n > 1 else 0.0

    def prop_ci(k: int) -> list[float]:
        p = k / n
        se = math.sqrt(p * (1 - p) / n)
        return [max(0.0, p - z * se), min(1.0, p + z * se)]

    return {
        "model": model,
        "origin": origin,
        "split": split,
        "label": model,
        "physics_backend": (
            "custom Node ApolloLander simulator via ApolloLanderAdapter "
            "(frontend/apollolander/experiment/physics.js)"
        ),
        "summary": {
            "n": n,
            "mean_reward": mean_r,
            "mean_reward_ci95": [mean_r - z * reward_se, mean_r + z * reward_se],
            "landing_rate": land / n,
            "landing_rate_ci95": prop_ci(land),
            "crash_rate": crash / n,
            "crash_rate_ci95": prop_ci(crash),
            "timeout_rate": timeout / n,
            "timeout_rate_ci95": prop_ci(timeout),
            "mean_fuel_used": sum(fuels) / n,
            "landings": land,
            "crashes": crash,
            "timeouts": timeout,
        },
        "episodes": [
            {
                "seed": e["seed"],
                "reward": e["reward"],
                "landed": e["landed"],
                "crashed": e["crashed"],
                "timed_out": e["timed_out"],
                "fuel_used": e["fuel_used"],
                "steps": e["steps"],
                "status": e["status"],
            }
            for e in episodes
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.yaml")
    parser.add_argument("--run-dir", type=Path, required=True, help="Training run directory with checkpoints/")
    parser.add_argument("--checkpoints", nargs="*", default=None, help="Checkpoint tags, e.g. step0 step250000 final")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--skip-baselines", action="store_true")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    env_cfg = env_from_config(raw)
    eval_cfg = raw["eval"]
    dev_seeds = list(eval_cfg["development_seeds"])
    hold_seeds = list(eval_cfg["held_out_seeds"])
    assert_seeds_allowed(dev_seeds, context="evaluate.development")
    assert_seeds_allowed(hold_seeds, context="evaluate.held_out")
    out = args.output or (args.run_dir / "evaluation")
    out.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "observation_kind": env_cfg.observation_kind,
        "observation_disclosure": (
            "numerical state observations with shaped rewards "
            "(progress/potential term + fuel penalty); NOT screenshots"
        ),
        "simulator_label": (
            "custom Node ApolloLander simulator "
            "(frontend/apollolander/experiment/physics.js)"
        ),
        "eval_policy_mode": "frozen_deterministic_argmax (no further weight updates)",
        "env_config": env_cfg.to_dict(),
        "env_config_hash": env_cfg.config_hash(),
        "development_seeds": dev_seeds,
        "held_out_seeds": hold_seeds,
        "reserved_seeds_excluded": "2000000..2000015 inclusive",
        "baselines": {},
        "checkpoints": {},
    }

    if not args.skip_baselines:
        print("Evaluating random-policy baseline…", flush=True)
        results["baselines"]["random_policy"] = {
            "development": evaluate_scripted(
                random_controller(0),
                dev_seeds,
                split="development",
                max_steps=env_cfg.max_steps,
                origin=ORIGIN_DETERMINISTIC_MOCK,
                model="baseline-random-0",
            ),
            "held_out": evaluate_scripted(
                random_controller(0),
                hold_seeds,
                split="held_out",
                max_steps=env_cfg.max_steps,
                origin=ORIGIN_DETERMINISTIC_MOCK,
                model="baseline-random-0",
            ),
        }
        print("Evaluating hand-tuned guidance (REFERENCE ONLY)…", flush=True)
        results["baselines"]["hand_tuned_guidance_REFERENCE_ONLY"] = {
            "note": (
                "Separately labeled comparison baseline. NOT used to initialize, "
                "imitate, shape actions, or guide RL training."
            ),
            "development": evaluate_scripted(
                demonstration_guidance_controller(),
                dev_seeds,
                split="development",
                max_steps=env_cfg.max_steps,
                origin=ORIGIN_HAND_SPECIFIED,
                model="hand-specified-guidance",
            ),
            "held_out": evaluate_scripted(
                demonstration_guidance_controller(),
                hold_seeds,
                split="held_out",
                max_steps=env_cfg.max_steps,
                origin=ORIGIN_HAND_SPECIFIED,
                model="hand-specified-guidance",
            ),
        }
        print("Evaluating randomly initialized network (untrained)…", flush=True)
        untrained_fn, _ = random_network_action_fn(seed=0, device=args.device)
        results["baselines"]["untrained_random_init_network"] = {
            "development": evaluate_policy_node(
                untrained_fn,
                dev_seeds,
                split="development",
                max_steps=env_cfg.max_steps,
                env_config=env_cfg,
                model="untrained-mlp",
                origin="rl_random_init_untrained",
            ),
            "held_out": evaluate_policy_node(
                untrained_fn,
                hold_seeds,
                split="held_out",
                max_steps=env_cfg.max_steps,
                env_config=env_cfg,
                model="untrained-mlp",
                origin="rl_random_init_untrained",
            ),
        }

    ckpt_dir = args.run_dir / "checkpoints"
    if args.checkpoints:
        tags = args.checkpoints
    else:
        tags = sorted(p.stem for p in ckpt_dir.glob("*.pt"))
    for tag in tags:
        path = ckpt_dir / f"{tag}.pt"
        if not path.exists():
            print(f"skip missing checkpoint {path}")
            continue
        print(f"Evaluating checkpoint {tag}…", flush=True)
        policy, payload = load_policy(path, device=args.device)
        action_fn = policy_action_fn(policy, device=args.device, deterministic=True)
        results["checkpoints"][tag] = {
            "path": str(path),
            "global_step": payload.get("global_step"),
            "development": evaluate_policy_node(
                action_fn,
                dev_seeds,
                split="development",
                max_steps=env_cfg.max_steps,
                env_config=env_cfg,
                model=f"ppo-{tag}",
                origin="rl_ppo_trained",
            ),
            "held_out": evaluate_policy_node(
                action_fn,
                hold_seeds,
                split="held_out",
                max_steps=env_cfg.max_steps,
                env_config=env_cfg,
                model=f"ppo-{tag}",
                origin="rl_ppo_trained",
            ),
        }
        for split in ("development", "held_out"):
            s = results["checkpoints"][tag][split]["summary"]
            print(
                f"  {tag} {split}: land={s['landing_rate']:.3f} crash={s['crash_rate']:.3f} "
                f"timeout={s['timeout_rate']:.3f} mean_r={s['mean_reward']:.2f}",
                flush=True,
            )

    out_path = out / "evaluation_results.json"
    # Compact: drop heavy per-episode traces from neural evals for the summary file.
    compact = json.loads(json.dumps(results))
    for block in list(compact.get("baselines", {}).values()) + list(compact.get("checkpoints", {}).values()):
        for split_key in ("development", "held_out"):
            if split_key in block and "episodes" in block[split_key]:
                eps = block[split_key]["episodes"]
                block[split_key]["episodes"] = [
                    {
                        "seed": e["seed"],
                        "reward": e["reward"],
                        "landed": e["landed"],
                        "crashed": e["crashed"],
                        "timed_out": e.get("timed_out", e.get("timedOut")),
                        "fuel_used": e["fuel_used"],
                        "steps": e["steps"],
                        "status": e.get("status"),
                        "replay_matched": e.get("replay_matched"),
                    }
                    for e in eps
                ]
    out_path.write_text(json.dumps(compact, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
