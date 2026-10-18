#!/usr/bin/env python3
"""Phase 2: random-policy and untrained-network landing rates per curriculum level.

Uses Wilson score intervals. Counts diagnostic physics frames separately.
"""

from __future__ import annotations

import argparse
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

from rewardbench.environments.apollolander.starts import (  # noqa: E402
    CURRICULUM_V3_LEVELS,
    START_SCHEDULE_VERSION,
    schedule_document,
)
from rewardbench.rl.continuous_policy import ContinuousThrustActorCritic  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.physics_python import ROTATION_BINS  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed  # noqa: E402
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

DIAG_FRAMES = 0


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def run_episodes(
    *,
    level: str,
    n: int,
    seed_start: int,
    max_steps: int,
    mode: str,
    policy: ContinuousThrustActorCritic | None = None,
    device: torch.device | None = None,
) -> dict[str, Any]:
    global DIAG_FRAMES
    env = ApolloLanderUpstreamEnv(
        EnvConfig(
            max_steps=max_steps,
            research_mode=True,
            start_schedule_version=level,
            vary_fuel=False,
            action_repeat=1,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        ),
        reward_mode="touchdown_v1",
    )
    rng = np.random.default_rng(seed_start + 99)
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0, "other": 0}
    returns = []
    fuels = []
    durations = []
    try:
        for i in range(n):
            seed = seed_start + i
            assert_seed_allowed(seed, context="baseline.measure")
            obs, _ = env.reset(seed)
            done = False
            ep_ret = 0.0
            steps = 0
            info: dict[str, Any] = {}
            while not done:
                if mode == "random":
                    thrust = float(rng.uniform(0.0, 1.0))
                    rot = int(rng.choice(ROTATION_BINS))
                    command = {"thrust": thrust, "rotation": rot}
                elif mode == "untrained":
                    assert policy is not None and device is not None
                    with torch.no_grad():
                        t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                        thrust_t, rot_idx, _ = policy.act_deterministic(t)
                        command = {
                            "thrust": float(thrust_t.item()),
                            "rotation": int(policy.decode_rotation(rot_idx).item()),
                        }
                else:
                    raise ValueError(mode)
                obs, reward, terminated, truncated, info = env.step_command(command)
                ep_ret += reward
                steps += 1
                DIAG_FRAMES += 1
                done = terminated or truncated
            status = info.get("status", "other")
            if status == "landed":
                counts["perfect"] += 1
            elif status == "hard_landing":
                counts["hard"] += 1
            elif status == "crashed":
                counts["crash"] += 1
            elif status == "timeout":
                counts["timeout"] += 1
            else:
                counts["other"] += 1
            returns.append(ep_ret)
            fuels.append(float(info.get("fuel_used", 0.0)))
            durations.append(steps)
    finally:
        env.close()

    land = counts["perfect"] + counts["hard"]
    p, lo, hi = wilson_ci(land, n)
    pp, plo, phi = wilson_ci(counts["perfect"], n)
    ph, hlo, hhi = wilson_ci(counts["hard"], n)
    return {
        "level": level,
        "mode": mode,
        "n": n,
        "seed_start": seed_start,
        "counts": counts,
        "landing_rate": p,
        "landing_wilson95": [lo, hi],
        "perfect_rate": pp,
        "perfect_wilson95": [plo, phi],
        "hard_rate": ph,
        "hard_wilson95": [hlo, hhi],
        "mean_return": float(np.mean(returns)) if returns else 0.0,
        "median_return": float(np.median(returns)) if returns else 0.0,
        "mean_fuel_used": float(np.mean(fuels)) if fuels else 0.0,
        "mean_duration": float(np.mean(durations)) if durations else 0.0,
    }


def main() -> None:
    global DIAG_FRAMES
    DIAG_FRAMES = 0
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=300)
    parser.add_argument("--max-steps", type=int, default=2000)
    parser.add_argument("--seed-start", type=int, default=300000)
    args = parser.parse_args()

    device = torch.device("cpu")
    untrained = ContinuousThrustActorCritic(hidden=128).to(device)
    untrained.eval()
    # Fixed documented untrained init seed (not a training seed).
    torch.manual_seed(42)
    untrained.reset_parameters()

    levels = list(CURRICULUM_V3_LEVELS) + [START_SCHEDULE_VERSION]
    # D easy for diagnosis comparison
    levels = [
        "apollolander.starts.curriculum_l0_v3",
        "apollolander.starts.curriculum_l1_v3",
        "apollolander.starts.curriculum_l2_v3",
        "apollolander.starts.curriculum_l3_v3",
        "apollolander.starts.curriculum_l4_v3",
        "apollolander.starts.curriculum_easy_v1",
        "apollolander.starts.v1",
    ]

    rows = []
    t0 = time.time()
    for li, level in enumerate(levels):
        for mode in ("random", "untrained"):
            print(f"Measuring {mode} @ {level}…", flush=True)
            row = run_episodes(
                level=level,
                n=args.episodes,
                seed_start=args.seed_start + li * 10_000,
                max_steps=args.max_steps,
                mode=mode,
                policy=untrained if mode == "untrained" else None,
                device=device,
            )
            rows.append(row)
            print(
                f"  land={row['landing_rate']:.3f} "
                f"CI=[{row['landing_wilson95'][0]:.3f},{row['landing_wilson95'][1]:.3f}] "
                f"perfect={row['perfect_rate']:.3f} hard={row['hard_rate']:.3f}",
                flush=True,
            )

    out = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "episodes_per_cell": args.episodes,
        "max_steps": args.max_steps,
        "diagnostic_physics_frames": DIAG_FRAMES,
        "wall_seconds": time.time() - t0,
        "schedules": {lv: schedule_document(lv) for lv in levels},
        "rows": rows,
        "diagnosis_notes": [
            "Family D curriculum_easy_v1 starts near the pad but often with rotation≠0;",
            "native landing requires exact rotation==0 and vy<0.15.",
            "Random/untrained rates on L0 vs easy_v1 quantify whether D was 'easy enough'.",
        ],
    }
    path = RESULTS / "baseline_rates.json"
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("Wrote", path, "diagnostic_frames", DIAG_FRAMES)


if __name__ == "__main__":
    main()
