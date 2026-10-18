#!/usr/bin/env python3
"""Clean L0 learning validation — matched step-0 baseline, no priors, no curriculum advance.

Hard limits:
- ≤250_000 training physics frames
- ≤400_000 diagnostic physics frames (baselines/gates/evals/step-0)
- Never touch reserved seeds 2000000–2000015
- Never modify frontend/apollolander/upstream/
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
from rewardbench.rl.train_integrity import (  # noqa: E402
    early_stop_reason_for_failed_check,
    preserve_resume_artifacts,
    should_early_stop_on_failed_check,
)
from rewardbench.rl.upstream_env import (  # noqa: E402
    ApolloLanderUpstreamEnv,
    VectorApolloLanderUpstreamEnv,
)

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
LEVEL = "apollolander.starts.curriculum_l0_v3"
TRAIN_HARD_CAP = 250_000
DIAG_HARD_CAP = 400_000


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


def two_proportion_pvalue(s1: int, n1: int, s2: int, n2: int) -> float:
    """Two-sided two-proportion z-test p-value (pooled)."""
    if n1 <= 0 or n2 <= 0:
        return 1.0
    p1, p2 = s1 / n1, s2 / n2
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p) * (1 / n1 + 1 / n2), 1e-16))
    if se <= 0:
        return 1.0
    z = (p1 - p2) / se
    return float(2 * (1 - scipy_stats.norm.cdf(abs(z))))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class CleanConfig:
    total_budget: int = TRAIN_HARD_CAP
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
    seed: int = 21
    action_repeat: int = 1
    max_steps: int = 400
    rotation_mode: str = "delta"
    soft_thrust_prior: bool = False
    hold_attitude_prior: bool = False
    init_scheme: str = "orthogonal_zero_bias"
    allow_level_advance: bool = False
    level: str = LEVEL
    checkpoint_every_frames: int = 50_000
    eval_every_frames: int = 50_000
    val_episodes: int = 40
    val_seed_start: int = 510_000
    train_seed_start: int = 82_000
    train_seed_count: int = 100_000
    diagnostic_hard_cap: int = DIAG_HARD_CAP
    device: str = "cpu"
    run_name: str = "CLEAN_L0_s21"


class CleanL0Trainer:
    def __init__(self, cfg: CleanConfig, output_dir: Path) -> None:
        if cfg.soft_thrust_prior or cfg.hold_attitude_prior:
            raise ValueError("clean experiment forbids output-layer priors")
        if cfg.allow_level_advance:
            raise ValueError("clean experiment is L0-only; allow_level_advance must be false")
        if cfg.total_budget > TRAIN_HARD_CAP:
            raise ValueError(f"train budget {cfg.total_budget} exceeds {TRAIN_HARD_CAP}")
        if cfg.diagnostic_hard_cap > DIAG_HARD_CAP:
            raise ValueError("diagnostic hard cap must not be raised above 400000")
        if cfg.init_scheme != "orthogonal_zero_bias":
            raise ValueError(f"unsupported init_scheme {cfg.init_scheme}")
        if cfg.level != LEVEL:
            raise ValueError(f"clean experiment is fixed to {LEVEL}")

        self.cfg = cfg
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("checkpoints", "logs", "plots", "evidence", "evaluation"):
            (self.output_dir / sub).mkdir(exist_ok=True)

        self.diagnostic_budget = DiagnosticBudget(hard_cap=int(cfg.diagnostic_hard_cap))
        self.device = torch.device(cfg.device)
        self._set_seeds(cfg.seed)
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
        # Documented init: orthogonal gain=1.0, zero bias, thrust_log_std=0.
        self.policy.reset_parameters_clean()
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=cfg.learning_rate, eps=1e-5)

        self.global_step = 0
        self.global_decisions = 0
        self.update_idx = 0
        self.level_idx = 0
        self._rng = np.random.default_rng(cfg.seed + 17)
        self._cmd_rotation = np.zeros(cfg.n_envs, dtype=np.int64)
        self._train_seeds = np.arange(
            cfg.train_seed_start, cfg.train_seed_start + cfg.train_seed_count, dtype=np.int64
        )
        assert_seeds_allowed(self._train_seeds.tolist(), context="clean.train_seeds")
        val_seeds = list(range(cfg.val_seed_start, cfg.val_seed_start + cfg.val_episodes))
        assert_seeds_allowed(val_seeds, context="clean.val_seeds")

        self._episode_returns = np.zeros(cfg.n_envs, dtype=np.float64)
        self._metrics: list[dict[str, Any]] = []
        self._eval_log: list[dict[str, Any]] = []
        self._first_landing_frames: dict[str, int | None] = {cfg.level: None}
        self._started = time.time()
        self._resume_preserved: dict[str, Any] = {}
        self._write_metadata()

    def _set_seeds(self, seed: int) -> None:
        torch.manual_seed(seed)
        np.random.seed(seed)

    def _write_metadata(self) -> None:
        meta = {
            "run_name": self.cfg.run_name,
            "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "cfg": asdict(self.cfg),
            "level": self.cfg.level,
            "init_scheme": self.cfg.init_scheme,
            "priors": {"soft_thrust_prior": False, "hold_attitude_prior": False},
            "matched_baseline": "step0_checkpoint_same_network",
            "diagnostic_hard_cap": self.cfg.diagnostic_hard_cap,
            "train_hard_cap": TRAIN_HARD_CAP,
        }
        (self.output_dir / "run_metadata.json").write_text(json.dumps(meta, indent=2) + "\n")
        (self.output_dir / "config_snapshot.yaml").write_text(
            yaml.safe_dump(asdict(self.cfg), sort_keys=False), encoding="utf-8"
        )

    def save_checkpoint(self, tag: str) -> Path:
        path = self.output_dir / "checkpoints" / f"{tag}.pt"
        payload = {
            "policy": self.policy.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "global_step": self.global_step,
            "global_decisions": self.global_decisions,
            "update_idx": self.update_idx,
            "level_idx": 0,
            "level": self.cfg.level,
            "cfg": asdict(self.cfg),
            "rng_state": self._rng.bit_generator.state,
            "init_scheme": self.cfg.init_scheme,
        }
        torch.save(payload, path)
        digest = sha256_file(path)
        meta = {
            "tag": tag,
            "path": str(path),
            "sha256": digest,
            "global_step": self.global_step,
            "level": self.cfg.level,
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
        self.level_idx = 0  # L0-only
        if "rng_state" in data:
            self._rng.bit_generator.state = data["rng_state"]
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
            if self.cfg.rotation_mode == "delta":
                delta = int(ROTATION_DELTAS[int(idx[i])])
                abs_rot = int(np.clip(self._cmd_rotation[i] + delta, -90, 90))
                abs_rot = int(round(abs_rot / 10.0) * 10)
                self._cmd_rotation[i] = abs_rot
                commands.append({"thrust": float(thrusts[i]), "rotation": abs_rot})
            else:
                abs_rot = int(self.policy.decode_rotation(rot_idx[i : i + 1]).item())
                self._cmd_rotation[i] = abs_rot
                commands.append({"thrust": float(thrusts[i]), "rotation": abs_rot})
        return commands

    def verify_step0_equivalence(self, step0_path: Path) -> dict[str, Any]:
        """Bit-for-bit prediction match: live policy vs loaded step-0 on fixed obs batch."""
        ckpt = torch.load(step0_path, map_location=self.device, weights_only=False)
        other = ContinuousThrustActorCritic(
            hidden=self.cfg.hidden,
            rotation_mode=self.cfg.rotation_mode,
            soft_thrust_prior=False,
            hold_attitude_prior=False,
        ).to(self.device)
        other.load_state_dict(ckpt["policy"])
        other.eval()
        self.policy.eval()
        g = torch.Generator(device="cpu")
        g.manual_seed(12345)
        obs = torch.randn(64, 10, generator=g)
        with torch.no_grad():
            t1, r1, v1 = self.policy.forward(obs.to(self.device))
            t2, r2, v2 = other.forward(obs.to(self.device))
            d_mean = (t1.mean - t2.mean).abs().max().item()
            d_std = (t1.stddev - t2.stddev).abs().max().item()
            d_logits = (r1.logits - r2.logits).abs().max().item()
            d_value = (v1 - v2).abs().max().item()
            # Deterministic actions
            th1, ri1, _ = self.policy.act_deterministic(obs.to(self.device))
            th2, ri2, _ = other.act_deterministic(obs.to(self.device))
            d_thrust = (th1 - th2).abs().max().item()
            d_rot = (ri1.float() - ri2.float()).abs().max().item()
        max_abs = max(d_mean, d_std, d_logits, d_value, d_thrust, d_rot)
        result = {
            "step0_path": str(step0_path),
            "step0_sha256": sha256_file(step0_path),
            "batch_size": 64,
            "obs_seed": 12345,
            "max_abs_diff": max_abs,
            "diffs": {
                "thrust_mean": d_mean,
                "thrust_std": d_std,
                "rotation_logits": d_logits,
                "value": d_value,
                "det_thrust": d_thrust,
                "det_rotation_idx": d_rot,
            },
            "bit_exact": max_abs == 0.0,
            "passed": max_abs == 0.0,
        }
        (self.output_dir / "logs" / "step0_equivalence.json").write_text(
            json.dumps(result, indent=2) + "\n"
        )
        if not result["passed"]:
            raise RuntimeError(f"step-0 equivalence failed: max_abs_diff={max_abs}")
        return result

    def evaluate_policy(
        self,
        *,
        policy: ContinuousThrustActorCritic | None = None,
        mode: str,
        seed_start: int | None = None,
        n: int | None = None,
        reason: str,
    ) -> dict[str, Any]:
        """Frozen eval on fixed val seeds. Charges diagnostic budget."""
        pol = policy if policy is not None else self.policy
        seed_start = self.cfg.val_seed_start if seed_start is None else seed_start
        n = self.cfg.val_episodes if n is None else n
        deterministic = mode == "deterministic"
        cfg = self.env_config
        env = ApolloLanderUpstreamEnv(cfg, reward_mode="touchdown_v1")
        counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
        returns: list[float] = []
        durations: list[int] = []
        diag_frames = 0
        pol.eval()
        try:
            for i in range(n):
                seed = seed_start + i
                assert_seed_allowed(seed, context="clean.eval")
                obs, info0 = env.reset(seed)
                done = False
                ep_ret = 0.0
                steps = 0
                info: dict[str, Any] = {}
                cmd_rot = int(round(float(info0["start"]["rotation"]) / 10.0) * 10)
                while not done:
                    with torch.no_grad():
                        t = torch.as_tensor(obs[None], dtype=torch.float32, device=self.device)
                        if mode == "random":
                            thrust = float(np.random.uniform(0.0, 1.0))
                            if self.cfg.rotation_mode == "delta":
                                rot_choice = int(np.random.randint(0, 3))
                                delta = int(ROTATION_DELTAS[rot_choice])
                                cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                                cmd_rot = int(round(cmd_rot / 10.0) * 10)
                            else:
                                cmd_rot = int(pol.decode_rotation(
                                    torch.tensor([np.random.randint(0, pol.n_rotations)])
                                ).item())
                            command = {"thrust": thrust, "rotation": cmd_rot}
                        else:
                            if deterministic:
                                thrust_t, rot_idx, _ = pol.act_deterministic(t)
                            else:
                                thrust_t, rot_idx, _, _, _ = pol.act(t)
                            if self.cfg.rotation_mode == "delta":
                                delta = int(ROTATION_DELTAS[int(rot_idx.item())])
                                cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                                cmd_rot = int(round(cmd_rot / 10.0) * 10)
                            else:
                                cmd_rot = int(pol.decode_rotation(rot_idx).item())
                            command = {"thrust": float(thrust_t.item()), "rotation": cmd_rot}
                    obs, reward, terminated, truncated, info = env.step_command(command)
                    ep_ret += reward
                    steps += 1
                    diag_frames += int(info.get("action_repeat", self.cfg.action_repeat))
                    done = terminated or truncated
                status = info.get("status", "")
                if status == "landed":
                    counts["perfect"] += 1
                elif status == "hard_landing":
                    counts["hard"] += 1
                elif status == "crashed":
                    counts["crash"] += 1
                elif status == "timeout":
                    counts["timeout"] += 1
                returns.append(ep_ret)
                durations.append(int(info.get("steps", steps)))
        finally:
            env.close()

        self.diagnostic_budget.charge(diag_frames, reason=reason)
        land = counts["perfect"] + counts["hard"]
        p, lo, hi = wilson_ci(land, n)
        return {
            "mode": mode,
            "level": self.cfg.level,
            "n": n,
            "seed_start": seed_start,
            "max_steps": self.cfg.max_steps,
            "counts": counts,
            "landing_rate": p,
            "landing_wilson95": [lo, hi],
            "mean_return": float(np.mean(returns)) if returns else 0.0,
            "mean_duration": float(np.mean(durations)) if durations else 0.0,
            "diagnostic_frames": diag_frames,
            "global_step_at_eval": self.global_step,
            "diagnostic_budget_spent": self.diagnostic_budget.spent,
        }

    def _compare_to_baseline(self, result: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
        s1 = result["counts"]["perfect"] + result["counts"]["hard"]
        n1 = result["n"]
        s0 = baseline["counts"]["perfect"] + baseline["counts"]["hard"]
        n0 = baseline["n"]
        lo1, hi1 = result["landing_wilson95"][0], result["landing_wilson95"][1]
        lo0, hi0 = baseline["landing_wilson95"][0], baseline["landing_wilson95"][1]
        nonoverlap = lo1 > hi0
        pval = two_proportion_pvalue(s1, n1, s0, n0)
        beats = bool(nonoverlap or (s1 > s0 and pval < 0.01))
        return {
            "beats_step0": beats,
            "wilson_nonoverlap": nonoverlap,
            "two_proportion_p": pval,
            "step0_landings": s0,
            "ckpt_landings": s1,
        }

    def collect_and_update(self, obs: np.ndarray) -> np.ndarray:
        cfg = self.cfg
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
        self.policy.train()
        for t in range(n_steps):
            with torch.no_grad():
                obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
                thrust, rot_idx, raw, log_prob, values = self.policy.act(obs_t)
                commands = self._commands_from_actions(thrust, rot_idx)
            next_obs, rewards, terminated, truncated, infos = self.env.step_commands(commands)
            self.global_step += n_envs * cfg.action_repeat
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
                    if landed and self._first_landing_frames[self.cfg.level] is None:
                        self._first_landing_frames[self.cfg.level] = self.global_step
                        evidence = {
                            "event": "first_train_landing",
                            "level": self.cfg.level,
                            "frames": self.global_step,
                            "status": status,
                            "native_outcome": info.get("native_outcome"),
                        }
                        with (self.output_dir / "logs" / "first_landings.jsonl").open("a") as f:
                            f.write(json.dumps(evidence) + "\n")
                        self.save_checkpoint(f"first_land_{self.global_step}")
                    row = {
                        "global_step": self.global_step,
                        "level": self.cfg.level,
                        "level_idx": 0,
                        "return": float(self._episode_returns[i]),
                        "status": status,
                        "landed": landed,
                        "perfect": status == "landed",
                        "hard": status == "hard_landing",
                        "crashed": status == "crashed",
                        "timed_out": status == "timeout",
                        "fuel_used": float(info.get("fuel_used", 0)),
                        "steps": int(info.get("steps", 0)),
                    }
                    self._metrics.append(row)
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
            obs = next_obs

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

        # PPO update
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
        # Flush every update so a crash/interrupt cannot wipe episode rows.
        self._flush_metrics()
        return obs

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

    def _eval_checkpoint(self, tag: str, step0_det: dict[str, Any], step0_sto: dict[str, Any]) -> dict[str, Any]:
        det = self.evaluate_policy(mode="deterministic", reason=f"ckpt_det:{tag}")
        sto = self.evaluate_policy(mode="stochastic", reason=f"ckpt_sto:{tag}")
        entry = {
            "tag": tag,
            "global_step": self.global_step,
            "deterministic": det,
            "stochastic": sto,
            "vs_step0_deterministic": self._compare_to_baseline(det, step0_det),
            "vs_step0_stochastic": self._compare_to_baseline(sto, step0_sto),
        }
        self._eval_log.append(entry)
        with (self.output_dir / "logs" / "checkpoint_evals.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(
            f"EVAL {tag} det_land={det['landing_rate']:.3f} {det['counts']} "
            f"sto_land={sto['landing_rate']:.3f} {sto['counts']} "
            f"beats_step0_det={entry['vs_step0_deterministic']['beats_step0']}",
            flush=True,
        )
        return entry

    def train(self) -> dict[str, Any]:
        cfg = self.cfg
        early_stop_reason = None
        learning_claimed = False

        # Step-0 checkpoint + equivalence + matched baselines on fixed val set.
        step0_path = self.save_checkpoint("step0")
        equiv = self.verify_step0_equivalence(step0_path)
        print("step0 equivalence:", json.dumps(equiv), flush=True)

        step0_det = self.evaluate_policy(mode="deterministic", reason="step0_det")
        step0_sto = self.evaluate_policy(mode="stochastic", reason="step0_sto")
        random_base = self.evaluate_policy(mode="random", reason="random_baseline")
        baselines = {
            "step0_deterministic": step0_det,
            "step0_stochastic": step0_sto,
            "random": random_base,
            "step0_equivalence": equiv,
        }
        (self.output_dir / "logs" / "step0_baselines.json").write_text(
            json.dumps(baselines, indent=2) + "\n"
        )
        print("step0 baselines:", json.dumps(baselines, indent=2), flush=True)

        # Also record step0 in eval log.
        self._eval_log.append(
            {
                "tag": "step0",
                "global_step": 0,
                "deterministic": step0_det,
                "stochastic": step0_sto,
                "vs_step0_deterministic": self._compare_to_baseline(step0_det, step0_det),
                "vs_step0_stochastic": self._compare_to_baseline(step0_sto, step0_sto),
            }
        )

        seeds = self._sample_train_seeds(cfg.n_envs)
        obs, infos = self.env.reset(seeds)
        for i, info in enumerate(infos):
            self._cmd_rotation[i] = int(round(float(info["start"]["rotation"]) / 10.0) * 10)

        next_ckpt_at = cfg.checkpoint_every_frames
        next_eval_at = cfg.eval_every_frames

        try:
            while self.global_step < cfg.total_budget:
                obs = self.collect_and_update(obs)

                if self.global_step >= next_ckpt_at:
                    tag = f"step{self.global_step}"
                    self.save_checkpoint(tag)
                    self._flush_metrics()
                    entry = self._eval_checkpoint(tag, step0_det, step0_sto)
                    next_ckpt_at += cfg.checkpoint_every_frames
                    next_eval_at = next_ckpt_at
                    if entry["vs_step0_deterministic"]["beats_step0"]:
                        learning_claimed = True
                        # Continue within budget but record claim; integrity still enforced.
                    # Integrity: if somehow a check fails we stop — mirrored for future gates.
                    # No curriculum advance by design.

                # Soft integrity: diagnostic budget is hard-enforced inside evaluate_policy.
        except DiagnosticBudgetExhausted as exc:
            early_stop_reason = "diagnostic_budget_exhausted"
            print("STOP:", exc, flush=True)
            (self.output_dir / "logs" / "diagnostic_budget_exhausted.json").write_text(
                json.dumps(self.diagnostic_budget.snapshot(), indent=2) + "\n"
            )

        self._flush_metrics()
        self.save_checkpoint("final")
        # Final eval if budget remains and not already evaluated at this step.
        if early_stop_reason != "diagnostic_budget_exhausted":
            try:
                if not self._eval_log or self._eval_log[-1]["global_step"] != self.global_step:
                    final_entry = self._eval_checkpoint("final", step0_det, step0_sto)
                    if final_entry["vs_step0_deterministic"]["beats_step0"]:
                        learning_claimed = True
            except DiagnosticBudgetExhausted as exc:
                early_stop_reason = early_stop_reason or "diagnostic_budget_exhausted"
                print("STOP at final eval:", exc, flush=True)

        # Learning integrity check: must beat step-0 with statistical criterion.
        best = max(
            self._eval_log,
            key=lambda e: e["deterministic"]["landing_rate"],
            default=None,
        )
        integrity_passed = bool(
            best and best["vs_step0_deterministic"]["beats_step0"]
        )
        if not integrity_passed and early_stop_reason is None:
            # Not a failure that stops mid-run (we finished the budget); record honest outcome.
            pass

        # Explicit failed learning-gate stop semantics for any future mid-run gate.
        # If we had a dedicated mid-run learning gate that failed, stop regardless of level:
        if best is not None and should_early_stop_on_failed_check(
            check_passed=integrity_passed, level_idx=self.level_idx
        ):
            # Only set if we want to mark post-hoc; do not override diag exhaustion.
            if early_stop_reason is None and self.global_step < cfg.total_budget:
                early_stop_reason = early_stop_reason_for_failed_check("clean_learning_gate")

        wall = time.time() - self._started
        train_landings = 0
        curve = self.output_dir / "logs" / "learning_curve.csv"
        if curve.exists():
            with curve.open(newline="") as f:
                train_landings = sum(1 for r in csv.DictReader(f) if r.get("landed") == "True")

        summary = {
            "run_id": cfg.run_name,
            "physics_frames": self.global_step,
            "policy_decisions": self.global_decisions,
            "updates": self.update_idx,
            "level": cfg.level,
            "first_landing_frames": self._first_landing_frames,
            "train_landing_episodes": train_landings,
            "wall_seconds": wall,
            "early_stop_reason": early_stop_reason,
            "budget": cfg.total_budget,
            "diagnostic_budget": self.diagnostic_budget.snapshot(),
            "learning_claimed": learning_claimed and integrity_passed,
            "integrity_passed": integrity_passed,
            "init_scheme": cfg.init_scheme,
            "resume_preserved": self._resume_preserved,
            "best_checkpoint_eval": best,
            "step0_baselines": {
                "deterministic": step0_det,
                "stochastic": step0_sto,
                "random": random_base,
            },
            "step0_equivalence": equiv,
            "claim_rule": (
                "Wilson non-overlap vs step-0 OR two-proportion p<0.01 on fixed val set; "
                "never from one stochastic landing or shaped reward"
            ),
        }
        (self.output_dir / "logs" / "train_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        (self.output_dir / "logs" / "checkpoint_evals.json").write_text(
            json.dumps(self._eval_log, indent=2) + "\n"
        )
        (self.output_dir / "logs" / "diagnostic_budget.json").write_text(
            json.dumps(self.diagnostic_budget.snapshot(), indent=2) + "\n"
        )
        self.env.close()
        return summary


def load_config(path: Path | None) -> CleanConfig:
    cfg = CleanConfig()
    if path is None:
        return cfg
    raw = yaml.safe_load(path.read_text()) or {}
    names = {f.name for f in fields(CleanConfig)}
    for k, v in raw.items():
        if k in names:
            setattr(cfg, k, v)
    return cfg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=HERE / "configs" / "CLEAN_L0_s21.yaml")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument("--total-budget", type=int, default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.total_budget is not None:
        cfg.total_budget = min(args.total_budget, TRAIN_HARD_CAP)
    out = args.output or (RESULTS / cfg.run_name)
    trainer = CleanL0Trainer(cfg, out)
    if args.resume:
        print("CONTINUOUS RESUME", args.resume, flush=True)
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
    summary = trainer.train()
    print("SUMMARY", json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
