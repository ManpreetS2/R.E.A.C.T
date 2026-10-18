#!/usr/bin/env python3
"""V6 genuine landing learning test — L0-near, ar=8, matched step-0, no priors.

Caps enforced BEFORE stepping (TrainingBudget / DiagnosticBudget.require).
Preregistered eval plan + seeds must exist and be hashed before evals run.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml
from scipy import stats as scipy_stats

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.rl.continuous_policy import (  # noqa: E402
    ROTATION_DELTAS,
    ContinuousThrustActorCritic,
)
from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed  # noqa: E402
from rewardbench.rl.train_integrity import preserve_resume_artifacts  # noqa: E402
from rewardbench.rl.training_budget import TrainingBudget, TrainingBudgetExhausted  # noqa: E402
from rewardbench.rl.upstream_env import (  # noqa: E402
    ApolloLanderUpstreamEnv,
    VectorApolloLanderUpstreamEnv,
)

HERE = Path(__file__).resolve().parent
PREREG = HERE / "preregistered"
RESULTS = HERE / "results"
LEVEL = "apollolander.starts.l0_near_v6"
TRAIN_CAP = 250_000
DIAG_CAP = 100_000
V5_SUCCESS_SEED = 548_003


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def mcnemar_exact(b: int, c: int) -> dict[str, Any]:
    """Exact McNemar two-sided p-value on discordant pairs (b, c)."""
    n = b + c
    if n == 0:
        return {"b": b, "c": c, "n_discordant": 0, "p_value": 1.0, "method": "exact_none"}
    # H0: P(b)=P(c)=0.5; two-sided exact binomial on b given n.
    res = scipy_stats.binomtest(b, n, 0.5, alternative="two-sided")
    return {
        "b": int(b),
        "c": int(c),
        "n_discordant": int(n),
        "p_value": float(res.pvalue),
        "method": "exact_binomial_mcnemar",
        "interpretation": "b=step0_fail_ckpt_land, c=step0_land_ckpt_fail",
    }


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@dataclass
class V6Config:
    total_budget: int = TRAIN_CAP
    diagnostic_hard_cap: int = DIAG_CAP
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
    hidden: int = 128
    seed: int = 31
    action_repeat: int = 8
    max_steps: int = 400
    rotation_mode: str = "delta"
    soft_thrust_prior: bool = False
    hold_attitude_prior: bool = False
    init_scheme: str = "orthogonal_zero_bias"
    level: str = LEVEL
    checkpoint_every_frames: int = 50_000
    device: str = "cpu"
    run_name: str = "V6_L0near_s31"


def load_preregistered() -> tuple[dict, dict]:
    plan = json.loads((PREREG / "eval_plan.json").read_text())
    seeds = json.loads((PREREG / "val_seeds.json").read_text())
    plan_hash = (PREREG / "eval_plan.sha256").read_text().strip()
    seeds_hash = (PREREG / "val_seeds.sha256").read_text().strip()
    assert sha256_file(PREREG / "eval_plan.json") == plan_hash
    assert sha256_file(PREREG / "val_seeds.json") == seeds_hash
    assert plan["fits_cap"]
    assert V5_SUCCESS_SEED not in seeds["val_seeds"]
    assert_seeds_allowed(seeds["val_seeds"], context="v6.val")
    assert_seeds_allowed(
        range(seeds["train_seed_start"], seeds["train_seed_start"] + seeds["train_seed_count"]),
        context="v6.train",
    )
    return plan, seeds


def integrity_check(cfg: V6Config) -> dict[str, Any]:
    checks = []
    ok = True

    def add(name: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            ok = False

    add("soft_thrust_prior_false", cfg.soft_thrust_prior is False)
    add("hold_attitude_prior_false", cfg.hold_attitude_prior is False)
    add("init_orthogonal_zero_bias", cfg.init_scheme == "orthogonal_zero_bias")
    add("rotation_delta", cfg.rotation_mode == "delta")
    add("action_repeat_8", cfg.action_repeat == 8)
    add("max_steps_400", cfg.max_steps == 400)
    add("level_l0_near_v6", cfg.level == LEVEL)
    add("train_cap", cfg.total_budget <= TRAIN_CAP)
    add("diag_cap", cfg.diagnostic_hard_cap <= DIAG_CAP)
    add("diag_cap_not_raised", cfg.diagnostic_hard_cap == DIAG_CAP)
    return {"passed": ok, "checks": checks, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


class V6Trainer:
    def __init__(self, cfg: V6Config, output_dir: Path) -> None:
        self.cfg = cfg
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("checkpoints", "logs", "evidence", "milestone", "evaluation"):
            (self.output_dir / sub).mkdir(exist_ok=True)

        self.plan, self.prereg_seeds = load_preregistered()
        self.val_seeds = list(self.prereg_seeds["val_seeds"])
        self.intermediate_seeds = list(self.prereg_seeds["intermediate_subset_seeds"])
        self.train_budget = TrainingBudget(hard_cap=int(cfg.total_budget))
        self.diag_budget = DiagnosticBudget(hard_cap=int(cfg.diagnostic_hard_cap))

        integ = integrity_check(cfg)
        (self.output_dir / "logs" / "integrity_check.json").write_text(
            json.dumps(integ, indent=2) + "\n"
        )
        if not integ["passed"]:
            raise SystemExit(f"INTEGRITY CHECK FAILED: {json.dumps(integ, indent=2)}")

        self.device = torch.device(cfg.device)
        torch.manual_seed(cfg.seed)
        np.random.seed(cfg.seed)
        torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "2"))))

        self.env_config = EnvConfig(
            max_steps=cfg.max_steps,
            research_mode=True,
            start_schedule_version=cfg.level,
            vary_fuel=False,
            action_repeat=cfg.action_repeat,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        )
        self.env = VectorApolloLanderUpstreamEnv(
            cfg.n_envs, self.env_config, reward_mode="touchdown_v1"
        )
        self.policy = ContinuousThrustActorCritic(
            hidden=cfg.hidden,
            rotation_mode=cfg.rotation_mode,
            soft_thrust_prior=False,
            hold_attitude_prior=False,
        ).to(self.device)
        self.policy.reset_parameters_clean()
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=cfg.learning_rate, eps=1e-5)

        self.global_step = 0
        self.global_decisions = 0
        self.update_idx = 0
        self._rng = np.random.default_rng(cfg.seed + 17)
        self._cmd_rotation = np.zeros(cfg.n_envs, dtype=np.int64)
        self._train_seeds = np.arange(
            self.prereg_seeds["train_seed_start"],
            self.prereg_seeds["train_seed_start"] + self.prereg_seeds["train_seed_count"],
            dtype=np.int64,
        )
        self._episode_returns = np.zeros(cfg.n_envs, dtype=np.float64)
        self._metrics: list[dict[str, Any]] = []
        self._action_traces: dict[int, list] = {i: [] for i in range(cfg.n_envs)}
        self._first_landing_frames: dict[str, int | None] = {cfg.level: None}
        self._started = time.time()
        self._resume_preserved: dict[str, Any] = {}
        self._step0_path: Path | None = None
        self._step0_sha: str | None = None
        self._step0_policy_sd: dict | None = None
        self._eval_log: list[dict[str, Any]] = []
        self._milestone: dict[str, Any] | None = None

        meta = {
            "run_name": cfg.run_name,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cfg": asdict(cfg),
            "prereg_plan_sha256": (PREREG / "eval_plan.sha256").read_text().strip(),
            "prereg_seeds_sha256": (PREREG / "val_seeds.sha256").read_text().strip(),
            "prereg_commit_note": "eval_plan + seeds committed before this run",
            "v5_success_seed_excluded": V5_SUCCESS_SEED,
            "claim_note": "Do not claim learning from V5 1/12 result",
        }
        (self.output_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
        (self.output_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(asdict(cfg), sort_keys=False)
        )

    def save_checkpoint(self, tag: str) -> Path:
        path = self.output_dir / "checkpoints" / f"{tag}.pt"
        payload = {
            "policy": self.policy.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "global_step": self.global_step,
            "global_decisions": self.global_decisions,
            "update_idx": self.update_idx,
            "level": self.cfg.level,
            "cfg": asdict(self.cfg),
            "rng_state": self._rng.bit_generator.state,
            "init_scheme": self.cfg.init_scheme,
            "step0_sha256": self._step0_sha,
        }
        torch.save(payload, path)
        digest = sha256_file(path)
        meta = {
            "tag": tag,
            "path": str(path),
            "sha256": digest,
            "global_step": self.global_step,
            "train_budget_spent": self.train_budget.spent,
        }
        (self.output_dir / "checkpoints" / f"{tag}.sha256.json").write_text(
            json.dumps(meta, indent=2) + "\n"
        )
        with (self.output_dir / "logs" / "checkpoint_log.jsonl").open("a") as f:
            f.write(json.dumps(meta) + "\n")
        return path

    def load_checkpoint(self, path: Path) -> None:
        data = torch.load(path, map_location=self.device, weights_only=False)
        self.policy.load_state_dict(data["policy"])
        self.optimizer.load_state_dict(data["optimizer"])
        self.global_step = int(data["global_step"])
        self.global_decisions = int(data.get("global_decisions", 0))
        self.update_idx = int(data.get("update_idx", 0))
        if "rng_state" in data:
            self._rng.bit_generator.state = data["rng_state"]
        self.train_budget.spent = self.global_step
        self.env.close()
        self.env = VectorApolloLanderUpstreamEnv(
            self.cfg.n_envs, self.env_config, reward_mode="touchdown_v1"
        )
        preserved = preserve_resume_artifacts(self.output_dir, levels=[self.cfg.level])
        self._first_landing_frames = preserved["first_landing_frames"]
        self._resume_preserved = preserved

    def _sample_train_seeds(self, n: int) -> np.ndarray:
        idx = self._rng.integers(0, len(self._train_seeds), size=n)
        return self._train_seeds[idx]

    def _commands_from_actions(
        self, thrust: torch.Tensor, rot_idx: torch.Tensor
    ) -> list[dict[str, float | int]]:
        thrusts = thrust.detach().cpu().numpy()
        idx = rot_idx.detach().cpu().numpy().astype(np.int64)
        commands: list[dict[str, float | int]] = []
        for i in range(len(thrusts)):
            delta = int(ROTATION_DELTAS[int(idx[i])])
            abs_rot = int(np.clip(self._cmd_rotation[i] + delta, -90, 90))
            abs_rot = int(round(abs_rot / 10.0) * 10)
            self._cmd_rotation[i] = abs_rot
            commands.append({"thrust": float(thrusts[i]), "rotation": abs_rot})
        return commands

    def evaluate_seeds(
        self,
        *,
        seeds: list[int],
        deterministic: bool,
        reason: str,
        policy: ContinuousThrustActorCritic | None = None,
        record_traces: bool = False,
    ) -> dict[str, Any]:
        pol = policy if policy is not None else self.policy
        # Pre-step guard: worst-case full horizon for every remaining episode.
        self.diag_budget.require(len(seeds) * self.cfg.max_steps, reason=f"pre:{reason}")

        env = ApolloLanderUpstreamEnv(self.env_config, reward_mode="touchdown_v1")
        per_seed: list[dict[str, Any]] = []
        counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
        pad_contacts = 0
        orient_errors: list[float] = []
        frames_total = 0
        pol.eval()
        try:
            for seed in seeds:
                assert_seed_allowed(seed, context="v6.eval")
                # Per-episode pre-step guard
                self.diag_budget.require(self.cfg.max_steps, reason=f"pre_ep:{reason}:{seed}")
                obs, info0 = env.reset(seed)
                cmd_rot = int(round(float(info0["start"]["rotation"]) / 10.0) * 10)
                done = False
                ep_ret = 0.0
                trace: list[dict[str, float | int]] = []
                info: dict[str, Any] = {}
                while not done:
                    with torch.no_grad():
                        t = torch.as_tensor(obs[None], dtype=torch.float32, device=self.device)
                        if deterministic:
                            thrust, rot_idx, _ = pol.act_deterministic(t)
                        else:
                            thrust, rot_idx, _, _, _ = pol.act(t)
                        delta = int(ROTATION_DELTAS[int(rot_idx.item())])
                        cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                        cmd_rot = int(round(cmd_rot / 10.0) * 10)
                        command = {"thrust": float(thrust.item()), "rotation": cmd_rot}
                    if record_traces:
                        trace.append(dict(command))
                    obs, reward, terminated, truncated, info = env.step_command(command)
                    ep_ret += reward
                    done = terminated or truncated

                ep_frames = int(info.get("steps", 0))
                self.diag_budget.charge(ep_frames, reason=f"{reason}:seed{seed}")
                frames_total += ep_frames
                status = info.get("status", "")
                native = info.get("native_outcome") or {}
                rot = float(native.get("rotation", info.get("terminal_rotation", 0.0)))
                vy = float(native.get("vy", info.get("terminal_vy", 0.0)))
                within = bool(native.get("within_pad", False))
                landable = bool(native.get("landable_contact", False))
                landed = status in ("landed", "hard_landing")
                if landed or (landable and within):
                    pad_contacts += 1
                if status == "landed":
                    counts["perfect"] += 1
                elif status == "hard_landing":
                    counts["hard"] += 1
                elif status == "crashed":
                    counts["crash"] += 1
                elif status == "timeout":
                    counts["timeout"] += 1
                if landable and within:
                    orient_errors.append(abs(rot))
                row = {
                    "seed": seed,
                    "status": status,
                    "landed": landed,
                    "rotation": rot,
                    "vy": vy,
                    "vx": float(native.get("vx", 0.0)),
                    "within_pad": within,
                    "landable_contact": landable,
                    "pad_aligned": bool(landable and within),
                    "return": float(ep_ret),
                    "steps": ep_frames,
                    "native_outcome": native,
                    "native_score": float(info.get("native_score", 0.0) or 0.0),
                    "fuel": float(native.get("fuel", info.get("fuel_used", 0.0))),
                }
                if record_traces:
                    row["action_trace"] = trace
                per_seed.append(row)
        finally:
            env.close()

        land = counts["perfect"] + counts["hard"]
        n = len(seeds)
        p, lo, hi = wilson_ci(land, n)
        return {
            "reason": reason,
            "deterministic": deterministic,
            "n": n,
            "seeds": seeds,
            "counts": counts,
            "landing_rate": p,
            "landing_wilson95": [lo, hi],
            "pad_contact_rate": pad_contacts / n if n else 0.0,
            "pad_contacts": pad_contacts,
            "orientation_error_abs_rotation_at_pad_contact": {
                "n": len(orient_errors),
                "mean": float(np.mean(orient_errors)) if orient_errors else None,
                "median": float(np.median(orient_errors)) if orient_errors else None,
                "values": orient_errors,
            },
            "diagnostic_frames": frames_total,
            "diagnostic_budget_spent": self.diag_budget.spent,
            "global_step_at_eval": self.global_step,
            "per_seed": per_seed,
        }

    def policy_divergence_vs_step0(self) -> dict[str, Any]:
        assert self._step0_policy_sd is not None
        other = ContinuousThrustActorCritic(
            hidden=self.cfg.hidden,
            rotation_mode=self.cfg.rotation_mode,
            soft_thrust_prior=False,
            hold_attitude_prior=False,
        ).to(self.device)
        other.load_state_dict(self._step0_policy_sd)
        other.eval()
        self.policy.eval()
        g = torch.Generator()
        g.manual_seed(999)
        obs = torch.randn(256, 10, generator=g)
        with torch.no_grad():
            t1, r1, v1 = self.policy.forward(obs)
            t2, r2, v2 = other.forward(obs)
            # KL for Gaussians + categorical
            # thrust: Normal
            kl_thrust = torch.distributions.kl_divergence(t1, t2).mean().item()
            p1 = r1.probs
            p2 = r2.probs.clamp(min=1e-8)
            kl_rot = (p1 * (p1.clamp(min=1e-8).log() - p2.log())).sum(-1).mean().item()
            th1, ri1, _ = self.policy.act_deterministic(obs)
            th2, ri2, _ = other.act_deterministic(obs)
            agree = (ri1 == ri2).float().mean().item()
            mean_thrust = float(th1.mean().item())
            mean_thrust0 = float(th2.mean().item())
        return {
            "kl_thrust_mean": kl_thrust,
            "kl_rotation_mean": kl_rot,
            "det_rotation_agreement": agree,
            "mean_det_thrust": mean_thrust,
            "mean_det_thrust_step0": mean_thrust0,
            "mean_abs_value_diff": float((v1 - v2).abs().mean().item()),
        }

    def compare_to_step0(self, result: dict[str, Any], step0: dict[str, Any]) -> dict[str, Any]:
        # Paired McNemar on same seed order
        s0 = {r["seed"]: r["landed"] for r in step0["per_seed"]}
        b = c = 0
        for r in result["per_seed"]:
            a = bool(s0[r["seed"]])
            z = bool(r["landed"])
            if (not a) and z:
                b += 1
            elif a and (not z):
                c += 1
        mc = mcnemar_exact(b, c)
        land = result["counts"]["perfect"] + result["counts"]["hard"]
        land0 = step0["counts"]["perfect"] + step0["counts"]["hard"]
        return {
            "mcnemar": mc,
            "step0_landings": land0,
            "ckpt_landings": land,
            "delta_landings": land - land0,
            "beats_step0_mcnemar_p_lt_0.01": bool(mc["p_value"] < 0.01 and b > c),
            "wilson_ckpt": result["landing_wilson95"],
            "wilson_step0": step0["landing_wilson95"],
            "wilson_nonoverlap_ckpt_above_step0": result["landing_wilson95"][0]
            > step0["landing_wilson95"][1],
        }

    def _flush_metrics(self) -> None:
        path = self.output_dir / "logs" / "learning_curve.csv"
        if not self._metrics:
            return
        keys = list(self._metrics[0].keys())
        write_header = not path.exists()
        with path.open("a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            if write_header:
                w.writeheader()
            w.writerows(self._metrics)
        self._metrics.clear()

    def collect_and_update(self, obs: np.ndarray) -> np.ndarray:
        cfg = self.cfg
        n_steps, n_envs = cfg.rollout_steps, cfg.n_envs
        frames_per_env_step = n_envs * cfg.action_repeat
        # Pre-check entire rollout affordability
        self.train_budget.require(
            n_steps * frames_per_env_step, reason="pre_rollout"
        )

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
        self.policy.train()
        for t in range(n_steps):
            self.train_budget.require(frames_per_env_step, reason=f"pre_env_step_u{self.update_idx}_t{t}")
            with torch.no_grad():
                obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
                thrust, rot_idx, raw, log_prob, values = self.policy.act(obs_t)
                commands = self._commands_from_actions(thrust, rot_idx)
            for i, cmd in enumerate(commands):
                self._action_traces[i].append(dict(cmd))

            next_obs, rewards, terminated, truncated, infos = self.env.step_commands(commands)
            # Charge actual frames: each env applies action_repeat unless episode ended earlier.
            # Conservative: charge full frames_per_env_step (matches host action_repeat loop).
            self.train_budget.charge(frames_per_env_step, reason=f"rollout_u{self.update_idx}_t{t}")
            self.global_step = self.train_budget.spent
            self.global_decisions += n_envs

            bootstrap_values = np.zeros(n_envs, dtype=np.float64)
            if np.any(truncated):
                with torch.no_grad():
                    trunc_vals = (
                        self.policy.forward(
                            torch.as_tensor(next_obs, dtype=torch.float32, device=self.device)
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
            self._episode_returns += rewards
            for i, info in enumerate(infos):
                if dones[i]:
                    status = info.get("status", "")
                    landed = status in ("landed", "hard_landing")
                    native = info.get("native_outcome") or {}
                    row = {
                        "global_step": self.global_step,
                        "level": self.cfg.level,
                        "return": float(self._episode_returns[i]),
                        "status": status,
                        "landed": landed,
                        "perfect": status == "landed",
                        "hard": status == "hard_landing",
                        "crashed": status == "crashed",
                        "timed_out": status == "timeout",
                        "rotation": float(native.get("rotation", info.get("terminal_rotation", 0.0))),
                        "vy": float(native.get("vy", info.get("terminal_vy", 0.0))),
                        "fuel_used": float(info.get("fuel_used", 0)),
                        "steps": int(info.get("steps", 0)),
                        "native_score": float(info.get("native_score", 0.0) or 0.0),
                    }
                    self._metrics.append(row)
                    with (self.output_dir / "logs" / "train_episodes.jsonl").open("a") as f:
                        f.write(json.dumps(row) + "\n")

                    if landed:
                        if self._first_landing_frames[self.cfg.level] is None:
                            self._first_landing_frames[self.cfg.level] = self.global_step
                        evidence = {
                            "event": "train_landing",
                            "frames": self.global_step,
                            "status": status,
                            "native_outcome": native,
                            "native_score": row["native_score"],
                            "rotation": row["rotation"],
                            "vy": row["vy"],
                            "action_trace": list(self._action_traces[i]),
                            "return": row["return"],
                            "steps": row["steps"],
                        }
                        with (self.output_dir / "logs" / "train_landings.jsonl").open("a") as f:
                            f.write(json.dumps(evidence) + "\n")
                        tag = f"train_land_{self.global_step}"
                        ckpt = self.save_checkpoint(tag)
                        if self._milestone is None:
                            self._milestone = {
                                "label": "FIRST_LANDING_MILESTONE",
                                "note": (
                                    "Chronological first stochastic training landing. "
                                    "Separate from statistical improvement over step-0."
                                ),
                                "frames": self.global_step,
                                "status": status,
                                "checkpoint": str(ckpt),
                                "sha256": sha256_file(ckpt),
                                "native_outcome": native,
                                "native_score": row["native_score"],
                                "rotation": row["rotation"],
                                "vy": row["vy"],
                                "action_trace_len": len(self._action_traces[i]),
                                "action_trace_path": str(
                                    self.output_dir / "milestone" / "first_landing_trace.json"
                                ),
                            }
                            (self.output_dir / "milestone" / "first_landing_trace.json").write_text(
                                json.dumps(
                                    {
                                        "trace": self._action_traces[i],
                                        "evidence": evidence,
                                        "checkpoint_sha256": self._milestone["sha256"],
                                    },
                                    indent=2,
                                )
                                + "\n"
                            )
                            (self.output_dir / "milestone" / "FIRST_LANDING_MILESTONE.json").write_text(
                                json.dumps(self._milestone, indent=2) + "\n"
                            )
                    self._action_traces[i] = []
                    self._episode_returns[i] = 0.0

            if np.any(dones):
                seeds = self._sample_train_seeds(int(np.sum(dones)))
                seed_iter = iter(seeds.tolist())
                for i, done in enumerate(dones):
                    if done:
                        o, info = self.env.envs[i].reset(int(next(seed_iter)))
                        next_obs[i] = o
                        self._cmd_rotation[i] = int(
                            round(float(info["start"]["rotation"]) / 10.0) * 10
                        )
                        self._action_traces[i] = []
            obs = next_obs

        # PPO update
        with torch.no_grad():
            last_values = (
                self.policy.forward(
                    torch.as_tensor(obs, dtype=torch.float32, device=self.device)
                )[2]
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

        obs_b = torch.as_tensor(buf["obs"].reshape(-1, 10), dtype=torch.float32, device=self.device)
        raw_b = torch.as_tensor(buf["raw_thrust"].reshape(-1), dtype=torch.float32, device=self.device)
        rot_b = torch.as_tensor(buf["rot_idx"].reshape(-1), dtype=torch.int64, device=self.device)
        old_lp = torch.as_tensor(buf["log_probs"].reshape(-1), dtype=torch.float32, device=self.device)
        adv_b = torch.as_tensor(advantages.reshape(-1), dtype=torch.float32, device=self.device)
        ret_b = torch.as_tensor(returns.reshape(-1), dtype=torch.float32, device=self.device)
        adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)

        batch = obs_b.shape[0]
        self.policy.train()
        for _ in range(cfg.update_epochs):
            perm = torch.randperm(batch, device=self.device)
            for start in range(0, batch, cfg.minibatch_size):
                mb = perm[start : start + cfg.minibatch_size]
                log_prob, entropy, values = self.policy.evaluate_actions(
                    obs_b[mb], raw_b[mb], rot_b[mb]
                )
                ratio = (log_prob - old_lp[mb]).exp()
                surr1 = ratio * adv_b[mb]
                surr2 = torch.clamp(ratio, 1 - cfg.clip_coef, 1 + cfg.clip_coef) * adv_b[mb]
                pg_loss = -torch.min(surr1, surr2).mean()
                v_loss = 0.5 * (values - ret_b[mb]).pow(2).mean()
                loss = pg_loss - cfg.ent_coef * entropy.mean() + cfg.vf_coef * v_loss
                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.optimizer.step()
        self.update_idx += 1
        self._flush_metrics()
        return obs

    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        # --- STEP 1: step-0 ---
        self._step0_path = self.save_checkpoint("step0")
        self._step0_sha = sha256_file(self._step0_path)
        self._step0_policy_sd = {
            k: v.detach().cpu().clone() for k, v in self.policy.state_dict().items()
        }
        # Equivalence
        reloaded = ContinuousThrustActorCritic(
            hidden=cfg.hidden, rotation_mode=cfg.rotation_mode
        ).to(self.device)
        ck = torch.load(self._step0_path, map_location=self.device, weights_only=False)
        reloaded.load_state_dict(ck["policy"])
        g = torch.Generator()
        g.manual_seed(12345)
        obs = torch.randn(64, 10, generator=g)
        with torch.no_grad():
            a = self.policy.forward(obs)
            b = reloaded.forward(obs)
            max_abs = max(
                (a[0].mean - b[0].mean).abs().max().item(),
                (a[1].logits - b[1].logits).abs().max().item(),
                (a[2] - b[2]).abs().max().item(),
            )
        equiv = {
            "step0_sha256": self._step0_sha,
            "max_abs_diff": max_abs,
            "bit_exact": max_abs == 0.0,
            "passed": max_abs == 0.0,
        }
        (self.output_dir / "logs" / "step0_equivalence.json").write_text(
            json.dumps(equiv, indent=2) + "\n"
        )
        if not equiv["passed"]:
            raise SystemExit("step0 equivalence failed")

        print("STEP0 eval deterministic on 100 val seeds…", flush=True)
        step0_det = self.evaluate_seeds(
            seeds=self.val_seeds, deterministic=True, reason="step0_deterministic"
        )
        (self.output_dir / "evaluation" / "step0_deterministic.json").write_text(
            json.dumps(step0_det, indent=2) + "\n"
        )
        print(
            f"step0 land={step0_det['counts']} rate={step0_det['landing_rate']:.3f} "
            f"frames={step0_det['diagnostic_frames']} diag_spent={self.diag_budget.spent}",
            flush=True,
        )

        # --- STEP 2: train ---
        seeds = self._sample_train_seeds(cfg.n_envs)
        obs, infos = self.env.reset(seeds)
        for i, info in enumerate(infos):
            self._cmd_rotation[i] = int(round(float(info["start"]["rotation"]) / 10.0) * 10)

        pending_marks = [50_000, 100_000, 150_000, 200_000]
        done_marks: set[int] = set()
        early_stop = None
        try:
            while True:
                # Stop before rollout that cannot fit
                need = cfg.rollout_steps * cfg.n_envs * cfg.action_repeat
                if not self.train_budget.can_afford(need):
                    early_stop = "training_budget_exhausted_before_rollout"
                    break
                obs = self.collect_and_update(obs)

                # Intermediate checkpoint + subset eval
                for mark in pending_marks:
                    if mark in done_marks or self.global_step < mark:
                        continue
                    tag = f"step{self.global_step}"
                    self.save_checkpoint(tag)
                    self.save_checkpoint(f"mark{mark}")
                    print(f"INTERMEDIATE EVAL mark={mark} step={self.global_step}", flush=True)
                    res = self.evaluate_seeds(
                        seeds=self.intermediate_seeds,
                        deterministic=True,
                        reason=f"intermediate_{mark}",
                    )
                    step0_sub_rows = [
                        r for r in step0_det["per_seed"] if r["seed"] in set(self.intermediate_seeds)
                    ]
                    sc = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
                    for r in step0_sub_rows:
                        if r["status"] == "landed":
                            sc["perfect"] += 1
                        elif r["status"] == "hard_landing":
                            sc["hard"] += 1
                        elif r["status"] == "crashed":
                            sc["crash"] += 1
                        else:
                            sc["timeout"] += 1
                    land0 = sc["perfect"] + sc["hard"]
                    p0, lo0, hi0 = wilson_ci(land0, len(self.intermediate_seeds))
                    step0_sub = {
                        "per_seed": step0_sub_rows,
                        "n": len(self.intermediate_seeds),
                        "counts": sc,
                        "landing_rate": p0,
                        "landing_wilson95": [lo0, hi0],
                    }
                    cmp_ = self.compare_to_step0(res, step0_sub)
                    div = self.policy_divergence_vs_step0()
                    entry = {
                        "tag": f"mark{mark}",
                        "actual_tag": tag,
                        "global_step": self.global_step,
                        "eval": {k: v for k, v in res.items() if k != "per_seed"},
                        "per_seed": res["per_seed"],
                        "vs_step0": cmp_,
                        "policy_vs_step0": div,
                    }
                    self._eval_log.append(entry)
                    with (self.output_dir / "logs" / "checkpoint_evals.jsonl").open("a") as f:
                        f.write(json.dumps(entry) + "\n")
                    print(
                        f"  land={res['counts']} mcnemar={cmp_['mcnemar']} div={div}",
                        flush=True,
                    )
                    done_marks.add(mark)
        except TrainingBudgetExhausted as exc:
            early_stop = "training_budget_exhausted"
            print("TRAIN STOP", exc, flush=True)
        except DiagnosticBudgetExhausted as exc:
            early_stop = "diagnostic_budget_exhausted"
            print("DIAG STOP", exc, flush=True)

        self._flush_metrics()
        final_path = self.save_checkpoint("final")
        final_sha = sha256_file(final_path)

        # --- STEP 3: final eval on full 100 seeds ---
        print("FINAL eval deterministic on 100 val seeds…", flush=True)
        try:
            final_det = self.evaluate_seeds(
                seeds=self.val_seeds, deterministic=True, reason="final_deterministic"
            )
        except DiagnosticBudgetExhausted as exc:
            early_stop = early_stop or "diagnostic_budget_exhausted_at_final"
            print("FINAL EVAL STOP", exc, flush=True)
            final_det = {"error": str(exc), "counts": {}, "per_seed": [], "n": 0}

        final_cmp = None
        final_div = None
        if final_det.get("per_seed"):
            final_cmp = self.compare_to_step0(final_det, step0_det)
            final_div = self.policy_divergence_vs_step0()
            entry = {
                "tag": "final",
                "global_step": self.global_step,
                "eval": {k: v for k, v in final_det.items() if k != "per_seed"},
                "per_seed": final_det["per_seed"],
                "vs_step0": final_cmp,
                "policy_vs_step0": final_div,
            }
            self._eval_log.append(entry)
            (self.output_dir / "evaluation" / "final_deterministic.json").write_text(
                json.dumps(final_det, indent=2) + "\n"
            )

        # Train landing count
        train_landings = 0
        land_path = self.output_dir / "logs" / "train_landings.jsonl"
        if land_path.exists():
            train_landings = sum(1 for _ in land_path.read_text().splitlines() if _.strip())

        summary = {
            "run_id": cfg.run_name,
            "result_headline": None,  # filled below
            "physics_frames_train": self.train_budget.spent,
            "physics_frames_diagnostic": self.diag_budget.spent,
            "train_budget": self.train_budget.snapshot(),
            "diagnostic_budget": self.diag_budget.snapshot(),
            "early_stop_reason": early_stop,
            "step0_sha256": self._step0_sha,
            "final_sha256": final_sha,
            "step0_counts": step0_det.get("counts"),
            "step0_landing_rate": step0_det.get("landing_rate"),
            "final_counts": final_det.get("counts"),
            "final_landing_rate": final_det.get("landing_rate"),
            "final_vs_step0": final_cmp,
            "final_policy_vs_step0": final_div,
            "train_landing_events": train_landings,
            "first_landing_frames": self._first_landing_frames,
            "milestone": self._milestone,
            "integrity": json.loads(
                (self.output_dir / "logs" / "integrity_check.json").read_text()
            ),
            "step0_equivalence": equiv,
            "prereg_seeds_sha256": (PREREG / "val_seeds.sha256").read_text().strip(),
            "wall_seconds": time.time() - self._started,
            "updates": self.update_idx,
        }
        # Headline
        if final_cmp and (
            final_cmp["beats_step0_mcnemar_p_lt_0.01"]
            or final_cmp["wilson_nonoverlap_ckpt_above_step0"]
        ):
            summary["result_headline"] = "STATISTICAL_IMPROVEMENT_OVER_STEP0"
        elif train_landings > 0 or (
            final_det.get("counts", {}).get("perfect", 0)
            + final_det.get("counts", {}).get("hard", 0)
            > 0
        ):
            summary["result_headline"] = "LANDINGS_OBSERVED_BUT_NO_RELIABLE_IMPROVEMENT_OVER_STEP0"
        else:
            summary["result_headline"] = "NO_TRAINED_LANDINGS_AND_NO_IMPROVEMENT_OVER_STEP0"

        (self.output_dir / "logs" / "train_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        (self.output_dir / "logs" / "checkpoint_evals.json").write_text(
            json.dumps(self._eval_log, indent=2) + "\n"
        )
        self.env.close()
        return summary


def load_config(path: Path | None) -> V6Config:
    cfg = V6Config()
    if path is None:
        return cfg
    raw = yaml.safe_load(path.read_text()) or {}
    names = {f.name for f in fields(V6Config)}
    for k, v in raw.items():
        if k in names:
            setattr(cfg, k, v)
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=HERE / "configs" / "V6_L0near_s31.yaml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None)
    args = parser.parse_args()
    cfg = load_config(args.config)
    out = args.output or (RESULTS / cfg.run_name)
    trainer = V6Trainer(cfg, out)
    if args.resume:
        trainer.load_checkpoint(args.resume)
        with (out / "logs" / "resume_events.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "event": "resume",
                        "checkpoint": str(args.resume),
                        "global_step": trainer.global_step,
                        "preserved": trainer._resume_preserved,
                    }
                )
                + "\n"
            )
    summary = trainer.run()
    print("SUMMARY", json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
