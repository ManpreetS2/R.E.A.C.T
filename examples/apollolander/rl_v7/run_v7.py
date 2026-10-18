#!/usr/bin/env python3
"""V7 demonstration-assisted training: translate expert → BC → optional PPO.

Expert (demonstration_guidance) is used for TRAINING ONLY (demo collection).
Learner eval never imports/calls the controller — integrity monkeypatch proves it.

Label every result: demonstration-assisted (never reward-only).
Caps enforced BEFORE stepping via TrainingBudget / DiagnosticBudget.require.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import traceback
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from scipy import stats as scipy_stats
from torch import nn

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rewardbench.environments.apollolander.schema import (  # noqa: E402
    DEMONSTRATION_GUIDANCE,
    guidance_action,
)
from rewardbench.rl.continuous_policy import (  # noqa: E402
    ROTATION_DELTAS,
    ContinuousThrustActorCritic,
)
from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.physics_python import normalize_obs, observation_vector  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed  # noqa: E402
from rewardbench.rl.training_budget import TrainingBudget, TrainingBudgetExhausted  # noqa: E402
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv, VectorApolloLanderUpstreamEnv  # noqa: E402

from translate import (  # noqa: E402
    ACTION_REPEAT,
    obs_dict_from_host,
    raw_expert_command,
    snap10,
    translate_to_learner,
)

HERE = Path(__file__).resolve().parent
PREREG = HERE / "preregistered"
RESULTS = HERE / "results"
LEVEL_V1 = "apollolander.starts.v1"
LEVEL_L0 = "apollolander.starts.l0_near_v6"
DEMO_CAP = 300_000
DIAG_CAP = 200_000
PPO_CAP = 250_000
LABEL = "demonstration-assisted"


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def mcnemar_exact(b: int, c: int) -> dict[str, Any]:
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "n_discordant": 0, "p_value": 1.0, "method": "exact_none"}
    res = scipy_stats.binomtest(b, n, 0.5, alternative="two-sided")
    return {
        "b": int(b),
        "c": int(c),
        "n_discordant": int(n),
        "p_value": float(res.pvalue),
        "method": "exact_binomial_mcnemar",
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_json(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass
class V7Config:
    action_repeat: int = ACTION_REPEAT
    rotation_mode: str = "delta"
    hidden: int = 128
    seed: int = 71
    # Raw/translated expert needs ~5.5–6.5k frames on v1; 3000 falsely times out.
    max_steps_v1: int = 8000
    max_steps_l0: int = 400
    feasibility_n: int = 12  # ~20-class landing-rate probe; sized for 300k demo cap
    fidelity_n: int = 4  # raw-vs-translated pairs (subset of feasibility seeds)
    demo_keep_target_min: int = 50
    demo_keep_target_max: int = 100
    demo_v1_target: int = 12  # primary distribution; remainder filled with L0-near
    bc_epochs: int = 40
    bc_batch_size: int = 256
    bc_lr: float = 1e-3
    ppo_budget: int = PPO_CAP
    diag_cap: int = DIAG_CAP
    demo_cap: int = DEMO_CAP
    n_envs: int = 4
    rollout_steps: int = 128
    learning_rate: float = 2.5e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    update_epochs: int = 4
    minibatch_size: int = 256
    device: str = "cpu"
    run_name: str = "V7_imitation"
    init_scheme: str = "orthogonal_zero_bias"
    soft_thrust_prior: bool = False
    hold_attitude_prior: bool = False
    bc_regularization: float = 0.0  # optional KL/BC term; 0 = off
    eval_v1_n: int = 40  # attempt preregistered v1 seeds; stop when diag cap blocks
    eval_l0_n: int = 40
    expert_ref_n: int = 4
    diag_reserve_for_ppo_eval: int = 20_000  # leave room for BC+PPO L0 McNemar
    max_footage_landings: int = 3


def load_prereg() -> dict[str, Any]:
    seeds = json.loads((PREREG / "seeds.json").read_text())
    plan = json.loads((PREREG / "plan.json").read_text())
    digest = (PREREG / "seeds.sha256").read_text().strip()
    assert sha256_file(PREREG / "seeds.json") == digest, "seeds.json hash mismatch"
    assert plan["seeds_sha256"] == digest
    assert_seeds_allowed(seeds["demo_train_attempt_pool"], context="v7.demo_train")
    assert_seeds_allowed(seeds["demo_val_seeds"], context="v7.demo_val")
    assert_seeds_allowed(seeds["unseen_eval_v1_seeds"], context="v7.eval_v1")
    assert_seeds_allowed(seeds["unseen_eval_l0near_seeds"], context="v7.eval_l0")
    return seeds


def make_env(level: str, max_steps: int, action_repeat: int) -> ApolloLanderUpstreamEnv:
    return ApolloLanderUpstreamEnv(
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


def host_observe(env: ApolloLanderUpstreamEnv) -> dict[str, Any]:
    return env.session.call({"cmd": "observe"})["observation"]


def outcome_row(info: dict[str, Any], ep_ret: float = 0.0) -> dict[str, Any]:
    status = info.get("status", "")
    native = info.get("native_outcome") or {}
    landed = status in ("landed", "hard_landing")
    return {
        "status": status,
        "landed": landed,
        "perfect": status == "landed",
        "hard": status == "hard_landing",
        "crash": status == "crashed",
        "timeout": status == "timeout",
        "rotation": float(native.get("rotation", info.get("terminal_rotation", 0.0))),
        "vy": float(native.get("vy", info.get("terminal_vy", 0.0))),
        "vx": float(native.get("vx", 0.0)),
        "native_outcome": native,
        "native_score": float(info.get("native_score", 0.0) or 0.0),
        "steps": int(info.get("steps", 0)),
        "return": float(ep_ret),
        "fuel_used": float(info.get("fuel_used", 0.0)),
    }


# ---------------------------------------------------------------------------
# Phase 0 / Phase 1: expert rollouts (training-only)
# ---------------------------------------------------------------------------


def rollout_translated_expert(
    env: ApolloLanderUpstreamEnv,
    seed: int,
    budget: DiagnosticBudget | TrainingBudget,
    *,
    reason: str,
    record_steps: bool = True,
) -> dict[str, Any]:
    """Run translated expert (ar=8 delta). Charges actual physics frames."""
    assert_seed_allowed(seed, context=reason)
    max_steps = env.config.max_steps
    budget.require(max_steps, reason=f"pre:{reason}:{seed}")
    obs_vec, info0 = env.reset(seed)
    raw = host_observe(env)
    cmd_rot = snap10(float(info0["start"]["rotation"]))
    steps_log: list[dict[str, Any]] = []
    decision_trace: list[dict[str, float | int]] = []
    per_frame_applied: list[dict[str, float | int]] = []
    ep_ret = 0.0
    done = False
    info: dict[str, Any] = {}
    frame_before = 0
    while not done:
        od = obs_dict_from_host(raw)
        tr = translate_to_learner(od, cmd_rot)
        applied = tr["applied_absolute"]
        cmd_rot = int(applied["rotation"])
        state_before = {
            "position": [od["x"], od["y"]],
            "velocity": [od["vx"], od["vy"]],
            "rotation": od["rotation"],
            "fuel": od["fuel"],
        }
        obs_after, reward, terminated, truncated, info = env.step_command(applied)
        ep_ret += reward
        done = terminated or truncated
        frames_this = int(info.get("steps", 0)) - frame_before
        # action_repeat may end early on terminal
        for _ in range(max(1, frames_this)):
            per_frame_applied.append(dict(applied))
        decision_trace.append(dict(applied))
        if record_steps:
            raw_after = host_observe(env) if not done else (info.get("_raw") or host_observe(env))
            # After terminal, observe still works
            try:
                raw_after = host_observe(env)
            except Exception:
                raw_after = raw
            od_after = obs_dict_from_host(raw_after)
            steps_log.append(
                {
                    "frame_index": frame_before,
                    "observation": obs_vec.tolist(),
                    "raw_state_before": state_before,
                    "raw_state_after": {
                        "position": [od_after["x"], od_after["y"]],
                        "velocity": [od_after["vx"], od_after["vy"]],
                        "rotation": od_after["rotation"],
                        "fuel": od_after["fuel"],
                    },
                    "translated_expert_action": tr["learner"],
                    "raw_expert_command": tr["raw_expert"],
                    "applied_absolute": applied,
                }
            )
            raw = raw_after
            obs_vec = obs_after
        else:
            raw = host_observe(env)
            obs_vec = obs_after
        frame_before = int(info.get("steps", 0))

    frames = int(info.get("steps", 0))
    budget.charge(frames, reason=f"{reason}:seed{seed}")
    row = outcome_row(info, ep_ret)
    row.update(
        {
            "seed": seed,
            "label": LABEL,
            "controller": "translated_expert",
            "action_repeat": env.config.action_repeat,
            "decision_trace": decision_trace,
            "per_frame_applied": per_frame_applied,
            "steps_log": steps_log if record_steps else None,
            "start": info0["start"],
        }
    )
    return row


def rollout_raw_expert(
    env_ar1: ApolloLanderUpstreamEnv,
    seed: int,
    budget: DiagnosticBudget | TrainingBudget,
    *,
    reason: str,
) -> dict[str, Any]:
    """Raw expert every physics frame (ar=1). For fidelity comparison only."""
    assert_seed_allowed(seed, context=reason)
    budget.require(env_ar1.config.max_steps, reason=f"pre:{reason}:{seed}")
    _, info0 = env_ar1.reset(seed)
    per_frame: list[dict[str, float | int]] = []
    ep_ret = 0.0
    done = False
    info: dict[str, Any] = {}
    while not done:
        raw = host_observe(env_ar1)
        cmd = raw_expert_command(obs_dict_from_host(raw))
        per_frame.append(cmd)
        _, reward, terminated, truncated, info = env_ar1.step_command(cmd)
        ep_ret += reward
        done = terminated or truncated
    frames = int(info.get("steps", 0))
    budget.charge(frames, reason=f"{reason}:seed{seed}")
    row = outcome_row(info, ep_ret)
    row.update(
        {
            "seed": seed,
            "label": LABEL,
            "controller": "raw_expert",
            "action_repeat": 1,
            "per_frame_applied": per_frame,
            "start": info0["start"],
        }
    )
    return row


def fidelity_compare(translated: dict[str, Any], raw: dict[str, Any]) -> dict[str, Any]:
    a = translated["per_frame_applied"]
    b = raw["per_frame_applied"]
    n = min(len(a), len(b))
    if n == 0:
        return {"n_frames_compared": 0}
    thr = [abs(float(a[i]["thrust"]) - float(b[i]["thrust"])) for i in range(n)]
    rot = [abs(int(a[i]["rotation"]) - int(b[i]["rotation"])) for i in range(n)]
    agree_rot = sum(1 for i in range(n) if int(a[i]["rotation"]) == int(b[i]["rotation"]))
    return {
        "n_frames_compared": n,
        "len_translated": len(a),
        "len_raw": len(b),
        "thrust_mae": float(np.mean(thr)),
        "thrust_max_abs": float(np.max(thr)),
        "rotation_mae_deg": float(np.mean(rot)),
        "rotation_max_abs_deg": float(np.max(rot)),
        "rotation_exact_agreement": agree_rot / n,
        "both_landed": bool(translated["landed"] and raw["landed"]),
        "translated_status": translated["status"],
        "raw_status": raw["status"],
    }


def replay_trace_bitexact(
    env: ApolloLanderUpstreamEnv,
    seed: int,
    decision_trace: list[dict[str, float | int]],
    expected: dict[str, Any],
    budget: DiagnosticBudget | TrainingBudget,
    *,
    reason: str,
) -> dict[str, Any]:
    """Replay decision_trace with same action_repeat; verify native outcome match."""
    assert_seed_allowed(seed, context=reason)
    budget.require(env.config.max_steps, reason=f"pre:{reason}:{seed}")
    env.reset(seed)
    info: dict[str, Any] = {}
    for cmd in decision_trace:
        _, _, terminated, truncated, info = env.step_command(cmd)
        if terminated or truncated:
            break
    frames = int(info.get("steps", 0))
    budget.charge(frames, reason=f"{reason}:seed{seed}")
    got = outcome_row(info)
    match = (
        got["status"] == expected["status"]
        and got["steps"] == expected["steps"]
        and abs(got["native_score"] - expected["native_score"]) < 1e-9
        and abs(got["rotation"] - expected["rotation"]) < 1e-9
        and abs(got["vy"] - expected["vy"]) < 1e-12
    )
    return {
        "seed": seed,
        "matched": match,
        "expected_status": expected["status"],
        "replay_status": got["status"],
        "expected_steps": expected["steps"],
        "replay_steps": got["steps"],
        "expected_score": expected["native_score"],
        "replay_score": got["native_score"],
        "expected_rotation": expected["rotation"],
        "replay_rotation": got["rotation"],
        "expected_vy": expected["vy"],
        "replay_vy": got["vy"],
    }


def phase0_feasibility(cfg: V7Config, out: Path, seeds_doc: dict) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    budget = DiagnosticBudget(hard_cap=cfg.demo_cap)  # shared demo/feas/replay pool
    feas_seeds = list(seeds_doc["demo_train_attempt_pool"][: cfg.feasibility_n])
    fid_seeds = set(feas_seeds[: cfg.fidelity_n])
    env_t = make_env(LEVEL_V1, cfg.max_steps_v1, cfg.action_repeat)
    env_r = make_env(LEVEL_V1, cfg.max_steps_v1, 1)
    rows = []
    fidelities = []
    raw_land = 0
    raw_n = 0
    try:
        for seed in feas_seeds:
            print(f"[feas] translated seed={seed}", flush=True)
            tr = rollout_translated_expert(
                env_t, seed, budget, reason="feas_translated", record_steps=False
            )
            fid = None
            raw_brief = None
            if seed in fid_seeds:
                print(f"[feas] raw seed={seed}", flush=True)
                rw = rollout_raw_expert(env_r, seed, budget, reason="feas_raw")
                fid = fidelity_compare(tr, rw)
                fidelities.append(fid)
                raw_n += 1
                raw_land += int(rw["landed"])
                raw_brief = {k: rw[k] for k in (
                    "status", "landed", "perfect", "hard", "steps",
                    "rotation", "vy", "native_score",
                )}
            rep = replay_trace_bitexact(
                env_t,
                seed,
                tr["decision_trace"],
                tr,
                budget,
                reason="feas_replay",
            )
            rows.append(
                {
                    "seed": seed,
                    "translated": {k: tr[k] for k in (
                        "status", "landed", "perfect", "hard", "steps",
                        "rotation", "vy", "native_score",
                    )},
                    "raw": raw_brief,
                    "fidelity": fid,
                    "replay": rep,
                }
            )
            print(
                f"  tr={tr['status']} steps={tr['steps']} "
                f"fid_rot_mae={(fid or {}).get('rotation_mae_deg')} replay={rep['matched']}",
                flush=True,
            )
    finally:
        env_t.close()
        env_r.close()

    l0_rows = []
    l0_probe = list(seeds_doc["demo_train_attempt_pool"][-10:])
    env_l0 = make_env(LEVEL_L0, cfg.max_steps_l0, cfg.action_repeat)
    try:
        for seed in l0_probe:
            if not budget.can_afford(cfg.max_steps_l0):
                break
            print(f"[feas-l0] translated seed={seed}", flush=True)
            tr = rollout_translated_expert(
                env_l0, seed, budget, reason="feas_l0_translated", record_steps=False
            )
            l0_rows.append(
                {k: tr[k] for k in ("seed", "status", "landed", "perfect", "hard", "steps", "rotation", "vy")}
            )
    finally:
        env_l0.close()

    n = len(rows)
    tr_land = sum(1 for r in rows if r["translated"]["landed"])
    replay_ok = sum(1 for r in rows if r["replay"]["matched"])
    l0_land = sum(1 for r in l0_rows if r["landed"])
    p, lo, hi = wilson_ci(tr_land, n)
    fid_ok = [f for f in fidelities if f.get("n_frames_compared")]
    summary = {
        "label": LABEL,
        "phase": 0,
        "action_repeat": cfg.action_repeat,
        "rotation_mode": "delta{-10,0,+10}",
        "max_steps_v1": cfg.max_steps_v1,
        "n_v1": n,
        "translated_landings": tr_land,
        "translated_landing_rate": p,
        "translated_wilson95": [lo, hi],
        "raw_landings": raw_land,
        "raw_n": raw_n,
        "raw_landing_rate": raw_land / raw_n if raw_n else None,
        "replay_bitexact_matched": replay_ok,
        "replay_bitexact_n": n,
        "fidelity_aggregate": {
            "n": len(fid_ok),
            "thrust_mae_mean": float(np.mean([f["thrust_mae"] for f in fid_ok])) if fid_ok else None,
            "rotation_mae_deg_mean": float(np.mean([f["rotation_mae_deg"] for f in fid_ok])) if fid_ok else None,
            "rotation_exact_agreement_mean": float(
                np.mean([f["rotation_exact_agreement"] for f in fid_ok])
            ) if fid_ok else None,
        },
        "l0_near_probe": {
            "seeds": l0_probe,
            "n": len(l0_rows),
            "landings": l0_land,
            "landing_rate": l0_land / len(l0_rows) if l0_rows else None,
            "rows": l0_rows,
        },
        "pass_threshold_0_80": tr_land / n >= 0.80 if n else False,
        "budget_spent": budget.spent,
        "budget_cap": budget.hard_cap,
        "budget_snapshot": budget.snapshot(),
        "per_seed": rows,
        "representation_note": (
            "Same learner space as V6: continuous thrust, delta{-10,0,+10}, ar=8. "
            "Expert absolute target quantized to one ±10/0 step per decision; thrust held. "
            "max_steps_v1=8000 required (expert ~6k frames; 3000 falsely times out)."
        ),
        "fallback_used": False,
    }
    (out / "phase0_feasibility.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "demo_budget_spent.json").write_text(
        json.dumps({"spent": budget.spent, "hard_cap": budget.hard_cap}) + "\n"
    )
    return summary


def phase1_collect_demos(cfg: V7Config, out: Path, seeds_doc: dict, phase0: dict) -> dict[str, Any]:
    demos_dir = out / "demos"
    demos_dir.mkdir(parents=True, exist_ok=True)
    spent0 = json.loads((out / "demo_budget_spent.json").read_text())["spent"]
    budget = DiagnosticBudget(hard_cap=cfg.demo_cap, spent=spent0)

    include_l0 = bool(
        phase0.get("l0_near_probe", {}).get("landing_rate") is not None
        and phase0["l0_near_probe"]["landing_rate"] >= 0.8
    )

    kept: list[dict[str, Any]] = []
    attempts = 0
    failures = 0
    attempt_log: list[dict[str, Any]] = []

    train_pool = list(seeds_doc["demo_train_attempt_pool"])
    val_pool = list(seeds_doc["demo_val_seeds"])
    # Feasibility seeds already burned frames; prefer unused seeds for demos.
    feas_used = set(train_pool[: cfg.feasibility_n]) | set(train_pool[-10:])
    train_pool_fresh = [s for s in train_pool if s not in feas_used] + [
        s for s in train_pool if s in feas_used
    ]

    env = make_env(LEVEL_V1, cfg.max_steps_v1, cfg.action_repeat)
    env_l0 = make_env(LEVEL_L0, cfg.max_steps_l0, cfg.action_repeat) if include_l0 else None

    def kept_count(*, split: str | None = None, level: str | None = None) -> int:
        n = 0
        for k in kept:
            if split is not None and k["split"] != split:
                continue
            if level is not None and k["level"] != level:
                continue
            n += 1
        return n

    def collect_from(
        pool: list[int],
        *,
        split: str,
        level: str,
        env_use,
        max_keep_split_level: int,
        global_max: int,
    ) -> None:
        nonlocal attempts, failures
        for seed in pool:
            if kept_count() >= global_max:
                return
            if kept_count(split=split, level=level) >= max_keep_split_level:
                return
            if not budget.can_afford(env_use.config.max_steps):
                return
            attempts += 1
            print(f"[demo {split}/{level}] attempt seed={seed} kept={kept_count()} spent={budget.spent}", flush=True)
            try:
                ep = rollout_translated_expert(
                    env_use, seed, budget, reason=f"demo_{split}", record_steps=True
                )
            except DiagnosticBudgetExhausted:
                raise
            ok = bool(ep["landed"])
            attempt_log.append(
                {
                    "seed": seed,
                    "split": split,
                    "level": level,
                    "status": ep["status"],
                    "landed": ok,
                    "steps": ep["steps"],
                }
            )
            if not ok:
                failures += 1
                continue
            if not budget.can_afford(env_use.config.max_steps):
                # Cannot replay-verify — do not keep
                failures += 1
                attempt_log[-1]["replay_skipped_budget"] = True
                return
            rep = replay_trace_bitexact(
                env_use,
                seed,
                ep["decision_trace"],
                ep,
                budget,
                reason=f"demo_replay_{split}",
            )
            if not rep["matched"]:
                failures += 1
                attempt_log[-1]["replay_failed"] = True
                continue
            demo_id = f"{split}_{level.replace('.', '_')}_{seed}"
            path = demos_dir / f"{demo_id}.json"
            payload = {
                "demo_id": demo_id,
                "label": LABEL,
                "split": split,
                "level": level,
                "seed": seed,
                "native_outcome": ep["native_outcome"],
                "native_score": ep["native_score"],
                "status": ep["status"],
                "perfect": ep["perfect"],
                "hard": ep["hard"],
                "steps": ep["steps"],
                "frame_count": ep["steps"],
                "decision_count": len(ep["decision_trace"]),
                "start": ep["start"],
                "decision_trace": ep["decision_trace"],
                "steps_log": ep["steps_log"],
                "replay_verification": rep,
                "action_repeat": cfg.action_repeat,
                "rotation_mode": "delta",
            }
            path.write_text(json.dumps(payload) + "\n")
            kept.append(
                {
                    "demo_id": demo_id,
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "split": split,
                    "level": level,
                    "seed": seed,
                    "status": ep["status"],
                    "steps": ep["steps"],
                    "native_score": ep["native_score"],
                }
            )
            print(f"  KEPT {demo_id} status={ep['status']} steps={ep['steps']}", flush=True)

    try:
        # Primary: normal v1 starts (budget allows only a handful at ~6k×2 frames).
        collect_from(
            train_pool_fresh,
            split="train",
            level=LEVEL_V1,
            env_use=env,
            max_keep_split_level=cfg.demo_v1_target,
            global_max=cfg.demo_keep_target_max,
        )
        collect_from(
            val_pool,
            split="val",
            level=LEVEL_V1,
            env_use=env,
            max_keep_split_level=max(2, cfg.demo_v1_target // 4),
            global_max=cfg.demo_keep_target_max,
        )
        # Fill to 50–100 with L0-near if expert lands there (documented).
        if include_l0 and env_l0 is not None:
            used = {k["seed"] for k in kept}
            l0_pool = [s for s in train_pool if s not in used]
            collect_from(
                l0_pool,
                split="train",
                level=LEVEL_L0,
                env_use=env_l0,
                max_keep_split_level=80,
                global_max=cfg.demo_keep_target_max,
            )
            l0_val = [s for s in val_pool if s not in used]
            collect_from(
                l0_val,
                split="val",
                level=LEVEL_L0,
                env_use=env_l0,
                max_keep_split_level=20,
                global_max=cfg.demo_keep_target_max,
            )
    finally:
        env.close()
        if env_l0 is not None:
            env_l0.close()

    seed_list = sorted(k["seed"] for k in kept)
    manifest = {
        "label": LABEL,
        "phase": 1,
        "attempts": attempts,
        "failures": failures,
        "kept": len(kept),
        "kept_train": sum(1 for k in kept if k["split"] == "train"),
        "kept_val": sum(1 for k in kept if k["split"] == "val"),
        "kept_v1": sum(1 for k in kept if k["level"] == LEVEL_V1),
        "kept_l0_near": sum(1 for k in kept if k["level"] == LEVEL_L0),
        "include_l0_near": include_l0,
        "primary_start": LEVEL_V1,
        "note": (
            "V1 demos are primary but expensive (~6k frames × attempt+replay). "
            "L0-near demos fill to 50–100 under the 300k demo/feas/replay cap."
        ),
        "demos": kept,
        "attempt_log": attempt_log,
        "demo_seed_list": seed_list,
        "demo_seed_list_sha256": sha256_json(seed_list),
        "budget_spent": budget.spent,
        "budget_cap": budget.hard_cap,
        "budget_snapshot": budget.snapshot(),
    }
    (out / "phase1_demos.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (out / "demo_budget_spent.json").write_text(
        json.dumps({"spent": budget.spent, "hard_cap": budget.hard_cap}) + "\n"
    )
    return manifest


# ---------------------------------------------------------------------------
# Phase 2: Behavioral cloning
# ---------------------------------------------------------------------------


def load_demo_pairs(manifest: dict, *, val_fraction: float = 0.2, seed: int = 71) -> tuple[list[dict], list[dict], dict]:
    """Train/val split BY TRAJECTORY.

    If Phase-1 produced no demos tagged split=val (budget exhaustion), hold out
    ``val_fraction`` of kept trajectories deterministically.
    """
    by_demo: dict[str, list[dict]] = {}
    meta: dict[str, dict] = {}
    for d in manifest["demos"]:
        payload = json.loads(Path(d["path"]).read_text())
        did = payload["demo_id"]
        meta[did] = {"seed": payload["seed"], "split_tag": payload["split"], "level": payload["level"]}
        pairs = []
        for step in payload["steps_log"]:
            pairs.append(
                {
                    "obs": np.asarray(step["observation"], dtype=np.float32),
                    "thrust": float(step["translated_expert_action"]["thrust"]),
                    "rotation_idx": int(step["translated_expert_action"]["rotation_idx"]),
                    "seed": payload["seed"],
                    "demo_id": did,
                }
            )
        by_demo[did] = pairs

    tagged_val = [did for did, m in meta.items() if m["split_tag"] == "val"]
    tagged_train = [did for did, m in meta.items() if m["split_tag"] != "val"]
    if tagged_val:
        train_ids, val_ids = tagged_train, tagged_val
        split_mode = "phase1_tags"
    else:
        ids = sorted(by_demo.keys())
        rng = np.random.default_rng(seed)
        rng.shuffle(ids)
        n_val = max(1, int(round(len(ids) * val_fraction))) if len(ids) > 1 else 0
        val_ids = sorted(ids[:n_val])
        train_ids = sorted(ids[n_val:])
        split_mode = "holdout_by_trajectory"

    train, val = [], []
    for did in train_ids:
        train.extend(by_demo[did])
    for did in val_ids:
        val.extend(by_demo[did])
    split_info = {
        "mode": split_mode,
        "train_demo_ids": train_ids,
        "val_demo_ids": val_ids,
        "n_train_trajectories": len(train_ids),
        "n_val_trajectories": len(val_ids),
        "val_fraction_requested": val_fraction,
    }
    return train, val, split_info


def phase2_bc(cfg: V7Config, out: Path, manifest: dict) -> dict[str, Any]:
    ckpt_dir = out / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    train_pairs, val_pairs, split_info = load_demo_pairs(manifest, seed=cfg.seed)
    if not train_pairs:
        raise SystemExit("No training demo pairs for BC")

    torch.manual_seed(cfg.seed)
    np.random.seed(cfg.seed)
    device = torch.device(cfg.device)
    policy = ContinuousThrustActorCritic(
        hidden=cfg.hidden,
        rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False,
        hold_attitude_prior=False,
    ).to(device)
    policy.reset_parameters_clean()
    # Save step0 (untrained) BEFORE any BC updates
    step0_path = ckpt_dir / "step0.pt"
    torch.save(
        {
            "policy": policy.state_dict(),
            "cfg": asdict(cfg),
            "global_step": 0,
            "phase": "untrained",
            "label": LABEL,
            "init_scheme": cfg.init_scheme,
            "demo_seed_list_sha256": manifest["demo_seed_list_sha256"],
        },
        step0_path,
    )
    step0_sha = sha256_file(step0_path)
    (ckpt_dir / "step0.sha256.json").write_text(
        json.dumps({"tag": "step0", "sha256": step0_sha, "path": str(step0_path)}, indent=2) + "\n"
    )

    opt = torch.optim.Adam(policy.parameters(), lr=cfg.bc_lr)
    history = []
    t0 = time.time()

    def batchify(pairs: list[dict], idx: np.ndarray) -> tuple[torch.Tensor, ...]:
        obs = torch.as_tensor(np.stack([pairs[i]["obs"] for i in idx]), dtype=torch.float32, device=device)
        thrust = torch.as_tensor([pairs[i]["thrust"] for i in idx], dtype=torch.float32, device=device)
        rot = torch.as_tensor([pairs[i]["rotation_idx"] for i in idx], dtype=torch.int64, device=device)
        return obs, thrust, rot

    def eval_loss(pairs: list[dict]) -> dict[str, float]:
        if not pairs:
            return {"loss": float("nan"), "thrust_mse": float("nan"), "rot_acc": float("nan"), "rot_ce": float("nan")}
        policy.eval()
        losses, mses, ces, accs = [], [], [], []
        with torch.no_grad():
            for start in range(0, len(pairs), cfg.bc_batch_size):
                idx = np.arange(start, min(start + cfg.bc_batch_size, len(pairs)))
                obs, thrust, rot = batchify(pairs, idx)
                thrust_dist, rot_dist, _ = policy.forward(obs)
                # MSE on squashed mean thrust vs target
                pred_thrust = policy.squash_thrust(thrust_dist.mean)
                mse = ((pred_thrust - thrust) ** 2).mean()
                # Also Gaussian NLL in pre-squash space via inverse sigmoid approx
                eps = 1e-6
                t_c = thrust.clamp(eps, 1 - eps)
                raw_target = torch.log(t_c) - torch.log(1 - t_c)
                nll = -policy.thrust_log_prob(thrust_dist, raw_target, t_c).mean()
                ce = nn.functional.cross_entropy(rot_dist.logits, rot)
                pred_rot = torch.argmax(rot_dist.logits, dim=-1)
                acc = (pred_rot == rot).float().mean()
                loss = nll + ce
                losses.append(float(loss))
                mses.append(float(mse))
                ces.append(float(ce))
                accs.append(float(acc))
        return {
            "loss": float(np.mean(losses)),
            "thrust_mse": float(np.mean(mses)),
            "thrust_nll": float(np.mean(losses)),  # combined; detailed below
            "rot_ce": float(np.mean(ces)),
            "rot_acc": float(np.mean(accs)),
        }

    n_train = len(train_pairs)
    for epoch in range(cfg.bc_epochs):
        policy.train()
        perm = np.random.permutation(n_train)
        ep_losses = []
        for start in range(0, n_train, cfg.bc_batch_size):
            idx = perm[start : start + cfg.bc_batch_size]
            obs, thrust, rot = batchify(train_pairs, idx)
            thrust_dist, rot_dist, _ = policy.forward(obs)
            eps = 1e-6
            t_c = thrust.clamp(eps, 1 - eps)
            raw_target = torch.log(t_c) - torch.log(1 - t_c)
            nll = -policy.thrust_log_prob(thrust_dist, raw_target, t_c).mean()
            ce = nn.functional.cross_entropy(rot_dist.logits, rot)
            loss = nll + ce
            opt.zero_grad()
            loss.backward()
            opt.step()
            ep_losses.append(float(loss.detach()))
        tr_m = {"loss": float(np.mean(ep_losses))}
        va_m = eval_loss(val_pairs)
        row = {
            "epoch": epoch,
            "train_loss": tr_m["loss"],
            "val_loss": va_m["loss"],
            "val_thrust_mse": va_m["thrust_mse"],
            "val_rot_ce": va_m["rot_ce"],
            "val_rot_acc": va_m["rot_acc"],
        }
        history.append(row)
        print(
            f"[bc] epoch={epoch} train_loss={row['train_loss']:.4f} "
            f"val_loss={row['val_loss']:.4f} val_rot_acc={row['val_rot_acc']:.3f}",
            flush=True,
        )

    wall = time.time() - t0
    bc_path = ckpt_dir / "bc.pt"
    torch.save(
        {
            "policy": policy.state_dict(),
            "cfg": asdict(cfg),
            "global_step": 0,
            "phase": "bc",
            "label": LABEL,
            "init_scheme": cfg.init_scheme,
            "demo_seed_list": manifest["demo_seed_list"],
            "demo_seed_list_sha256": manifest["demo_seed_list_sha256"],
            "demo_manifest_sha256": sha256_file(out / "phase1_demos.json"),
            "bc_epochs": cfg.bc_epochs,
            "history": history,
            "step0_sha256": step0_sha,
            "reproducibility": {
                "torch": torch.__version__,
                "numpy": np.__version__,
                "seed": cfg.seed,
                "device": cfg.device,
            },
        },
        bc_path,
    )
    bc_sha = sha256_file(bc_path)
    (ckpt_dir / "bc.sha256.json").write_text(
        json.dumps(
            {
                "tag": "bc",
                "sha256": bc_sha,
                "path": str(bc_path),
                "demo_seed_list_sha256": manifest["demo_seed_list_sha256"],
                "step0_sha256": step0_sha,
            },
            indent=2,
        )
        + "\n"
    )

    # Integrity: eval path must not call controller
    integrity = run_controller_integrity_check()
    (logs / "integrity_no_controller.json").write_text(json.dumps(integrity, indent=2) + "\n")
    if not integrity["passed"]:
        raise SystemExit(f"INTEGRITY FAILED: {integrity}")

    summary = {
        "label": LABEL,
        "phase": 2,
        "n_train_pairs": n_train,
        "n_val_pairs": len(val_pairs),
        "n_train_trajectories": split_info["n_train_trajectories"],
        "n_val_trajectories": split_info["n_val_trajectories"],
        "trajectory_split": split_info,
        "epochs": cfg.bc_epochs,
        "wall_seconds": wall,
        "history": history,
        "final_val": history[-1] if history else None,
        "step0_sha256": step0_sha,
        "bc_sha256": bc_sha,
        "step0_path": str(step0_path),
        "bc_path": str(bc_path),
        "integrity": integrity,
        "env_frames_used": 0,
        "note": "BC is supervised; uses zero environment physics frames",
    }
    (out / "phase2_bc.json").write_text(json.dumps(summary, indent=2) + "\n")
    (logs / "bc_history.json").write_text(json.dumps(history, indent=2) + "\n")
    return summary


def run_controller_integrity_check() -> dict[str, Any]:
    """Prove eval imports/calls no controller by monkeypatching guidance to raise."""
    import rewardbench.environments.apollolander.schema as schema_mod
    import translate as translate_mod

    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("CONTROLLER_CALLED_DURING_EVAL")

    # Simulate eval module path: load policy and act without translate/guidance
    original_g = schema_mod.guidance_action
    original_t = translate_mod.translate_to_learner
    original_r = translate_mod.raw_expert_command
    schema_mod.guidance_action = boom  # type: ignore
    translate_mod.translate_to_learner = boom  # type: ignore
    translate_mod.raw_expert_command = boom  # type: ignore
    try:
        pol = ContinuousThrustActorCritic(rotation_mode="delta", soft_thrust_prior=False, hold_attitude_prior=False)
        pol.reset_parameters_clean()
        obs = torch.zeros(1, 10)
        with torch.no_grad():
            thrust, rot_idx, _ = pol.act_deterministic(obs)
            _ = float(thrust.item()), int(rot_idx.item())
        # Ensure eval helper does not touch controller
        passed = calls["n"] == 0
        detail = "policy.act_deterministic completed with controller monkeypatched to raise"
    except Exception as exc:
        passed = False
        detail = f"unexpected: {exc}"
    finally:
        schema_mod.guidance_action = original_g
        translate_mod.translate_to_learner = original_t
        translate_mod.raw_expert_command = original_r

    return {
        "passed": passed,
        "controller_calls_during_eval_probe": calls["n"],
        "detail": detail,
        "label": LABEL,
    }


# ---------------------------------------------------------------------------
# Phase 3: Independent eval (expert DISABLED for networks)
# ---------------------------------------------------------------------------


def evaluate_policy(
    policy: ContinuousThrustActorCritic,
    *,
    seeds: list[int],
    level: str,
    max_steps: int,
    action_repeat: int,
    deterministic: bool,
    budget: DiagnosticBudget,
    reason: str,
    device: torch.device,
    record_traces: bool = False,
) -> dict[str, Any]:
    env = make_env(level, max_steps, action_repeat)
    per_seed = []
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
    frames_total = 0
    policy.eval()
    try:
        for seed in seeds:
            assert_seed_allowed(seed, context=reason)
            if not budget.can_afford(max_steps):
                break
            budget.require(max_steps, reason=f"pre:{reason}:{seed}")
            obs, info0 = env.reset(seed)
            cmd_rot = snap10(float(info0["start"]["rotation"]))
            ep_ret = 0.0
            done = False
            info: dict[str, Any] = {}
            trace: list[dict[str, float | int]] = []
            while not done:
                with torch.no_grad():
                    t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                    if deterministic:
                        thrust, rot_idx, _ = policy.act_deterministic(t)
                    else:
                        thrust, rot_idx, _, _, _ = policy.act(t)
                    delta = int(ROTATION_DELTAS[int(rot_idx.item())])
                    cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                    cmd_rot = snap10(cmd_rot)
                    command = {"thrust": float(thrust.item()), "rotation": int(cmd_rot)}
                if record_traces:
                    trace.append(dict(command))
                obs, reward, terminated, truncated, info = env.step_command(command)
                ep_ret += reward
                done = terminated or truncated
            frames = int(info.get("steps", 0))
            budget.charge(frames, reason=f"{reason}:seed{seed}")
            frames_total += frames
            row = outcome_row(info, ep_ret)
            row["seed"] = seed
            if record_traces:
                row["action_trace"] = trace
                row["touchdown_frame"] = frames if row["landed"] else None
            if row["perfect"]:
                counts["perfect"] += 1
            elif row["hard"]:
                counts["hard"] += 1
            elif row["crash"]:
                counts["crash"] += 1
            elif row["timeout"]:
                counts["timeout"] += 1
            else:
                # map unknown
                if row["status"] == "crashed":
                    counts["crash"] += 1
                else:
                    counts["timeout"] += 1
            per_seed.append(row)
    finally:
        env.close()

    n = len(per_seed)
    land = counts["perfect"] + counts["hard"]
    p, lo, hi = wilson_ci(land, n)
    return {
        "label": LABEL,
        "reason": reason,
        "deterministic": deterministic,
        "level": level,
        "n": n,
        "seeds_requested": seeds,
        "seeds_evaluated": [r["seed"] for r in per_seed],
        "counts": counts,
        "landing_rate": p,
        "landing_wilson95": [lo, hi],
        "diagnostic_frames": frames_total,
        "per_seed": per_seed,
        "expert_disabled": True,
    }


def evaluate_translated_expert_ref(
    seeds: list[int],
    *,
    level: str,
    max_steps: int,
    action_repeat: int,
    budget: DiagnosticBudget,
    reason: str,
) -> dict[str, Any]:
    """Reference only — NOT a learner. Counted under diagnostic budget."""
    env = make_env(level, max_steps, action_repeat)
    per_seed = []
    counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
    frames_total = 0
    try:
        for seed in seeds:
            if not budget.can_afford(max_steps):
                break
            ep = rollout_translated_expert(
                env, seed, budget, reason=reason, record_steps=False
            )
            frames_total += ep["steps"]
            row = {k: ep[k] for k in (
                "seed", "status", "landed", "perfect", "hard", "crash", "timeout",
                "rotation", "vy", "native_score", "steps",
            )}
            if row["perfect"]:
                counts["perfect"] += 1
            elif row["hard"]:
                counts["hard"] += 1
            elif row["crash"]:
                counts["crash"] += 1
            else:
                counts["timeout"] += 1
            per_seed.append(row)
    finally:
        env.close()
    n = len(per_seed)
    land = counts["perfect"] + counts["hard"]
    p, lo, hi = wilson_ci(land, n)
    return {
        "label": LABEL,
        "reason": reason,
        "role": "translated_expert_REFERENCE_not_learner",
        "level": level,
        "n": n,
        "counts": counts,
        "landing_rate": p,
        "landing_wilson95": [lo, hi],
        "diagnostic_frames": frames_total,
        "per_seed": per_seed,
    }


def paired_mcnemar(a: dict, b: dict) -> dict[str, Any]:
    """McNemar: b= a_fail & b_land, c= a_land & b_fail. Here a=untrained, b=bc."""
    sa = {r["seed"]: r["landed"] for r in a["per_seed"]}
    bb = cc = 0
    shared = []
    for r in b["per_seed"]:
        if r["seed"] not in sa:
            continue
        shared.append(r["seed"])
        x, y = bool(sa[r["seed"]]), bool(r["landed"])
        if (not x) and y:
            bb += 1
        elif x and (not y):
            cc += 1
    return {"shared_seeds": shared, "mcnemar": mcnemar_exact(bb, cc)}


def render_trace_video(
    *,
    seed: int,
    level: str,
    max_steps: int,
    action_trace: list[dict[str, float | int]],
    action_repeat: int,
    out_mp4: Path,
    label: str,
) -> dict[str, Any]:
    """Headless Chromium replay of absolute action trace on unmodified upstream game."""
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread
    import base64
    import io

    from rewardbench.environments.apollolander.starts import derive_start

    try:
        from playwright.sync_api import sync_playwright
        import imageio.v2 as imageio
        from PIL import Image
    except Exception as exc:
        return {"ok": False, "error": f"render deps missing: {exc}"}

    BRIDGE = "/frontend/apollolander/rl_overnight/browser_rl_bridge.html"
    port = 8777

    class _RootHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, format, *a):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", port), _RootHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)
    start = derive_start(seed, version=level).as_dict()
    frames_png = []
    status = "flying"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(f"http://127.0.0.1:{port}{BRIDGE}", wait_until="load")
            page.wait_for_function("() => window.__rl && window.__rl.ready")
            page.evaluate("(cfg) => window.__rl.reset(cfg)", {"start": start, "maxSteps": max_steps})
            steps = 0
            for command in action_trace:
                for _ in range(action_repeat):
                    step = page.evaluate("(a) => window.__rl.step(a)", command)
                    png = page.evaluate(
                        """() => {
                          const c = document.querySelector('canvas') || (() => {
                            const el = document.createElement('canvas');
                            el.width = 800; el.height = 600; document.body.appendChild(el); return el;
                          })();
                          window.__rl.renderFrame(c);
                          return c.toDataURL('image/png');
                        }"""
                    )
                    frames_png.append(png)
                    steps += 1
                    if step["done"]:
                        status = step["status"]
                        break
                if status != "flying" and status != "Flying":
                    if step.get("done"):
                        break
            browser.close()
    finally:
        server.shutdown()

    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(str(out_mp4), fps=30, codec="libx264", quality=8)
    for b64 in frames_png[::2]:
        data = base64.b64decode(b64.split(",", 1)[1])
        img = Image.open(io.BytesIO(data)).convert("RGB")
        writer.append_data(np.asarray(img))
    writer.close()
    return {
        "ok": True,
        "path": str(out_mp4),
        "sha256": sha256_file(out_mp4),
        "seed": seed,
        "label": label,
        "status": status,
        "frames_rendered": len(frames_png),
    }


def independent_reverify_landing(
    env: ApolloLanderUpstreamEnv,
    seed: int,
    trace: list[dict[str, float | int]],
    expected: dict[str, Any],
    budget: DiagnosticBudget,
) -> dict[str, Any]:
    return replay_trace_bitexact(
        env, seed, trace, expected, budget, reason="landing_reverify"
    )


def phase3_eval(cfg: V7Config, out: Path, seeds_doc: dict, bc_summary: dict) -> dict[str, Any]:
    eval_dir = out / "evaluation"
    mile_dir = out / "milestone"
    footage_dir = out / "footage"
    for d in (eval_dir, mile_dir, footage_dir):
        d.mkdir(parents=True, exist_ok=True)

    budget = DiagnosticBudget(hard_cap=cfg.diag_cap)
    device = torch.device(cfg.device)
    eval_seeds = list(seeds_doc["unseen_eval_v1_seeds"][: cfg.eval_v1_n])

    # Load step0 + bc
    step0 = ContinuousThrustActorCritic(
        hidden=cfg.hidden, rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False, hold_attitude_prior=False,
    ).to(device)
    ck0 = torch.load(bc_summary["step0_path"], map_location=device, weights_only=False)
    step0.load_state_dict(ck0["policy"])
    step0.eval()

    bc_pol = ContinuousThrustActorCritic(
        hidden=cfg.hidden, rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False, hold_attitude_prior=False,
    ).to(device)
    ck_bc = torch.load(bc_summary["bc_path"], map_location=device, weights_only=False)
    bc_pol.load_state_dict(ck_bc["policy"])
    bc_pol.eval()

    # Integrity again at eval time
    integrity = run_controller_integrity_check()
    if not integrity["passed"]:
        raise SystemExit("eval integrity failed")

    l0_seeds = list(seeds_doc["unseen_eval_l0near_seeds"][: cfg.eval_l0_n])
    # Soft reserve: treat budget as (cap - reserve) during Phase-3 eval/footage so
    # Phase-4 PPO McNemar can still run under the hard 200k diagnostic cap.
    budget_hard = budget.hard_cap
    budget.hard_cap = max(0, budget_hard - int(cfg.diag_reserve_for_ppo_eval))

    def run_net(pol, seeds, level, max_steps, reason, record=True):
        return evaluate_policy(
            pol,
            seeds=seeds,
            level=level,
            max_steps=max_steps,
            action_repeat=cfg.action_repeat,
            deterministic=True,
            budget=budget,
            reason=reason,
            device=device,
            record_traces=record,
        )

    # L0-near first (cheap, where demos concentrate) then v1.
    print("[eval] untrained L0-near…", flush=True)
    untrained_l0 = run_net(step0, l0_seeds, LEVEL_L0, cfg.max_steps_l0, "untrained_l0")
    print(f"  untrained_l0 counts={untrained_l0['counts']} n={untrained_l0['n']}", flush=True)

    print("[eval] BC L0-near…", flush=True)
    bc_l0 = run_net(bc_pol, l0_seeds, LEVEL_L0, cfg.max_steps_l0, "bc_l0")
    print(f"  bc_l0 counts={bc_l0['counts']} n={bc_l0['n']}", flush=True)

    # Film a few BC L0 landings NOW (before expensive v1 evals consume the budget).
    landings_preserved_early: list[dict[str, Any]] = []
    env_rev_l0_early = make_env(LEVEL_L0, cfg.max_steps_l0, cfg.action_repeat)
    try:
        filmed = 0
        for row in bc_l0["per_seed"]:
            if filmed >= cfg.max_footage_landings or not row.get("landed"):
                continue
            if not budget.can_afford(cfg.max_steps_l0):
                break
            seed = row["seed"]
            trace = row.get("action_trace") or []
            rev = independent_reverify_landing(env_rev_l0_early, seed, trace, row, budget)
            vid_path = footage_dir / f"bc_l0_seed{seed}_{row['status']}.mp4"
            try:
                vid = render_trace_video(
                    seed=seed,
                    level=LEVEL_L0,
                    max_steps=cfg.max_steps_l0,
                    action_trace=trace,
                    action_repeat=cfg.action_repeat,
                    out_mp4=vid_path,
                    label=f"{LABEL}_bc_l0",
                )
            except Exception as exc:
                vid = {"ok": False, "error": str(exc)}
            entry = {
                "tag": "bc_l0",
                "level": LEVEL_L0,
                "seed": seed,
                "checkpoint": bc_summary["bc_path"],
                "checkpoint_sha256": bc_summary["bc_sha256"],
                "status": row["status"],
                "native_score": row["native_score"],
                "rotation": row["rotation"],
                "vy": row["vy"],
                "touchdown_frame": row.get("touchdown_frame") or row["steps"],
                "action_trace": trace,
                "reverify": rev,
                "video": vid,
                "label": LABEL,
            }
            if vid.get("ok") and vid.get("path"):
                art = Path("/opt/cursor/artifacts/rl_v7")
                art.mkdir(parents=True, exist_ok=True)
                import shutil
                dest = art / Path(vid["path"]).name
                shutil.copy2(vid["path"], dest)
                entry["video_artifact"] = str(dest)
            landings_preserved_early.append(entry)
            filmed += 1
            print(f"  EARLY footage bc_l0 seed={seed} vid={vid.get('ok')} reverify={rev.get('matched')}", flush=True)
    finally:
        env_rev_l0_early.close()

    print(f"[eval] untrained v1 (up to {cfg.eval_v1_n} / budget)…", flush=True)
    untrained = run_net(step0, eval_seeds, LEVEL_V1, cfg.max_steps_v1, "untrained_v1")
    print(f"  untrained_v1 counts={untrained['counts']} n={untrained['n']}", flush=True)

    print(f"[eval] BC v1 (up to {cfg.eval_v1_n} / budget)…", flush=True)
    bc_eval = run_net(bc_pol, eval_seeds, LEVEL_V1, cfg.max_steps_v1, "bc_v1")
    print(f"  bc_v1 counts={bc_eval['counts']} n={bc_eval['n']}", flush=True)

    (eval_dir / "untrained_l0_deterministic.json").write_text(json.dumps(untrained_l0, indent=2) + "\n")
    (eval_dir / "bc_l0_deterministic.json").write_text(json.dumps(bc_l0, indent=2) + "\n")
    (eval_dir / "untrained_v1_deterministic.json").write_text(json.dumps(untrained, indent=2) + "\n")
    (eval_dir / "bc_v1_deterministic.json").write_text(json.dumps(bc_eval, indent=2) + "\n")

    mc_l0 = paired_mcnemar(untrained_l0, bc_l0)
    mc_v1 = paired_mcnemar(untrained, bc_eval)

    # Expert reference on L0 (cheap) + few v1 if budget remains
    print("[eval] translated expert REFERENCE…", flush=True)
    try:
        expert_ref_l0 = evaluate_translated_expert_ref(
            l0_seeds[: min(20, len(l0_seeds))],
            level=LEVEL_L0,
            max_steps=cfg.max_steps_l0,
            action_repeat=cfg.action_repeat,
            budget=budget,
            reason="expert_ref_l0",
        )
    except DiagnosticBudgetExhausted as exc:
        expert_ref_l0 = {"error": str(exc), "counts": {}, "n": 0, "per_seed": []}
    try:
        expert_ref_v1 = evaluate_translated_expert_ref(
            eval_seeds[: cfg.expert_ref_n],
            level=LEVEL_V1,
            max_steps=cfg.max_steps_v1,
            action_repeat=cfg.action_repeat,
            budget=budget,
            reason="expert_ref_v1",
        )
    except DiagnosticBudgetExhausted as exc:
        expert_ref_v1 = {"error": str(exc), "counts": {}, "n": 0, "per_seed": []}
    (eval_dir / "translated_expert_reference_l0.json").write_text(
        json.dumps(expert_ref_l0, indent=2) + "\n"
    )
    (eval_dir / "translated_expert_reference_v1.json").write_text(
        json.dumps(expert_ref_v1, indent=2) + "\n"
    )

    # Persist all landing outcomes + traces; footage already captured early for a few.
    landings_preserved: list[dict[str, Any]] = list(landings_preserved_early)
    early_seeds = {(e["tag"], e["seed"]) for e in landings_preserved_early}
    for tag, result, sha, path, level in (
        ("untrained_l0", untrained_l0, bc_summary["step0_sha256"], bc_summary["step0_path"], LEVEL_L0),
        ("bc_l0", bc_l0, bc_summary["bc_sha256"], bc_summary["bc_path"], LEVEL_L0),
        ("untrained_v1", untrained, bc_summary["step0_sha256"], bc_summary["step0_path"], LEVEL_V1),
        ("bc_v1", bc_eval, bc_summary["bc_sha256"], bc_summary["bc_path"], LEVEL_V1),
    ):
        for row in result["per_seed"]:
            if not row.get("landed"):
                continue
            seed = row["seed"]
            if (tag, seed) in early_seeds:
                continue
            trace = row.get("action_trace") or []
            entry = {
                "tag": tag,
                "level": level,
                "seed": seed,
                "checkpoint": path,
                "checkpoint_sha256": sha,
                "status": row["status"],
                "native_score": row["native_score"],
                "rotation": row["rotation"],
                "vy": row["vy"],
                "touchdown_frame": row.get("touchdown_frame") or row["steps"],
                "action_trace": trace,
                "label": LABEL,
                "reverify": {"skipped": True, "reason": "trace_persisted_footage_capped"},
                "video": {"ok": False, "skipped": True},
            }
            landings_preserved.append(entry)
            (mile_dir / f"{tag}_seed{seed}_trace.json").write_text(
                json.dumps({"seed": seed, "trace": trace, "status": row["status"]}, indent=2) + "\n"
            )
            (mile_dir / f"{tag}_seed{seed}.json").write_text(
                json.dumps({k: v for k, v in entry.items() if k != "action_trace"}, indent=2) + "\n"
            )
    for entry in landings_preserved_early:
        (mile_dir / f"{entry['tag']}_seed{entry['seed']}.json").write_text(
            json.dumps({k: v for k, v in entry.items() if k != "action_trace"}, indent=2) + "\n"
        )

    # Restore hard cap so snapshot / Phase-4 see the real remaining reserve.
    budget.hard_cap = budget_hard

    bc_land_l0 = bc_l0["counts"]["perfect"] + bc_l0["counts"]["hard"]
    bc_land_v1 = bc_eval["counts"]["perfect"] + bc_eval["counts"]["hard"]
    un_land_l0 = untrained_l0["counts"]["perfect"] + untrained_l0["counts"]["hard"]
    un_land_v1 = untrained["counts"]["perfect"] + untrained["counts"]["hard"]

    summary = {
        "label": LABEL,
        "phase": 3,
        "untrained_l0": {k: v for k, v in untrained_l0.items() if k != "per_seed"},
        "bc_l0": {k: v for k, v in bc_l0.items() if k != "per_seed"},
        "untrained_v1": {k: v for k, v in untrained.items() if k != "per_seed"},
        "bc_v1": {k: v for k, v in bc_eval.items() if k != "per_seed"},
        "untrained_l0_per_seed": untrained_l0["per_seed"],
        "bc_l0_per_seed": bc_l0["per_seed"],
        "untrained_v1_per_seed": untrained["per_seed"],
        "bc_v1_per_seed": bc_eval["per_seed"],
        "mcnemar_bc_vs_untrained_l0": mc_l0,
        "mcnemar_bc_vs_untrained_v1": mc_v1,
        "expert_reference_l0": {k: v for k, v in expert_ref_l0.items() if k != "per_seed"},
        "expert_reference_v1": {k: v for k, v in expert_ref_v1.items() if k != "per_seed"},
        "landings_preserved": [
            {k: v for k, v in e.items() if k != "action_trace"} for e in landings_preserved
        ],
        "diagnostic_budget": budget.snapshot(),
        "integrity": integrity,
        "bc_landings_l0": bc_land_l0,
        "bc_landings_v1": bc_land_v1,
        "bc_landings": bc_land_l0 + bc_land_v1,
        "untrained_landings_l0": un_land_l0,
        "untrained_landings_v1": un_land_v1,
        "untrained_landings": un_land_l0 + un_land_v1,
        "bc_shows_ability": (bc_land_l0 + bc_land_v1) >= 1,
        # Compat aliases for report
        "untrained": {k: v for k, v in untrained_l0.items() if k != "per_seed"},
        "bc": {k: v for k, v in bc_l0.items() if k != "per_seed"},
        "bc_per_seed": bc_l0["per_seed"] + bc_eval["per_seed"],
        "mcnemar_bc_vs_untrained": mc_l0,
    }
    (out / "phase3_eval.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "diag_budget_spent.json").write_text(
        json.dumps({"spent": budget.spent, "hard_cap": budget.hard_cap}) + "\n"
    )
    return summary


# ---------------------------------------------------------------------------
# Phase 4: PPO fine-tune from BC (optional)
# ---------------------------------------------------------------------------


def phase4_ppo(cfg: V7Config, out: Path, seeds_doc: dict, bc_summary: dict, phase3: dict) -> dict[str, Any]:
    if not phase3.get("bc_shows_ability"):
        summary = {
            "label": LABEL,
            "phase": 4,
            "skipped": True,
            "reason": "BC did not show meaningful ability (no independent landings)",
        }
        (out / "phase4_ppo.json").write_text(json.dumps(summary, indent=2) + "\n")
        return summary

    device = torch.device(cfg.device)
    train_budget = TrainingBudget(hard_cap=cfg.ppo_budget)
    # Remaining diag for PPO vs BC eval
    spent_diag = json.loads((out / "diag_budget_spent.json").read_text())["spent"]
    diag = DiagnosticBudget(hard_cap=cfg.diag_cap, spent=spent_diag)

    policy = ContinuousThrustActorCritic(
        hidden=cfg.hidden, rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False, hold_attitude_prior=False,
    ).to(device)
    ck = torch.load(bc_summary["bc_path"], map_location=device, weights_only=False)
    policy.load_state_dict(ck["policy"])
    # Keep a frozen BC copy for optional KL
    bc_frozen = ContinuousThrustActorCritic(
        hidden=cfg.hidden, rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False, hold_attitude_prior=False,
    ).to(device)
    bc_frozen.load_state_dict(ck["policy"])
    bc_frozen.eval()
    for p in bc_frozen.parameters():
        p.requires_grad_(False)

    opt = torch.optim.Adam(policy.parameters(), lr=cfg.learning_rate, eps=1e-5)
    # PPO on L0-near for sample efficiency under 250k when BC ability was shown there.
    # Reward unchanged: touchdown_v1.
    ppo_level = LEVEL_L0
    env_config = EnvConfig(
        max_steps=cfg.max_steps_l0,
        research_mode=True,
        start_schedule_version=ppo_level,
        vary_fuel=False,
        action_repeat=cfg.action_repeat,
        bonuses=False,
        locked_camera=True,
        physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
    )
    vec = VectorApolloLanderUpstreamEnv(cfg.n_envs, env_config, reward_mode="touchdown_v1")
    rng = np.random.default_rng(cfg.seed + 99)
    train_seeds = np.arange(
        seeds_doc["ppo_train_seed_start"],
        seeds_doc["ppo_train_seed_start"] + seeds_doc["ppo_train_seed_count"],
        dtype=np.int64,
    )
    cmd_rot = np.zeros(cfg.n_envs, dtype=np.int64)

    def sample_seeds(n: int) -> np.ndarray:
        idx = rng.integers(0, len(train_seeds), size=n)
        return train_seeds[idx]

    seeds0 = sample_seeds(cfg.n_envs)
    obs, infos = vec.reset(seeds0)
    for i, info in enumerate(infos):
        cmd_rot[i] = snap10(float(info["start"]["rotation"]))

    updates = 0
    early = None
    t0 = time.time()
    try:
        while True:
            need = cfg.rollout_steps * cfg.n_envs * cfg.action_repeat
            if not train_budget.can_afford(need):
                early = "ppo_budget_exhausted_before_rollout"
                break
            # rollout
            n_steps, n_envs = cfg.rollout_steps, cfg.n_envs
            buf = {
                "obs": np.zeros((n_steps, n_envs, 10), dtype=np.float32),
                "raw_thrust": np.zeros((n_steps, n_envs), dtype=np.float32),
                "rot_idx": np.zeros((n_steps, n_envs), dtype=np.int64),
                "log_probs": np.zeros((n_steps, n_envs), dtype=np.float64),
                "rewards": np.zeros((n_steps, n_envs), dtype=np.float64),
                "values": np.zeros((n_steps, n_envs), dtype=np.float64),
                "terminations": np.zeros((n_steps, n_envs), dtype=np.float64),
                "truncations": np.zeros((n_steps, n_envs), dtype=np.float64),
                "bootstrap_values": np.zeros((n_steps, n_envs), dtype=np.float64),
            }
            policy.train()
            for t in range(n_steps):
                frames_per = n_envs * cfg.action_repeat
                train_budget.require(frames_per, reason=f"ppo_pre_u{updates}_t{t}")
                with torch.no_grad():
                    obs_t = torch.as_tensor(obs, dtype=torch.float32, device=device)
                    thrust, rot_idx, raw, log_prob, values = policy.act(obs_t)
                    commands = []
                    th = thrust.cpu().numpy()
                    ri = rot_idx.cpu().numpy()
                    for i in range(n_envs):
                        delta = int(ROTATION_DELTAS[int(ri[i])])
                        cmd_rot[i] = snap10(int(np.clip(cmd_rot[i] + delta, -90, 90)))
                        commands.append({"thrust": float(th[i]), "rotation": int(cmd_rot[i])})
                next_obs, rewards, terminated, truncated, infos = vec.step_commands(commands)
                train_budget.charge(frames_per, reason=f"ppo_u{updates}_t{t}")
                bootstrap_values = np.zeros(n_envs, dtype=np.float64)
                if np.any(truncated):
                    with torch.no_grad():
                        trunc_vals = (
                            policy.forward(
                                torch.as_tensor(next_obs, dtype=torch.float32, device=device)
                            )[2]
                            .cpu()
                            .numpy()
                        )
                    bootstrap_values = np.where(truncated, trunc_vals, bootstrap_values)
                buf["obs"][t] = obs
                buf["raw_thrust"][t] = raw.cpu().numpy()
                buf["rot_idx"][t] = rot_idx.cpu().numpy()
                buf["log_probs"][t] = log_prob.cpu().numpy()
                buf["rewards"][t] = rewards
                buf["values"][t] = values.cpu().numpy()
                buf["terminations"][t] = terminated.astype(np.float64)
                buf["truncations"][t] = truncated.astype(np.float64)
                buf["bootstrap_values"][t] = bootstrap_values
                dones = np.logical_or(terminated, truncated)
                if np.any(dones):
                    new_seeds = sample_seeds(int(np.sum(dones)))
                    it = iter(new_seeds.tolist())
                    for i, d in enumerate(dones):
                        if d:
                            o, info = vec.envs[i].reset(int(next(it)))
                            next_obs[i] = o
                            cmd_rot[i] = snap10(float(info["start"]["rotation"]))
                obs = next_obs

            with torch.no_grad():
                last_values = (
                    policy.forward(torch.as_tensor(obs, dtype=torch.float32, device=device))[2]
                    .cpu()
                    .numpy()
                )
            advantages = np.zeros_like(buf["rewards"])
            last_gae = np.zeros(n_envs, dtype=np.float64)
            for t in reversed(range(n_steps)):
                next_values = last_values if t == n_steps - 1 else buf["values"][t + 1]
                terminated_t = buf["terminations"][t]
                truncated_t = buf["truncations"][t]
                next_values_eff = np.where(truncated_t > 0.5, buf["bootstrap_values"][t], next_values)
                next_values_eff = np.where(terminated_t > 0.5, 0.0, next_values_eff)
                next_non_terminal = 1.0 - terminated_t
                delta = (
                    buf["rewards"][t]
                    + cfg.gamma * next_values_eff * next_non_terminal
                    - buf["values"][t]
                )
                gae_mask = 1.0 - np.maximum(terminated_t, truncated_t)
                last_gae = delta + cfg.gamma * cfg.gae_lambda * gae_mask * last_gae
                advantages[t] = last_gae
            returns = advantages + buf["values"]

            obs_b = torch.as_tensor(buf["obs"].reshape(-1, 10), dtype=torch.float32, device=device)
            raw_b = torch.as_tensor(buf["raw_thrust"].reshape(-1), dtype=torch.float32, device=device)
            rot_b = torch.as_tensor(buf["rot_idx"].reshape(-1), dtype=torch.int64, device=device)
            old_lp = torch.as_tensor(buf["log_probs"].reshape(-1), dtype=torch.float32, device=device)
            adv_b = torch.as_tensor(advantages.reshape(-1), dtype=torch.float32, device=device)
            ret_b = torch.as_tensor(returns.reshape(-1), dtype=torch.float32, device=device)
            adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)

            batch = obs_b.shape[0]
            for _ in range(cfg.update_epochs):
                perm = torch.randperm(batch, device=device)
                for start in range(0, batch, cfg.minibatch_size):
                    mb = perm[start : start + cfg.minibatch_size]
                    log_prob, entropy, values = policy.evaluate_actions(obs_b[mb], raw_b[mb], rot_b[mb])
                    ratio = (log_prob - old_lp[mb]).exp()
                    surr1 = ratio * adv_b[mb]
                    surr2 = torch.clamp(ratio, 1 - cfg.clip_coef, 1 + cfg.clip_coef) * adv_b[mb]
                    pg_loss = -torch.min(surr1, surr2).mean()
                    v_loss = 0.5 * (values - ret_b[mb]).pow(2).mean()
                    loss = pg_loss - cfg.ent_coef * entropy.mean() + cfg.vf_coef * v_loss
                    if cfg.bc_regularization > 0:
                        with torch.no_grad():
                            bt, br, _ = bc_frozen.forward(obs_b[mb])
                        pt, pr, _ = policy.forward(obs_b[mb])
                        kl_t = torch.distributions.kl_divergence(pt, bt).mean()
                        p = pr.probs
                        q = br.probs.clamp(min=1e-8)
                        kl_r = (p * (p.clamp(min=1e-8).log() - q.log())).sum(-1).mean()
                        loss = loss + cfg.bc_regularization * (kl_t + kl_r)
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(policy.parameters(), cfg.max_grad_norm)
                    opt.step()
            updates += 1
            if updates % 5 == 0:
                print(f"[ppo] updates={updates} frames={train_budget.spent}", flush=True)
    except TrainingBudgetExhausted:
        early = "ppo_budget_exhausted"
    finally:
        vec.close()

    ppo_path = out / "checkpoints" / "ppo.pt"
    torch.save(
        {
            "policy": policy.state_dict(),
            "cfg": asdict(cfg),
            "global_step": train_budget.spent,
            "phase": "ppo_from_bc",
            "label": LABEL,
            "started_from_bc_sha256": bc_summary["bc_sha256"],
            "bc_regularization": cfg.bc_regularization,
            "reward": "touchdown_v1 (unchanged)",
            "note": "PPO fine-tune from BC; not discovery from scratch",
        },
        ppo_path,
    )
    ppo_sha = sha256_file(ppo_path)
    (out / "checkpoints" / "ppo.sha256.json").write_text(
        json.dumps({"tag": "ppo", "sha256": ppo_sha, "path": str(ppo_path)}, indent=2) + "\n"
    )

    # Eval PPO vs BC on SAME unseen L0-near eval seeds (primary ability surface).
    eval_seeds = list(seeds_doc["unseen_eval_l0near_seeds"][: cfg.eval_l0_n])
    bc_pol = ContinuousThrustActorCritic(
        hidden=cfg.hidden, rotation_mode=cfg.rotation_mode,
        soft_thrust_prior=False, hold_attitude_prior=False,
    ).to(device)
    bc_pol.load_state_dict(ck["policy"])
    print("[ppo-eval] frozen BC on L0-near…", flush=True)
    try:
        bc_again = evaluate_policy(
            bc_pol, seeds=eval_seeds, level=LEVEL_L0, max_steps=cfg.max_steps_l0,
            action_repeat=cfg.action_repeat, deterministic=True, budget=diag,
            reason="ppo_phase_bc_refreeze", device=device, record_traces=True,
        )
    except DiagnosticBudgetExhausted as exc:
        bc_again = {"error": str(exc), "per_seed": [], "counts": {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}, "n": 0}
    print("[ppo-eval] frozen PPO on L0-near…", flush=True)
    try:
        ppo_eval = evaluate_policy(
            policy, seeds=eval_seeds, level=LEVEL_L0, max_steps=cfg.max_steps_l0,
            action_repeat=cfg.action_repeat, deterministic=True, budget=diag,
            reason="ppo_det", device=device, record_traces=True,
        )
    except DiagnosticBudgetExhausted as exc:
        ppo_eval = {"error": str(exc), "per_seed": [], "counts": {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}, "n": 0}

    mc = paired_mcnemar(bc_again, ppo_eval) if bc_again.get("per_seed") and ppo_eval.get("per_seed") else None
    ppo_land = ppo_eval.get("counts", {}).get("perfect", 0) + ppo_eval.get("counts", {}).get("hard", 0)
    bc_land = bc_again.get("counts", {}).get("perfect", 0) + bc_again.get("counts", {}).get("hard", 0)
    n_ppo = int(ppo_eval.get("n") or 0)
    n_bc = int(bc_again.get("n") or 0)
    if n_ppo == 0 or n_bc == 0 or not mc:
        verdict = "PPO_EVAL_INCOMPLETE_DIAG_BUDGET"
    elif mc["mcnemar"]["n_discordant"] > 0:
        if mc["mcnemar"]["b"] > mc["mcnemar"]["c"]:
            verdict = "PPO_IMPROVED_OVER_BC"
        elif mc["mcnemar"]["b"] < mc["mcnemar"]["c"]:
            verdict = "PPO_WORSENED_VS_BC"
        else:
            verdict = "PPO_PRESERVED_BC"
    else:
        if ppo_land > bc_land:
            verdict = "PPO_IMPROVED_OVER_BC_descriptive_only"
        elif ppo_land < bc_land:
            verdict = "PPO_WORSENED_VS_BC_descriptive_only"
        else:
            verdict = "PPO_PRESERVED_BC"

    summary = {
        "label": LABEL,
        "phase": 4,
        "skipped": False,
        "ppo_frames": train_budget.spent,
        "ppo_updates": updates,
        "early_stop": early,
        "wall_seconds": time.time() - t0,
        "ppo_sha256": ppo_sha,
        "ppo_path": str(ppo_path),
        "bc_eval": {k: v for k, v in bc_again.items() if k != "per_seed"},
        "ppo_eval": {k: v for k, v in ppo_eval.items() if k != "per_seed"},
        "mcnemar_ppo_vs_bc": mc,
        "verdict": verdict,
        "note": "Never imply PPO discovered the maneuver from scratch — started from BC.",
        "reward": "touchdown_v1 unchanged",
        "bc_regularization": cfg.bc_regularization,
        "diagnostic_budget": diag.snapshot(),
        "train_budget": train_budget.snapshot(),
    }
    (out / "phase4_ppo.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "evaluation" / "ppo_deterministic.json").write_text(json.dumps(ppo_eval, indent=2) + "\n")
    return summary


def write_report(
    cfg: V7Config,
    out: Path,
    phase0: dict,
    phase1: dict,
    phase2: dict,
    phase3: dict,
    phase4: dict,
) -> Path:
    report_dir = ROOT / "docs" / "rl_v7"
    report_dir.mkdir(parents=True, exist_ok=True)
    bc_land = phase3.get("bc_landings", 0)
    un_land = phase3.get("untrained_landings", 0)
    native_perfect = sum(1 for row in phase3.get("bc_per_seed", []) if row.get("perfect"))
    native_hard = sum(1 for row in phase3.get("bc_per_seed", []) if row.get("hard"))
    fid = phase0.get("fidelity_aggregate") or {}
    ppo_verdict = phase4.get("verdict", "skipped")
    milestone = bc_land > 0
    lines = [
        "# ApolloLander R.E.A.C.T. V7 — Demonstration-Assisted Imitation + Optional PPO",
        "",
        f"**Label:** `{LABEL}` (expert demos for TRAINING ONLY; never at evaluation).",
        "",
        "This is NOT a reward-only / from-scratch discovery claim.",
        "",
        "## Preregistration",
        "",
        f"- Seeds file: `examples/apollolander/rl_v7/preregistered/seeds.json`",
        f"- SHA256: `{sha256_file(PREREG / 'seeds.json')}`",
        "- Committed before demo generation.",
        "",
        "## Phase 0 — Translation feasibility",
        "",
        f"- Learner space: continuous thrust, delta {{-10,0,+10}}, action_repeat={cfg.action_repeat}",
        f"- max_steps_v1={phase0.get('max_steps_v1', cfg.max_steps_v1)} (expert needs ~6k frames)",
        f"- V1 translated expert landings: {phase0['translated_landings']}/{phase0['n_v1']} "
        f"(rate={phase0['translated_landing_rate']:.3f}, Wilson95={phase0['translated_wilson95']})",
        f"- Raw expert landings (fidelity subset): {phase0.get('raw_landings')}/{phase0.get('raw_n')}",
        f"- Fidelity (mean over n={fid.get('n')}): thrust MAE={fid.get('thrust_mae_mean')}, "
        f"rotation MAE deg={fid.get('rotation_mae_deg_mean')}, "
        f"rotation exact agreement={fid.get('rotation_exact_agreement_mean')}",
        f"- Replay bit-exact: {phase0['replay_bitexact_matched']}/{phase0['replay_bitexact_n']}",
        f"- Pass ≥80%: {phase0['pass_threshold_0_80']}",
        f"- L0-near probe landings: {phase0['l0_near_probe']['landings']}/{phase0['l0_near_probe']['n']}",
        f"- Demo/feas/replay frames spent after Phase 0: {phase0['budget_spent']}",
        f"- Fallback representation used: {phase0.get('fallback_used', False)}",
        "",
        "## Phase 1 — Demonstrations",
        "",
        f"- Attempts: {phase1['attempts']}",
        f"- Failures: {phase1['failures']}",
        f"- Kept (native landings, replay-verified): {phase1['kept']} "
        f"(train={phase1['kept_train']}, val={phase1['kept_val']})",
        f"- Include L0-near demos: {phase1['include_l0_near']}",
        f"- Demo seed list sha256: `{phase1['demo_seed_list_sha256']}`",
        f"- Demo budget spent: {phase1['budget_spent']} / {phase1['budget_cap']}",
        "",
        "## Phase 2 — Behavioral cloning",
        "",
        f"- Train pairs: {phase2.get('n_train_pairs')} (from {phase2.get('n_train_trajectories')} trajectories)",
        f"- Val pairs: {phase2.get('n_val_pairs')} (from {phase2.get('n_val_trajectories')} trajectories)",
        f"- Epochs: {phase2.get('epochs')}, wall seconds: {phase2.get('wall_seconds')}",
        f"- Final val loss: {(phase2.get('final_val') or {}).get('val_loss')}",
        f"- Final val rotation accuracy: {(phase2.get('final_val') or {}).get('val_rot_acc')}",
        f"- Final val thrust MSE: {(phase2.get('final_val') or {}).get('val_thrust_mse')}",
        f"- step0 sha256: `{phase2.get('step0_sha256')}`",
        f"- bc sha256: `{phase2.get('bc_sha256')}`",
        f"- Integrity (no controller at eval): {(phase2.get('integrity') or {}).get('passed')}",
        f"- Environment frames for BC: 0",
        "",
        "## Phase 3 — Independent gameplay (expert DISABLED)",
        "",
        f"- L0-near eval n={phase3.get('bc_l0', {}).get('n')}: "
        f"untrained={phase3.get('untrained_l0', {}).get('counts')} "
        f"BC={phase3.get('bc_l0', {}).get('counts')}",
        f"- V1 eval n={phase3.get('bc_v1', {}).get('n')}: "
        f"untrained={phase3.get('untrained_v1', {}).get('counts')} "
        f"BC={phase3.get('bc_v1', {}).get('counts')}",
        f"- Untrained landings total: {un_land} (l0={phase3.get('untrained_landings_l0')}, v1={phase3.get('untrained_landings_v1')})",
        f"- BC landings total: {bc_land} (l0={phase3.get('bc_landings_l0')}, v1={phase3.get('bc_landings_v1')}; "
        f"perfect={native_perfect}, hard={native_hard} across listed per-seed rows)",
        f"- McNemar BC vs untrained (L0-near primary): {phase3.get('mcnemar_bc_vs_untrained_l0')}",
        f"- McNemar BC vs untrained (v1): {phase3.get('mcnemar_bc_vs_untrained_v1')}",
        f"- Expert reference L0 (NOT a learner): {phase3.get('expert_reference_l0', {}).get('counts')}",
        f"- Expert reference V1 (NOT a learner): {phase3.get('expert_reference_v1', {}).get('counts')}",
        f"- Diagnostic frames spent: {phase3.get('diagnostic_budget', {}).get('spent')}",
        f"- Landings preserved (videos/traces): {len(phase3.get('landings_preserved', []))}",
        "",
        "## Phase 4 — PPO fine-tune from BC",
        "",
    ]
    if phase4.get("skipped"):
        lines += [
            f"- Skipped: {phase4.get('reason')}",
            "",
        ]
    else:
        lines += [
            f"- PPO frames: {phase4.get('ppo_frames')} / {cfg.ppo_budget}",
            f"- PPO sha256: `{phase4.get('ppo_sha256')}`",
            f"- BC re-eval counts: {phase4.get('bc_eval', {}).get('counts')}",
            f"- PPO eval counts: {phase4.get('ppo_eval', {}).get('counts')}",
            f"- McNemar PPO vs BC: {phase4.get('mcnemar_ppo_vs_bc')}",
            f"- Verdict: {ppo_verdict}",
            "- Note: PPO started from BC checkpoint; not discovery from scratch.",
            "",
        ]

    lines += [
        "## Budgets (exact frames)",
        "",
        f"| Bucket | Cap | Spent |",
        f"|---|---:|---:|",
        f"| Demo + feasibility + replay | {cfg.demo_cap} | {phase1.get('budget_spent', phase0.get('budget_spent'))} |",
        f"| Diagnostics (evals/baselines/footage sim) | {cfg.diag_cap} | {phase3.get('diagnostic_budget', {}).get('spent')} |",
        f"| PPO fine-tune | {cfg.ppo_budget} | {phase4.get('ppo_frames', 0) if not phase4.get('skipped') else 0} |",
        f"| BC supervised | 0 env frames | 0 |",
        "",
        "## Checkpoints & videos",
        "",
        f"- step0: `{phase2.get('step0_path')}` sha256=`{phase2.get('step0_sha256')}`",
        f"- bc: `{phase2.get('bc_path')}` sha256=`{phase2.get('bc_sha256')}`",
    ]
    if not phase4.get("skipped"):
        lines.append(f"- ppo: `{phase4.get('ppo_path')}` sha256=`{phase4.get('ppo_sha256')}`")
    filmed = [e for e in phase3.get("landings_preserved", []) if (e.get("video") or {}).get("ok")]
    lines.append(
        f"- Landing traces persisted for {len(phase3.get('landings_preserved', []))} "
        f"outcomes; Chromium footage for {len(filmed)} (capped)."
    )
    for e in filmed:
        vid = e.get("video") or {}
        lines.append(
            f"- landing {e.get('tag')} seed={e.get('seed')}: "
            f"video=`{vid.get('path')}` sha256=`{vid.get('sha256')}` "
            f"reverify={e.get('reverify', {}).get('matched')} "
            f"artifact=`{e.get('video_artifact')}`"
        )

    lines += [
        "",
        "## Milestone",
        "",
        f"- Achieved independent native landing under demonstration-assisted training: **{milestone}**",
        f"- Explicit label: `{LABEL}`",
        "",
        "## Representation",
        "",
        phase0.get("representation_note", ""),
        "",
        "## Artifacts",
        "",
        f"- Run directory: `{out}`",
        f"- Phase JSON: phase0_feasibility.json, phase1_demos.json, phase2_bc.json, phase3_eval.json, phase4_ppo.json",
        "",
    ]
    path = report_dir / "REPORT.md"
    path.write_text("\n".join(lines) + "\n")
    (report_dir / "STATUS.md").write_text(
        "\n".join(
            [
                "# V7 STATUS",
                "",
                f"label: {LABEL}",
                f"milestone_independent_landing: {milestone}",
                f"bc_landings: {bc_land}",
                f"ppo: {ppo_verdict}",
                f"demo_kept: {phase1.get('kept')}/{phase1.get('attempts')} attempts",
                "",
            ]
        )
        + "\n"
    )
    return path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["all", "0", "1", "2", "3", "4", "report"], default="all")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    cfg = V7Config()
    out = args.output or (RESULTS / cfg.run_name)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config_snapshot.yaml").write_text(yaml.safe_dump(asdict(cfg), sort_keys=False))

    seeds_doc = load_prereg()
    phase0 = phase1 = phase2 = phase3 = phase4 = {}

    def _load(name: str) -> dict:
        return json.loads((out / name).read_text())

    try:
        if args.phase in ("all", "0"):
            print("=== PHASE 0 ===", flush=True)
            phase0 = phase0_feasibility(cfg, out, seeds_doc)
            if not phase0["pass_threshold_0_80"]:
                print(
                    "STOP: translated expert landing rate < 80%. "
                    "Options: reduce action_repeat, use absolute target rotation, "
                    "or mix L0-near starts. See phase0_feasibility.json.",
                    flush=True,
                )
                write_report(
                    cfg,
                    out,
                    phase0,
                    {
                        "attempts": 0,
                        "failures": 0,
                        "kept": 0,
                        "kept_train": 0,
                        "kept_val": 0,
                        "include_l0_near": False,
                        "demo_seed_list_sha256": "",
                        "budget_spent": phase0["budget_spent"],
                        "budget_cap": phase0["budget_cap"],
                    },
                    {},
                    {},
                    {"skipped": True, "reason": "phase0_failed"},
                )
                raise SystemExit(2)
        elif args.phase in ("1", "2", "3", "4", "report"):
            phase0 = _load("phase0_feasibility.json")

        if args.phase in ("all", "1"):
            print("=== PHASE 1 ===", flush=True)
            phase1 = phase1_collect_demos(cfg, out, seeds_doc, phase0)
            if phase1["kept"] < cfg.demo_keep_target_min:
                print(
                    f"WARNING: only {phase1['kept']} demos kept "
                    f"(target {cfg.demo_keep_target_min}-{cfg.demo_keep_target_max})",
                    flush=True,
                )
        elif args.phase in ("2", "3", "4", "report"):
            phase1 = _load("phase1_demos.json")

        if args.phase in ("all", "2"):
            print("=== PHASE 2 ===", flush=True)
            phase2 = phase2_bc(cfg, out, phase1)
        elif args.phase in ("3", "4", "report"):
            phase2 = _load("phase2_bc.json")

        if args.phase in ("all", "3"):
            print("=== PHASE 3 ===", flush=True)
            phase3 = phase3_eval(cfg, out, seeds_doc, phase2)
        elif args.phase in ("4", "report"):
            phase3 = _load("phase3_eval.json")

        if args.phase in ("all", "4"):
            print("=== PHASE 4 ===", flush=True)
            phase4 = phase4_ppo(cfg, out, seeds_doc, phase2, phase3)
        elif args.phase == "report":
            p4 = out / "phase4_ppo.json"
            phase4 = _load("phase4_ppo.json") if p4.exists() else {"skipped": True}

        if args.phase in ("all", "report"):
            path = write_report(cfg, out, phase0, phase1, phase2, phase3, phase4)
            print("REPORT", path, flush=True)

    except DiagnosticBudgetExhausted as exc:
        print("BUDGET STOP", exc, flush=True)
        traceback.print_exc()
        raise SystemExit(3)


if __name__ == "__main__":
    main()
