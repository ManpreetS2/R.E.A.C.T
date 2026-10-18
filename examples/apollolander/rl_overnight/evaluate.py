#!/usr/bin/env python3
"""Frozen-policy evaluation on upstream backend (native landing metrics)."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import torch

from rewardbench.rl.env import EnvConfig
from rewardbench.rl.policy import ActorCritic
from rewardbench.rl.reserved_seeds import assert_seeds_allowed
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv

HERE = Path(__file__).resolve().parent


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    p = successes / n
    denom = 1 + z**2 / n
    centre = p + z**2 / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return ((centre - margin) / denom, (centre + margin) / denom)


def run_policy(
    env: ApolloLanderUpstreamEnv,
    policy: ActorCritic | None,
    seeds: list[int],
    deterministic: bool = True,
    random_open_loop: bool = False,
) -> dict[str, Any]:
    assert_seeds_allowed(seeds, context="overnight.evaluate")
    rows = []
    for seed in seeds:
        obs, info = env.reset(seed)
        done = False
        total_r = 0.0
        last_info = info
        steps = 0
        while not done:
            if random_open_loop:
                action = int(np.random.randint(0, env.n_actions))
            else:
                assert policy is not None
                with torch.no_grad():
                    dist, _ = policy.forward(torch.as_tensor(obs, dtype=torch.float32).unsqueeze(0))
                    action = int(torch.argmax(dist.probs, dim=-1).item()) if deterministic else int(
                        dist.sample().item()
                    )
            obs, reward, terminated, truncated, step_info = env.step(action)
            total_r += float(reward)
            last_info = step_info
            steps += 1
            done = bool(terminated or truncated)
        rows.append(
            {
                "seed": seed,
                "return": total_r,
                "status": last_info.get("status"),
                "landed": bool(last_info.get("landed")),
                "crashed": bool(last_info.get("crashed")),
                "timed_out": bool(last_info.get("timed_out")),
                "fuel_used": float(last_info.get("fuel_used", 0.0)),
                "steps": int(last_info.get("steps", steps)),
                "start": info.get("start"),
            }
        )
    n = len(rows)
    lands = sum(1 for r in rows if r["landed"])
    crashes = sum(1 for r in rows if r["crashed"])
    timeouts = sum(1 for r in rows if r["timed_out"])
    perfect = sum(1 for r in rows if r["status"] == "landed")
    hard = sum(1 for r in rows if r["status"] == "hard_landing")
    returns = [r["return"] for r in rows]
    fuels = [max(0.0, 1000.0 - r["fuel_used"]) for r in rows]
    durations = [r["steps"] for r in rows]
    lo, hi = wilson_ci(lands, n)
    return {
        "n": n,
        "perfect_rate": perfect / n,
        "hard_rate": hard / n,
        "landing_rate": lands / n,
        "landing_wilson_95": [lo, hi],
        "crash_rate": crashes / n,
        "timeout_rate": timeouts / n,
        "mean_return": float(np.mean(returns)),
        "median_return": float(np.median(returns)),
        "mean_fuel_remaining": float(np.mean(fuels)),
        "median_fuel_remaining": float(np.median(fuels)),
        "mean_duration_steps": float(np.mean(durations)),
        "median_duration_steps": float(np.median(durations)),
        "episodes": rows,
    }


def load_policy(ckpt: Path, device: str = "cpu") -> tuple[ActorCritic, dict]:
    payload = torch.load(ckpt, map_location=device, weights_only=False)
    env_cfg = payload.get("env_config", {})
    hidden = int(payload.get("ppo_config", {}).get("hidden", 128))
    policy = ActorCritic(obs_dim=10, n_actions=95, hidden=hidden)
    policy.load_state_dict(payload["policy_state_dict"])
    policy.eval()
    return policy, payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--checkpoints", nargs="+", default=["step0", "final"])
    parser.add_argument("--suite", choices=["dev_validation", "pilot_comparison", "held_out_test"], default="dev_validation")
    parser.add_argument("--include-baselines", action="store_true")
    args = parser.parse_args()

    # Frozen seed suites (documented before outcomes).
    suites = {
        "dev_validation": list(range(5000, 5032)),
        "pilot_comparison": list(range(1000000, 1000032)),
        "held_out_test": list(range(1000100, 1000300)),
    }
    seeds = suites[args.suite]
    assert_seeds_allowed(seeds, context=f"suite:{args.suite}")

    env_cfg = EnvConfig(
        max_steps=8000,
        research_mode=True,
        action_repeat=2,
        physics_backend="upstream_vm_host",
    )
    # Reward mode for eval metrics uses research_shaped numbers for return
    # comparability; native landed/crashed/timeout come from upstream outcomes.
    env = ApolloLanderUpstreamEnv(env_cfg, reward_mode="research_shaped")
    out: dict[str, Any] = {
        "suite": args.suite,
        "seeds": seeds,
        "backend": "upstream_vm_host",
        "policies": {},
    }
    try:
        if args.include_baselines:
            print("baseline: random open-loop", flush=True)
            np.random.seed(0)
            out["policies"]["random_open_loop"] = run_policy(
                env, None, seeds, random_open_loop=True
            )
            print("baseline: untrained net", flush=True)
            untrained = ActorCritic(10, 95, 128)
            out["policies"]["untrained_net"] = run_policy(env, untrained, seeds)

        for tag in args.checkpoints:
            ckpt = args.run_dir / "checkpoints" / f"{tag}.pt"
            if not ckpt.exists():
                print("missing", ckpt)
                continue
            print("eval", tag, flush=True)
            policy, payload = load_policy(ckpt)
            result = run_policy(env, policy, seeds)
            result["checkpoint"] = str(ckpt)
            result["checkpoint_global_step"] = payload.get("global_step")
            out["policies"][tag] = result
            print(
                f"  land={result['landing_rate']:.3f} "
                f"CI={result['landing_wilson_95']} "
                f"crash={result['crash_rate']:.3f} "
                f"timeout={result['timeout_rate']:.3f}",
                flush=True,
            )
    finally:
        env.close()

    dest = args.run_dir / "evaluation" / f"{args.suite}_results.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("Wrote", dest)


if __name__ == "__main__":
    main()
