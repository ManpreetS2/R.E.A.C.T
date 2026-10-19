#!/usr/bin/env python3
"""Validate A/B/C/D fairness constraints and seed non-leakage (no training)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import (  # noqa: E402
    ABCD_MODES,
    A_PRIME_ALPHA,
    A_PRIME_TIME_COST,
    PPO_GAMMA,
    STEER_DELTAS,
    THRUST_LEVELS,
    ApolloLanderGym,
)
from env.seeds import (  # noqa: E402
    ABCD_AUDIT_SEEDS,
    ABCD_CONDITIONS,
    ABCD_DEV_SEEDS,
    ABCD_HELD_OUT_SEEDS,
    ABCD_REWARD_MODE,
    ABCD_TRAIN_BASES,
    ABCD_TRAIN_SEEDS,
    CHAMPION_VAL_SEEDS,
    DEV_EVAL_SEEDS,
    HELD_OUT_SEEDS,
    TRAIN_SEED_BASE,
    V4_HELD_OUT_SEEDS,
    V5_HELD_OUT_SEEDS,
    abcd_train_auto_seed_base,
)
from env.starts import SHORT_HORIZON_TEMPLATES, SHORT_HORIZON_VERSION  # noqa: E402

OUT = ROOT / "outputs" / "abcd_preflight"


def _load_budget_callback():
    path = ROOT / "scripts" / "train_ppo.py"
    spec = importlib.util.spec_from_file_location("train_ppo_mod", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.PhysicsBudgetCallback


def test_spaces_identical() -> dict:
    failures = []
    envs = []
    try:
        for i, mode in enumerate(sorted(ABCD_MODES)):
            env = ApolloLanderGym(
                reward_mode=mode,
                start_template="sh_contact",
                start_mode="research",
                commitment_shaping=False,
                timeout_as_terminated=True,
                headless=True,
                port=19700 + i,
            )
            envs.append(env)
            if env.observation_space.shape != (10,):
                failures.append(f"{mode} obs={env.observation_space.shape}")
            if list(env.action_space.nvec) != [5, 3]:
                failures.append(f"{mode} action={env.action_space.nvec}")
            if env.commitment_shaping:
                failures.append(f"{mode} commitment on")
            if abs(env.potential_scale - 10.0) > 1e-12 and mode != "abcd_d":
                # abcd_d may leave potential_scale at 1.0 unused
                if mode in ("abcd_a", "abcd_b", "abcd_c"):
                    failures.append(f"{mode} alpha={env.potential_scale}")
            if mode in ("abcd_a", "abcd_b", "abcd_c"):
                if abs(float(env.time_cost) - 0.005) > 1e-12:
                    failures.append(f"{mode} c={env.time_cost}")
            if not env.timeout_as_terminated:
                failures.append(f"{mode} timeout_as_terminated false")
        if not np.allclose(THRUST_LEVELS, [0, 0.25, 0.5, 0.75, 1.0]):
            failures.append("thrust")
        if not np.allclose(STEER_DELTAS, [-10, 0, 10]):
            failures.append("steer")
        if "sh_contact" not in SHORT_HORIZON_TEMPLATES:
            failures.append("missing sh_contact")
        if SHORT_HORIZON_VERSION != "short_horizon.v1":
            failures.append(f"version={SHORT_HORIZON_VERSION}")
        return {
            "passed": len(failures) == 0,
            "failures": failures,
            "obs_dim": 10,
            "action_nvec": [5, 3],
            "ar": 4,
            "start": "sh_contact",
            "short_horizon_version": SHORT_HORIZON_VERSION,
        }
    finally:
        for e in envs:
            e.close()


def test_seed_leakage() -> dict:
    pools = {
        "audit": set(ABCD_AUDIT_SEEDS),
        "dev": set(ABCD_DEV_SEEDS),
        "heldout": set(ABCD_HELD_OUT_SEEDS),
        "champion": set(CHAMPION_VAL_SEEDS),
        "v3_dev": set(DEV_EVAL_SEEDS),
        "v3_held": set(HELD_OUT_SEEDS),
        "v4_held": set(V4_HELD_OUT_SEEDS),
        "v5_held": set(V5_HELD_OUT_SEEDS),
    }
    overlaps = []
    keys = list(pools)
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            inter = pools[a] & pools[b]
            if inter:
                overlaps.append(f"{a}&{b}:{sorted(inter)[:5]}")
    # Train bases vs eval absolute seeds
    bases = set(ABCD_TRAIN_BASES.values())
    for name in ("dev", "heldout", "audit", "champion"):
        # collision if an eval seed equals a base (episode 0)
        hit = bases & pools[name]
        if hit:
            overlaps.append(f"train_base&{name}:{sorted(hit)[:5]}")
    # Ensure 12 runs
    ok_count = len(ABCD_TRAIN_BASES) == 12
    # Spacing: consecutive bases differ by 10k
    ordered = sorted(ABCD_TRAIN_BASES.values())
    gaps_ok = all(ordered[i + 1] - ordered[i] >= 10_000 for i in range(len(ordered) - 1))
    return {
        "passed": len(overlaps) == 0 and ok_count and gaps_ok,
        "overlaps": overlaps,
        "n_train_runs": len(ABCD_TRAIN_BASES),
        "train_bases": {f"{c}-{s}": abcd_train_auto_seed_base(c, s) for c, s in ABCD_TRAIN_BASES},
        "reward_modes": ABCD_REWARD_MODE,
        "train_seeds": list(ABCD_TRAIN_SEEDS),
        "conditions": list(ABCD_CONDITIONS),
        "heldout_n": len(ABCD_HELD_OUT_SEEDS),
        "dev_n": len(ABCD_DEV_SEEDS),
        "gaps_ok": gaps_ok,
    }


def test_budget_guard() -> dict:
    PhysicsBudgetCallback = _load_budget_callback()

    def would_continue(physics_frames: int, max_f: int, ar: int) -> bool:
        if physics_frames >= max_f:
            return False
        if physics_frames + ar > max_f:
            return False
        return True

    expect = {
        199_996: True,
        199_997: False,
        199_998: False,
        199_999: False,
        200_000: False,
    }
    logic = {f: would_continue(f, 200_000, 4) for f in expect}
    cb = PhysicsBudgetCallback(200_000, action_repeat=4)
    cb.physics_frames = 199_996
    cb.locals = {"infos": [{"physics_frames_delta": 4}]}
    cont = PhysicsBudgetCallback._on_step(cb)
    return {
        "passed": logic == expect and (not cont) and cb.physics_frames == 200_000,
        "logic": logic,
        "exact_cap_continue_after": cont,
        "exact_cap_frames": cb.physics_frames,
        "max_physics_frames_per_run": 200_000,
        "max_total_study_frames": 12 * 200_000,
    }


def test_ppo_hyperparams_doc() -> dict:
    """Document frozen PPO settings (must match train_ppo defaults / study plan)."""
    frozen = {
        "policy": "MlpPolicy",
        "learning_rate": 3e-4,
        "n_steps": 256,
        "batch_size": 64,
        "gamma": PPO_GAMMA,
        "action_repeat": 4,
        "episode_max_frames": 2000,
        "max_physics_frames": 200_000,
        "checkpoint_every_gym_steps": 5_000,
        "train_seeds": list(ABCD_TRAIN_SEEDS),
        "independent_init": True,
        "alpha": A_PRIME_ALPHA,
        "time_cost": A_PRIME_TIME_COST,
    }
    return {"passed": True, "frozen": frozen}


def test_v3_40k_separate() -> dict:
    path = (
        ROOT
        / "models"
        / "ppo_pilot_v3_contact_Aprime"
        / "checkpoints"
        / "ppo_apollo_40000_steps.zip"
    )
    return {
        "passed": path.exists(),
        "path": str(path),
        "role": "historical_feasibility_reference_only",
        "not_condition_A": True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "spaces": test_spaces_identical(),
        "seeds": test_seed_leakage(),
        "budget_guard": test_budget_guard(),
        "ppo": test_ppo_hyperparams_doc(),
        "v3_reference": test_v3_40k_separate(),
    }
    report["passed"] = all(v.get("passed") for v in report.values() if isinstance(v, dict))
    (OUT / "ABCD_FAIRNESS.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("ABCD fairness check FAILED")
    print("ABCD FAIRNESS PASSED", flush=True)


if __name__ == "__main__":
    main()
