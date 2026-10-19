#!/usr/bin/env python3
"""V5 preflight — must PASS before ppo_pilot_v5_commitment may launch.

Tests the frozen late-approach commitment term on recorded V3 success/failure
behavior (live rollouts of frozen V3-40k + legal reference), confirms no
obvious occupancy/fall exploit, verifies controlled variables, and checks
logging directories exist before tee.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import (  # noqa: E402
    A_PRIME_ALPHA,
    A_PRIME_TIME_COST,
    COMMIT_BETA,
    COMMIT_D_APP,
    COMMIT_H_APP,
    COMMIT_R_SOFT,
    COMMIT_V_SOFT,
    STEER_DELTAS,
    THRUST_LEVELS,
    ApolloLanderGym,
)
from env.controllers import reference_guidance_action  # noqa: E402
from env.seeds import (  # noqa: E402
    DEV_EVAL_SEEDS,
    HELD_OUT_SEEDS,
    TRAIN_SEED_BASE,
    V4_HELD_OUT_SEEDS,
    V5_HELD_OUT_SEEDS,
)

OUT = ROOT / "outputs" / "preflight_v5"
V3_40K = (
    ROOT
    / "models"
    / "ppo_pilot_v3_contact_Aprime"
    / "checkpoints"
    / "ppo_apollo_40000_steps.zip"
)
V3_INCUMBENT = ROOT / "models" / "ppo_pilot_v3_contact_Aprime" / "V3_40K_INCUMBENT.json"
FREEZE = (
    ROOT
    / "outputs"
    / "ppo_pilot_v3_contact_Aprime"
    / "v4_audit"
    / "v3_freeze_manifest.json"
)
AUTOPSY = (
    ROOT
    / "outputs"
    / "ppo_pilot_v3_contact_Aprime"
    / "v4_audit"
    / "timeout_autopsy_best_40k.json"
)

# Frozen constants — preflight fails if code drifts.
FROZEN = {
    "H_app": 25.0,
    "D_app": 60.0,
    "V_soft": 0.15,
    "R_soft": 15.0,
    "beta": 1.0,
    "alpha": 10.0,
    "time_cost": 0.005,
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_v5_env(**kwargs) -> ApolloLanderGym:
    cfg = dict(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime_v5",
        potential_scale=10.0,
        time_cost=0.005,
        commitment_shaping=True,
        timeout_as_terminated=True,
        headless=True,
        port=18790,
    )
    cfg.update(kwargs)
    return ApolloLanderGym(**cfg)


def make_v3_env(**kwargs) -> ApolloLanderGym:
    cfg = dict(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        commitment_shaping=False,
        timeout_as_terminated=True,
        headless=True,
        port=18791,
    )
    cfg.update(kwargs)
    return ApolloLanderGym(**cfg)


def test_frozen_constants() -> dict:
    failures = []
    mapping = {
        "H_app": COMMIT_H_APP,
        "D_app": COMMIT_D_APP,
        "V_soft": COMMIT_V_SOFT,
        "R_soft": COMMIT_R_SOFT,
        "beta": COMMIT_BETA,
        "alpha": A_PRIME_ALPHA,
        "time_cost": A_PRIME_TIME_COST,
    }
    for k, expect in FROZEN.items():
        got = mapping[k]
        if abs(float(got) - float(expect)) > 1e-12:
            failures.append(f"{k}: got {got} want {expect}")
    return {"passed": len(failures) == 0, "failures": failures, "frozen": FROZEN}


def test_spaces_and_controls() -> dict:
    env = make_v5_env()
    try:
        obs, info = env.reset(seed=200_000)
        failures = []
        if env.observation_space.shape != (11,):
            failures.append(f"obs_shape={env.observation_space.shape} (need 11)")
        if list(env.action_space.nvec) != [5, 3]:
            failures.append(f"action_nvec={env.action_space.nvec}")
        if abs(float(env.time_cost) - 0.005) > 1e-12:
            failures.append(f"time_cost={env.time_cost}")
        if abs(float(env.potential_scale) - 10.0) > 1e-12:
            failures.append(f"alpha={env.potential_scale}")
        if not env.commitment_shaping:
            failures.append("commitment_shaping_false")
        if obs.shape != (11,):
            failures.append(f"reset_obs={obs.shape}")
        if "approached" not in info:
            failures.append("missing_approached_info")
        # V3-compatible env stays 10-D
        env3 = make_v3_env(port=18792)
        try:
            o3, _ = env3.reset(seed=200_000)
            if o3.shape != (10,):
                failures.append(f"v3_obs={o3.shape}")
        finally:
            env3.close()
        return {
            "passed": len(failures) == 0,
            "failures": failures,
            "obs_dim": int(obs.shape[0]),
            "approached_at_reset": bool(info.get("approached")),
            "thrust_levels": THRUST_LEVELS.tolist(),
            "steer_deltas": STEER_DELTAS.tolist(),
        }
    finally:
        env.close()


def test_v3_incumbent_frozen() -> dict:
    if not V3_40K.exists():
        return {"passed": False, "error": "missing_40k"}
    digest = sha256(V3_40K)
    expected = None
    if FREEZE.exists():
        man = json.loads(FREEZE.read_text())
        expected = (
            man.get("checkpoints", {})
            .get("ppo_apollo_40000_steps.zip", {})
            .get("sha256")
        )
    match = expected is None or digest == expected
    return {
        "passed": match,
        "sha256": digest,
        "matches_freeze": match,
        "expected": expected,
        "incumbent_marker_exists": V3_INCUMBENT.exists(),
    }


def test_v5_heldout_reserved() -> dict:
    pool = set(V5_HELD_OUT_SEEDS)
    disjoint = (
        not pool & set(DEV_EVAL_SEEDS)
        and not pool & set(HELD_OUT_SEEDS)
        and not pool & set(V4_HELD_OUT_SEEDS)
        and list(V5_HELD_OUT_SEEDS) == list(range(500_000, 500_020))
        and TRAIN_SEED_BASE < min(DEV_EVAL_SEEDS)
    )
    return {
        "passed": disjoint,
        "pool": list(V5_HELD_OUT_SEEDS),
        "disjoint_ok": disjoint,
    }


def _rollout_reward_breakdown(env, policy_fn, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    sum_r = 0.0
    sum_commit = 0.0
    n_commit_neg = 0
    min_alt = float("inf")
    max_alt = float("-inf")
    series = []
    while True:
        action = policy_fn(obs, info)
        obs, r, term, trunc, info = env.step(action)
        raw = info["raw"]
        alt = float(raw["altitude"])
        vy = float(raw["vy"])
        rot = float(raw["rotation"])
        dx = float(raw["dx"])
        min_alt = min(min_alt, alt)
        max_alt = max(max_alt, alt)
        # Reconstruct commit term (same formula) for logging.
        approached = bool(info.get("approached"))
        commit = 0.0
        if (
            approached
            and vy < COMMIT_V_SOFT
            and abs(rot) < COMMIT_R_SOFT
            and (-vy) > 0
        ):
            commit = -COMMIT_BETA * max(0.0, -vy)
            n_commit_neg += 1
        sum_commit += commit
        sum_r += float(r)
        series.append(
            {
                "t": info["physics_frames"],
                "alt": alt,
                "vy": vy,
                "rot": rot,
                "dx": dx,
                "r": float(r),
                "commit": commit,
                "approached": approached,
            }
        )
        if term or trunc:
            break
    return {
        "seed": seed,
        "landed": bool(info.get("landed")),
        "perfect": bool(info.get("perfect")),
        "hard_landing": bool(info.get("hard_landing")),
        "crashed": bool(info.get("crashed")),
        "timeout": bool(info.get("timeout")),
        "physics_frames": info.get("physics_frames"),
        "sum_train_reward": sum_r,
        "sum_commit": sum_commit,
        "n_commit_penalty_steps": n_commit_neg,
        "min_alt": min_alt,
        "max_alt": max_alt,
        "approached": bool(info.get("approached")),
        "status": info.get("status"),
    }


def test_reward_on_recorded_behaviors() -> dict:
    """Live V3-40k rollouts: landings should not be crushed by commit; reascents should."""
    if not V3_40K.exists():
        return {"passed": False, "error": "missing_v3_40k"}
    autopsy = json.loads(AUTOPSY.read_text()) if AUTOPSY.exists() else {}
    land_seeds = list(autopsy.get("land_seeds", [200001, 200003, 200005])[:4])
    timeout_seeds = list(autopsy.get("timeout_seeds", [200000, 200002, 200004])[:4])

    # V3-40k was trained on 10-D obs — roll it in a 10-D env, then replay actions
    # is hard. Instead: roll V3 policy in 10-D to get outcomes, and separately
    # compute commitment on the same trajectories via a shadow env that we drive
    # with the same MultiDiscrete actions.
    model = PPO.load(str(V3_40K))
    env_act = make_v3_env(port=18793)
    env_v5 = make_v5_env(port=18794)

    def run_paired(seed: int) -> dict:
        # Collect actions from V3 policy on 10-D env
        obs, info = env_act.reset(seed=seed)
        actions = []
        while True:
            a, _ = model.predict(obs, deterministic=True)
            a = np.asarray(a, dtype=np.int64)
            actions.append(a.copy())
            obs, _, term, trunc, info = env_act.step(a)
            if term or trunc:
                outcome = {
                    "landed": bool(info["landed"]),
                    "timeout": bool(info["timeout"]),
                    "crashed": bool(info["crashed"]),
                    "perfect": bool(info["perfect"]),
                    "frames": info["physics_frames"],
                    "min_alt_proxy": float(info["raw"]["altitude"]),
                }
                break
        # Replay identical actions on V5 reward env
        obs5, _ = env_v5.reset(seed=seed)
        sum_r = 0.0
        sum_commit = 0.0
        n_pen = 0
        min_alt = float("inf")
        max_alt = float("-inf")
        for a in actions:
            obs5, r, term, trunc, info5 = env_v5.step(a)
            raw = info5["raw"]
            alt = float(raw["altitude"])
            vy = float(raw["vy"])
            rot = float(raw["rotation"])
            min_alt = min(min_alt, alt)
            max_alt = max(max_alt, alt)
            approached = bool(info5.get("approached"))
            commit = 0.0
            if approached and vy < COMMIT_V_SOFT and abs(rot) < COMMIT_R_SOFT:
                ascent = max(0.0, -vy)
                if ascent > 0:
                    commit = -COMMIT_BETA * ascent
                    n_pen += 1
            sum_commit += commit
            sum_r += float(r)
            if term or trunc:
                break
        return {
            "seed": seed,
            **outcome,
            "sum_train_reward_v5": sum_r,
            "sum_commit": sum_commit,
            "n_commit_penalty_steps": n_pen,
            "min_alt": min_alt,
            "max_alt": max_alt,
            "v5_landed": bool(info5.get("landed")),
            "v5_timeout": bool(info5.get("timeout")),
            "v5_status": info5.get("status"),
        }

    try:
        land_rows = [run_paired(s) for s in land_seeds]
        timeout_rows = [run_paired(s) for s in timeout_seeds]
    finally:
        env_act.close()
        env_v5.close()

    # Reference guidance should still land with non-pathological commit on a land seed
    env_ref = make_v5_env(port=18795)
    try:
        def ref_fn(obs, info):
            return reference_guidance_action(info["raw"], env_ref.cmd_angle)

        ref_row = _rollout_reward_breakdown(env_ref, ref_fn, land_seeds[0])
    finally:
        env_ref.close()

    land_commit = [r["sum_commit"] for r in land_rows if r.get("landed")]
    timeout_commit = [
        r["sum_commit"]
        for r in timeout_rows
        if r.get("timeout") or (r.get("max_alt", 0) > 50 and r.get("min_alt", 99) < 20)
    ]
    # Scientific gates
    failures = []
    if not land_commit:
        failures.append("no_successful_land_replays")
    else:
        if min(land_commit) < -5.0:
            failures.append(f"land_commit_too_harsh={land_commit}")
        if max(abs(c) for c in land_commit) > 5.0 and max(land_commit) < -5.0:
            failures.append(f"land_commit_unexpected={land_commit}")
    if not timeout_commit:
        failures.append("no_timeout_replays_for_compare")
    else:
        if max(timeout_commit) > -1.0:
            failures.append(f"timeout_commit_not_negative_enough={timeout_commit}")
        if land_commit and (np.mean(timeout_commit) >= np.mean(land_commit) - 1.0):
            failures.append(
                f"timeout_not_worse_than_land: land={land_commit} timeout={timeout_commit}"
            )
    # Reference should prefer landing path: if it lands, commit near 0
    if ref_row.get("landed") and ref_row["sum_commit"] < -10.0:
        failures.append(f"reference_land_commit_harsh={ref_row['sum_commit']}")
    # Occupancy exploit probe: no positive commit ever
    if any(c > 1e-9 for c in land_commit + timeout_commit + [ref_row["sum_commit"]]):
        failures.append("positive_commitment_reward_detected")

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "land_replays": land_rows,
        "timeout_replays": timeout_rows,
        "reference_replay": ref_row,
        "mean_land_commit": float(np.mean(land_commit)) if land_commit else None,
        "mean_timeout_commit": float(np.mean(timeout_commit)) if timeout_commit else None,
        "note": "Success should have ~0 commit; post-approach ascent timeouts strongly negative",
    }


def test_no_occupancy_or_fall_exploit() -> dict:
    """Synthetic unit checks on commitment formula (no browser)."""
    env = make_v5_env()
    # Don't need page for pure formula — call methods with fake raw
    failures = []
    env._approached = True
    # Soft ascent → penalty
    r = env._commitment_reward(
        {"altitude": 10.0, "dx": 5.0, "vy": -0.2, "rotation": 0.0}
    )
    if r >= 0:
        failures.append(f"soft_ascent_not_penalized={r}")
    # Hard fall (vy large positive) even if somehow ascending flag wrong → no penalty
    env._approached = True
    r_fall = env._commitment_reward(
        {"altitude": 10.0, "dx": 5.0, "vy": 0.5, "rotation": 0.0}
    )
    if abs(r_fall) > 1e-12:
        failures.append(f"hard_fall_penalized={r_fall}")
    # Low altitude occupancy with gentle descent → 0
    env._approached = True
    r_occ = env._commitment_reward(
        {"altitude": 5.0, "dx": 5.0, "vy": 0.05, "rotation": 0.0}
    )
    if abs(r_occ) > 1e-12:
        failures.append(f"occupancy_penalized={r_occ}")
    # Tilted recovery ascent → 0
    env._approached = True
    r_tilt = env._commitment_reward(
        {"altitude": 10.0, "dx": 5.0, "vy": -0.3, "rotation": 40.0}
    )
    if abs(r_tilt) > 1e-12:
        failures.append(f"tilted_recovery_penalized={r_tilt}")
    # Not approached → 0 even if ascending soft
    env._approached = False
    r_far = env._commitment_reward(
        {"altitude": 200.0, "dx": 5.0, "vy": -0.5, "rotation": 0.0}
    )
    if abs(r_far) > 1e-12:
        failures.append(f"far_ascent_penalized_without_latch={r_far}")
    env.close()
    return {"passed": len(failures) == 0, "failures": failures}


def test_log_dirs_before_tee() -> dict:
    run = "ppo_pilot_v5_commitment"
    out = ROOT / "outputs" / run
    logs = ROOT / "logs" / run
    models = ROOT / "models" / run
    out.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    models.mkdir(parents=True, exist_ok=True)
    return {
        "passed": out.is_dir() and logs.is_dir() and models.is_dir(),
        "outputs": str(out),
        "logs": str(logs),
        "models": str(models),
    }


def test_v4_negative_preserved() -> dict:
    v4 = ROOT / "outputs" / "ppo_pilot_v4_timecost" / "V4_RESULTS.md"
    if not v4.exists():
        return {"passed": False, "error": "missing_v4_results"}
    text = v4.read_text()
    ok = "NEGATIVE" in text and "V3-40k" in text
    return {"passed": ok, "path": str(v4)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "frozen_constants": test_frozen_constants(),
        "spaces_and_controls": test_spaces_and_controls(),
        "v3_incumbent_frozen": test_v3_incumbent_frozen(),
        "v5_heldout_reserved": test_v5_heldout_reserved(),
        "formula_unit": test_no_occupancy_or_fall_exploit(),
        "log_dirs": test_log_dirs_before_tee(),
        "v4_negative_preserved": test_v4_negative_preserved(),
    }
    # Live reward replay last (slow / browser)
    print("Running live reward replay on V3-40k land/timeout seeds...", flush=True)
    report["reward_replay"] = test_reward_on_recorded_behaviors()
    report["passed"] = all(
        v.get("passed") for v in report.values() if isinstance(v, dict) and "passed" in v
    )
    (OUT / "preflight_report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit("V5 preflight FAILED — do not train")
    print("V5 PREFLIGHT PASSED", flush=True)


if __name__ == "__main__":
    main()
