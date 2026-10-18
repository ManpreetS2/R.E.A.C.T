#!/usr/bin/env python3
"""Phase 4: final evaluation on sealed unseen target-task seeds 1000300–1000499.

Compares: trained (det + stochastic), random, untrained, PR #4 run A final.pt,
and (separately labeled) hand-tuned guidance reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.schema import (  # noqa: E402
    DEMONSTRATION_GUIDANCE,
    guidance_action,
)
from rewardbench.environments.apollolander.starts import CURRICULUM_V3_LEVELS  # noqa: E402
from rewardbench.rl.continuous_policy import ContinuousThrustActorCritic  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.physics_python import ROTATION_BINS, decode_action  # noqa: E402
from rewardbench.rl.policy import ActorCritic  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed  # noqa: E402
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"

# Chosen BEFORE eval outcomes (owner brief).
TARGET_SEEDS = list(range(1_000_300, 1_000_500))  # 1000300–1000499 inclusive = 200 seeds
assert TARGET_SEEDS[0] == 1000300 and TARGET_SEEDS[-1] == 1000499
assert not any(2_000_000 <= s <= 2_000_015 for s in TARGET_SEEDS)


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def summarize(counts: dict[str, int], returns: list[float], fuels: list[float], durs: list[float], n: int) -> dict[str, Any]:
    land = counts["perfect"] + counts["hard"]
    p, lo, hi = wilson_ci(land, n)
    pp, plo, phi = wilson_ci(counts["perfect"], n)
    ph, hlo, hhi = wilson_ci(counts["hard"], n)
    pc, clo, chi = wilson_ci(counts["crash"], n)
    pt, tlo, thi = wilson_ci(counts["timeout"], n)
    return {
        "n": n,
        "counts": counts,
        "landing_rate": p,
        "landing_wilson95": [lo, hi],
        "perfect_rate": pp,
        "perfect_wilson95": [plo, phi],
        "hard_rate": ph,
        "hard_wilson95": [hlo, hhi],
        "crash_rate": pc,
        "crash_wilson95": [clo, chi],
        "timeout_rate": pt,
        "timeout_wilson95": [tlo, thi],
        "mean_return": float(np.mean(returns)) if returns else 0.0,
        "median_return": float(np.median(returns)) if returns else 0.0,
        "mean_fuel_used": float(np.mean(fuels)) if fuels else 0.0,
        "median_fuel_used": float(np.median(fuels)) if fuels else 0.0,
        "mean_duration": float(np.mean(durs)) if durs else 0.0,
        "median_duration": float(np.median(durs)) if durs else 0.0,
    }


def run_policy(
    *,
    name: str,
    seeds: list[int],
    level: str,
    max_steps: int,
    action_fn,
    action_repeat: int = 2,
) -> dict[str, Any]:
    env = ApolloLanderUpstreamEnv(
        EnvConfig(
            max_steps=max_steps,
            research_mode=True,
            start_schedule_version=level,
            vary_fuel=False,
            action_repeat=action_repeat,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        ),
        reward_mode="touchdown_v1",
    )
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0, "other": 0}
    returns: list[float] = []
    fuels: list[float] = []
    durs: list[float] = []
    diag = 0
    landings: list[dict[str, Any]] = []
    try:
        for seed in seeds:
            assert_seed_allowed(seed, context=f"final_eval.{name}")
            obs, info0 = env.reset(seed)
            done = False
            ep_ret = 0.0
            info: dict[str, Any] = {}
            actions_trace: list[dict[str, float | int]] = []
            while not done:
                command = action_fn(obs, seed, info0.get("start"))
                actions_trace.append(command)
                obs, reward, terminated, truncated, info = env.step_command(command)
                ep_ret += reward
                diag += action_repeat
                done = terminated or truncated
            status = info.get("status", "other")
            if status == "landed":
                counts["perfect"] += 1
                landings.append(
                    {
                        "seed": seed,
                        "status": status,
                        "start": info0.get("start"),
                        "steps": info.get("steps"),
                        "native_outcome": info.get("native_outcome"),
                        "native_score": info.get("native_score"),
                        "actions": actions_trace,
                    }
                )
            elif status == "hard_landing":
                counts["hard"] += 1
                landings.append(
                    {
                        "seed": seed,
                        "status": status,
                        "start": info0.get("start"),
                        "steps": info.get("steps"),
                        "native_outcome": info.get("native_outcome"),
                        "native_score": info.get("native_score"),
                        "actions": actions_trace,
                    }
                )
            elif status == "crashed":
                counts["crash"] += 1
            elif status == "timeout":
                counts["timeout"] += 1
            else:
                counts["other"] += 1
            returns.append(ep_ret)
            fuels.append(float(info.get("fuel_used", 0)))
            durs.append(float(info.get("steps", 0)))
    finally:
        env.close()
    out = summarize(counts, returns, fuels, durs, len(seeds))
    out["name"] = name
    out["level"] = level
    out["diagnostic_frames"] = diag
    out["landings"] = landings
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--max-steps", type=int, default=8000)
    parser.add_argument("--run-dir", type=Path, default=None)
    args = parser.parse_args()

    device = torch.device("cpu")
    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    continuous = ContinuousThrustActorCritic(hidden=int(ckpt.get("cfg", {}).get("hidden", 128))).to(device)
    continuous.load_state_dict(ckpt["policy"])
    continuous.eval()
    ckpt_sha = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()

    untrained = ContinuousThrustActorCritic(hidden=128).to(device)
    torch.manual_seed(42)
    untrained.reset_parameters()
    untrained.eval()

    rng = np.random.default_rng(0)

    def act_trained_det(obs, seed, start):
        with torch.no_grad():
            t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
            thrust, rot_idx, _ = continuous.act_deterministic(t)
            return {
                "thrust": float(thrust.item()),
                "rotation": int(continuous.decode_rotation(rot_idx).item()),
            }

    def act_trained_stoch(obs, seed, start):
        with torch.no_grad():
            t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
            thrust, rot_idx, _, _, _ = continuous.act(t)
            return {
                "thrust": float(thrust.item()),
                "rotation": int(continuous.decode_rotation(rot_idx).item()),
            }

    def act_untrained(obs, seed, start):
        with torch.no_grad():
            t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
            thrust, rot_idx, _ = untrained.act_deterministic(t)
            return {
                "thrust": float(thrust.item()),
                "rotation": int(untrained.decode_rotation(rot_idx).item()),
            }

    def act_random(obs, seed, start):
        return {"thrust": float(rng.uniform(0, 1)), "rotation": int(rng.choice(ROTATION_BINS))}

    def act_guidance(obs, seed, start):
        # REFERENCE ONLY
        raw = {
            "dx": float(obs[0] * 8000.0) if False else None,
        }
        # obs is normalized — recover from env by using guidance on denormalized via session.
        # Simpler: use host observation fields through a side channel — evaluate via
        # re-deriving from start is wrong. Instead step using guidance on last raw obs
        # stored on the closure.
        return guidance_action(act_guidance.last_raw, DEMONSTRATION_GUIDANCE)  # type: ignore[attr-defined]

    # Guidance needs raw observations. Wrap env loop specially below.

    out_dir = args.output or (args.run_dir or args.checkpoint.parent.parent) / "evaluation"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    results: dict[str, Any] = {
        "protocol": {
            "seeds": [TARGET_SEEDS[0], TARGET_SEEDS[-1]],
            "n": len(TARGET_SEEDS),
            "level": "apollolander.starts.v1",
            "chosen_before_outcomes": True,
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": ckpt_sha,
            "max_steps": args.max_steps,
        },
        "agents": {},
        "per_level": {},
    }

    print("Evaluating trained deterministic…", flush=True)
    results["agents"]["trained_deterministic"] = run_policy(
        name="trained_deterministic",
        seeds=TARGET_SEEDS,
        level="apollolander.starts.v1",
        max_steps=args.max_steps,
        action_fn=act_trained_det,
    )
    # Persist any success evidence immediately.
    for land in results["agents"]["trained_deterministic"].get("landings", []):
        evid = out_dir / f"SUCCESS_landing_seed{land['seed']}.json"
        payload = {
            **land,
            "checkpoint": str(args.checkpoint),
            "checkpoint_sha256": ckpt_sha,
            "env_version": "upstream_vm_host",
            "schedule": "apollolander.starts.v1",
        }
        evid.write_text(json.dumps(payload) + "\n")
        print("SUCCESS EVIDENCE", evid, flush=True)

    print("Evaluating trained stochastic…", flush=True)
    results["agents"]["trained_stochastic"] = run_policy(
        name="trained_stochastic",
        seeds=TARGET_SEEDS,
        level="apollolander.starts.v1",
        max_steps=args.max_steps,
        action_fn=act_trained_stoch,
    )

    print("Evaluating random…", flush=True)
    results["agents"]["random"] = run_policy(
        name="random",
        seeds=TARGET_SEEDS,
        level="apollolander.starts.v1",
        max_steps=args.max_steps,
        action_fn=act_random,
    )

    print("Evaluating untrained…", flush=True)
    results["agents"]["untrained"] = run_policy(
        name="untrained",
        seeds=TARGET_SEEDS,
        level="apollolander.starts.v1",
        max_steps=args.max_steps,
        action_fn=act_untrained,
    )

    # PR #4 run A discrete policy comparison
    run_a = ROOT / "examples/apollolander/rl_overnight/results/A_reproduce_upstream_s0/checkpoints/final.pt"
    if run_a.is_file():
        print("Evaluating PR #4 run A final.pt…", flush=True)
        discrete = ActorCritic(hidden=128).to(device)
        data = torch.load(run_a, map_location=device, weights_only=False)
        discrete.load_state_dict(data["policy"] if "policy" in data else data)
        discrete.eval()

        def act_a(obs, seed, start):
            with torch.no_grad():
                t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                dist, _ = discrete.forward(t)
                a = torch.argmax(dist.logits, dim=-1)
                return decode_action(int(a.item()))

        results["agents"]["pr4_runA_final_det"] = run_policy(
            name="pr4_runA_final_det",
            seeds=TARGET_SEEDS,
            level="apollolander.starts.v1",
            max_steps=args.max_steps,
            action_fn=act_a,
        )

    # Guidance REFERENCE ONLY — custom loop with raw observations
    print("Evaluating guidance REFERENCE ONLY…", flush=True)
    env = ApolloLanderUpstreamEnv(
        EnvConfig(
            max_steps=args.max_steps,
            research_mode=True,
            start_schedule_version="apollolander.starts.v1",
            vary_fuel=False,
            action_repeat=2,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        ),
        reward_mode="touchdown_v1",
    )
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0, "other": 0}
    returns: list[float] = []
    fuels: list[float] = []
    durs: list[float] = []
    diag = 0
    try:
        for seed in TARGET_SEEDS:
            assert_seed_allowed(seed, context="final_eval.guidance")
            obs, _ = env.reset(seed)
            # Pull raw observation from host
            raw = env.session.call({"cmd": "observe"})["observation"]
            done = False
            ep_ret = 0.0
            info: dict[str, Any] = {}
            while not done:
                command = guidance_action(raw, DEMONSTRATION_GUIDANCE)
                obs, reward, terminated, truncated, info = env.step_command(command)
                raw = env.session.call({"cmd": "observe"})["observation"]
                ep_ret += reward
                diag += 2
                done = terminated or truncated
            status = info.get("status", "other")
            counts[{"landed": "perfect", "hard_landing": "hard", "crashed": "crash", "timeout": "timeout"}.get(status, "other")] += 1
            returns.append(ep_ret)
            fuels.append(float(info.get("fuel_used", 0)))
            durs.append(float(info.get("steps", 0)))
    finally:
        env.close()
    gsum = summarize(counts, returns, fuels, durs, len(TARGET_SEEDS))
    gsum["name"] = "hand_tuned_guidance_REFERENCE_ONLY"
    gsum["level"] = "apollolander.starts.v1"
    gsum["diagnostic_frames"] = diag
    gsum["label"] = "REFERENCE_ONLY — not a trained agent"
    results["agents"]["hand_tuned_guidance_REFERENCE_ONLY"] = gsum

    # Per-curriculum-level performance for trained det (40 seeds each, disjoint)
    for li, level in enumerate(CURRICULUM_V3_LEVELS):
        seeds = list(range(410_000 + li * 100, 410_000 + li * 100 + 40))
        print(f"Per-level trained det @ {level}…", flush=True)
        results["per_level"][level] = run_policy(
            name=f"trained_det_{level}",
            seeds=seeds,
            level=level,
            max_steps=min(args.max_steps, 4000),
            action_fn=act_trained_det,
        )
        # strip bulky landings traces for per-level except seeds list
        lands = results["per_level"][level].pop("landings", [])
        results["per_level"][level]["landing_seeds"] = [x["seed"] for x in lands]

    # Strip bulky action traces from main agents except success evidence files
    for key, agent in results["agents"].items():
        if "landings" in agent:
            slim = []
            for land in agent["landings"]:
                slim.append({k: land[k] for k in land if k != "actions"})
            agent["landings_slim"] = slim
            del agent["landings"]

    results["wall_seconds"] = time.time() - t0
    results["total_diagnostic_frames"] = sum(
        a.get("diagnostic_frames", 0) for a in results["agents"].values()
    ) + sum(a.get("diagnostic_frames", 0) for a in results["per_level"].values())

    path = out_dir / "final_eval_results.json"
    path.write_text(json.dumps(results, indent=2) + "\n")
    print("Wrote", path)
    for name, agent in results["agents"].items():
        print(
            f"{name}: land={agent['landing_rate']:.3f} "
            f"CI={agent['landing_wilson95']} perfect={agent['perfect_rate']:.3f}"
        )


if __name__ == "__main__":
    main()
