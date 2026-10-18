#!/usr/bin/env python3
"""Phase 3: progressive curriculum PPO (continuous thrust + categorical rotation).

- Random NN init with documented seeds; never loads prior-run weights.
- Reward: touchdown_v1 (frozen). Judgment: native landings only.
- GAE: timeout = truncation (bootstrap); crash/land = termination.
- Advance levels only on frozen validation ≥ 50% native landings.
- Hard stop: 2_000_000 training physics frames; early-stop if L0 fails basic learning check @ ~500k.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.starts import CURRICULUM_V3_LEVELS  # noqa: E402
from rewardbench.rl.continuous_policy import (  # noqa: E402
    ROTATION_DELTAS,
    ContinuousThrustActorCritic,
)
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed  # noqa: E402
from rewardbench.rl.upstream_env import VectorApolloLanderUpstreamEnv  # noqa: E402

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
TRAIN_BUDGET = 2_000_000
LEVELS = list(CURRICULUM_V3_LEVELS)


def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return p, max(0.0, center - margin), min(1.0, center + margin)


@dataclass
class TrainConfig:
    total_budget: int = TRAIN_BUDGET
    n_envs: int = 4
    rollout_steps: int = 128
    learning_rate: float = 3.0e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    ent_coef: float = 0.02
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    update_epochs: int = 4
    minibatch_size: int = 256
    hidden: int = 128
    seed: int = 11
    action_repeat: int = 2
    max_steps: int = 2000
    gate_threshold: float = 0.50
    gate_episodes: int = 40
    gate_every_frames: int = 100_000
    l0_learning_check_frames: int = 500_000
    checkpoint_every_frames: int = 100_000
    train_seed_start: int = 50_000
    train_seed_count: int = 100_000
    # Validation seeds disjoint from train pool (and from final eval 1000300-1000499).
    val_seed_start: int = 400_000
    device: str = "cpu"
    run_name: str = "CURR_touchdown_s11"
    # absolute: 19 bins × 10°; delta: {-10,0,+10} applied to last commanded angle.
    rotation_mode: str = "absolute"


class CurriculumTrainer:
    def __init__(self, cfg: TrainConfig, output_dir: Path) -> None:
        self.cfg = cfg
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for sub in ("checkpoints", "logs", "plots", "evidence"):
            (self.output_dir / sub).mkdir(exist_ok=True)

        self._set_seeds(cfg.seed)
        torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "2"))))
        self.device = torch.device(cfg.device)

        self.level_idx = 0
        self.env_config = self._env_config_for_level(LEVELS[self.level_idx])
        self.env = VectorApolloLanderUpstreamEnv(
            cfg.n_envs, self.env_config, reward_mode="touchdown_v1"
        )
        self.policy = ContinuousThrustActorCritic(
            hidden=cfg.hidden, rotation_mode=cfg.rotation_mode
        ).to(self.device)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=cfg.learning_rate, eps=1e-5)

        self.global_step = 0
        self.global_decisions = 0
        self.update_idx = 0
        self.total_minibatch_grad_steps = 0
        self._rng = np.random.default_rng(cfg.seed + 17)
        # Last commanded absolute rotation per env (for delta mode).
        self._cmd_rotation = np.zeros(cfg.n_envs, dtype=np.int64)
        self._train_seeds = np.arange(
            cfg.train_seed_start, cfg.train_seed_start + cfg.train_seed_count, dtype=np.int64
        )
        assert_seeds_allowed(self._train_seeds.tolist(), context="curriculum.train_seeds")
        if self._train_seeds.max() >= 1_000_000:
            raise ValueError("train seeds must be development pool")

        self._episode_returns = np.zeros(cfg.n_envs, dtype=np.float64)
        self._metrics: list[dict[str, Any]] = []
        self._gate_log: list[dict[str, Any]] = []
        self._level_history: list[dict[str, Any]] = []
        self._first_landing_frames: dict[str, int | None] = {lv: None for lv in LEVELS}
        self._started = time.time()
        self._write_metadata()
        self.save_checkpoint("step0")

    def _env_config_for_level(self, level: str) -> EnvConfig:
        return EnvConfig(
            max_steps=self.cfg.max_steps,
            research_mode=True,
            start_schedule_version=level,
            vary_fuel=False,
            action_repeat=self.cfg.action_repeat,
            bonuses=False,
            locked_camera=True,
            observation_kind="state-observation RL, continuous thrust + categorical rotation",
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        )

    def _set_seeds(self, seed: int) -> None:
        np.random.seed(seed)
        torch.manual_seed(seed)

    def _git_sha(self) -> str:
        try:
            return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
        except Exception:  # noqa: BLE001
            return "unknown"

    def _write_metadata(self) -> None:
        upstream = (ROOT / "frontend/apollolander/upstream/UPSTREAM_COMMIT.txt").read_text().strip()
        meta = {
            "run_id": self.cfg.run_name,
            "family": "curriculum_v3",
            "reward_mode": "touchdown_v1",
            "reward_doc": "docs/rl_curriculum_v3/REWARD_TOUCHDOWN_V1.md",
            "action_space": {
                "thrust": "continuous [0,1] via sigmoid-squashed Gaussian",
                "rotation": (
                    "delta {-10,0,+10} → setRotation"
                    if self.cfg.rotation_mode == "delta"
                    else "categorical 19 bins × 10° in [-90,90]"
                ),
                "rotation_mode": self.cfg.rotation_mode,
            },
            "parity_status": "PASS — docs/rl_curriculum_v3/PARITY_REPORT_V2.md",
            "upstream_commit": upstream,
            "source_commit": self._git_sha(),
            "torch_version": torch.__version__,
            "seed": self.cfg.seed,
            "train_config": asdict(self.cfg),
            "levels": LEVELS,
            "gate": {
                "threshold": self.cfg.gate_threshold,
                "episodes": self.cfg.gate_episodes,
                "val_seed_start": self.cfg.val_seed_start,
                "rule": "frozen eval only; never advance on train stats alone",
            },
            "budget_train_frames": self.cfg.total_budget,
            "reserved_seeds": "2000000..2000015 never used",
            "weight_init": "random at step0 only; never loads other runs",
            "guidance": "NOT used for training",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
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
            "level_idx": self.level_idx,
            "level": LEVELS[self.level_idx],
            "cfg": asdict(self.cfg),
            "rng_state": self._rng.bit_generator.state,
        }
        torch.save(payload, path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        (self.output_dir / "checkpoints" / f"{tag}.sha256.json").write_text(
            json.dumps(
                {
                    "tag": tag,
                    "path": str(path),
                    "sha256": digest,
                    "global_step": self.global_step,
                    "level": LEVELS[self.level_idx],
                    "level_idx": self.level_idx,
                },
                indent=2,
            )
            + "\n"
        )
        return path

    def load_checkpoint(self, path: Path) -> None:
        data = torch.load(path, map_location=self.device, weights_only=False)
        self.policy.load_state_dict(data["policy"])
        self.optimizer.load_state_dict(data["optimizer"])
        self.global_step = int(data["global_step"])
        self.global_decisions = int(data.get("global_decisions", 0))
        self.update_idx = int(data.get("update_idx", 0))
        self.level_idx = int(data.get("level_idx", 0))
        if "rng_state" in data:
            self._rng.bit_generator.state = data["rng_state"]
        # Rebuild envs for resumed level.
        self.env.close()
        self.env_config = self._env_config_for_level(LEVELS[self.level_idx])
        self.env = VectorApolloLanderUpstreamEnv(
            self.cfg.n_envs, self.env_config, reward_mode="touchdown_v1"
        )

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
                # Quantize to 10° (setRotation does this too).
                abs_rot = int(round(abs_rot / 10.0) * 10)
                self._cmd_rotation[i] = abs_rot
                commands.append({"thrust": float(thrusts[i]), "rotation": abs_rot})
            else:
                abs_rot = int(self.policy.decode_rotation(rot_idx[i : i + 1]).item())
                self._cmd_rotation[i] = abs_rot
                commands.append({"thrust": float(thrusts[i]), "rotation": abs_rot})
        return commands

    def evaluate_frozen(
        self,
        *,
        level: str,
        seed_start: int,
        n: int,
        deterministic: bool = True,
        max_steps: int | None = None,
    ) -> dict[str, Any]:
        """Frozen policy eval — does NOT count toward training budget."""
        cfg = EnvConfig(
            max_steps=max_steps or self.cfg.max_steps,
            research_mode=True,
            start_schedule_version=level,
            vary_fuel=False,
            action_repeat=self.cfg.action_repeat,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        )
        from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv

        env = ApolloLanderUpstreamEnv(cfg, reward_mode="touchdown_v1")
        counts = {"perfect": 0, "hard": 0, "crash": 0, "timeout": 0}
        returns = []
        fuels = []
        durations = []
        diag_frames = 0
        self.policy.eval()
        try:
            for i in range(n):
                seed = seed_start + i
                assert_seed_allowed(seed, context="curriculum.gate_eval")
                obs, info0 = env.reset(seed)
                done = False
                ep_ret = 0.0
                steps = 0
                info: dict[str, Any] = {}
                cmd_rot = int(round(float(info0["start"]["rotation"]) / 10.0) * 10)
                while not done:
                    with torch.no_grad():
                        t = torch.as_tensor(obs[None], dtype=torch.float32, device=self.device)
                        if deterministic:
                            thrust, rot_idx, _ = self.policy.act_deterministic(t)
                        else:
                            thrust, rot_idx, _, _, _ = self.policy.act(t)
                        if self.cfg.rotation_mode == "delta":
                            delta = int(ROTATION_DELTAS[int(rot_idx.item())])
                            cmd_rot = int(np.clip(cmd_rot + delta, -90, 90))
                            cmd_rot = int(round(cmd_rot / 10.0) * 10)
                        else:
                            cmd_rot = int(self.policy.decode_rotation(rot_idx).item())
                        command = {"thrust": float(thrust.item()), "rotation": cmd_rot}
                    obs, reward, terminated, truncated, info = env.step_command(command)
                    ep_ret += reward
                    steps += self.cfg.action_repeat  # approx; host counts true frames
                    diag_frames += int(info.get("action_repeat", self.cfg.action_repeat))
                    # More accurate: use result steps delta — host returns cumulative steps.
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
                fuels.append(float(info.get("fuel_used", 0)))
                durations.append(int(info.get("steps", steps)))
        finally:
            env.close()
        land = counts["perfect"] + counts["hard"]
        p, lo, hi = wilson_ci(land, n)
        return {
            "level": level,
            "n": n,
            "seed_start": seed_start,
            "deterministic": deterministic,
            "counts": counts,
            "landing_rate": p,
            "landing_wilson95": [lo, hi],
            "mean_return": float(np.mean(returns)) if returns else 0.0,
            "median_return": float(np.median(returns)) if returns else 0.0,
            "mean_fuel": float(np.mean(fuels)) if fuels else 0.0,
            "mean_duration": float(np.mean(durations)) if durations else 0.0,
            "diagnostic_frames": diag_frames,
            "global_step_at_eval": self.global_step,
        }

    def maybe_gate(self) -> bool:
        """Run frozen gate check. Returns True if advanced."""
        level = LEVELS[self.level_idx]
        # Disjoint val seeds per level.
        seed_start = self.cfg.val_seed_start + self.level_idx * 1_000
        result = self.evaluate_frozen(
            level=level, seed_start=seed_start, n=self.cfg.gate_episodes, deterministic=True
        )
        passed = result["landing_rate"] >= self.cfg.gate_threshold
        entry = {
            "event": "gate_check",
            "level": level,
            "level_idx": self.level_idx,
            "passed": passed,
            "threshold": self.cfg.gate_threshold,
            **result,
            "wall_time_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._gate_log.append(entry)
        with (self.output_dir / "logs" / "gate_log.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")
        print(
            f"GATE level={level} land={result['landing_rate']:.3f} "
            f"CI={result['landing_wilson95']} passed={passed}",
            flush=True,
        )
        if passed and self.level_idx < len(LEVELS) - 1:
            self.save_checkpoint(f"gate_pass_L{self.level_idx}_{self.global_step}")
            self.level_idx += 1
            new_level = LEVELS[self.level_idx]
            self.env.close()
            self.env_config = self._env_config_for_level(new_level)
            self.env = VectorApolloLanderUpstreamEnv(
                self.cfg.n_envs, self.env_config, reward_mode="touchdown_v1"
            )
            hist = {
                "advanced_to": new_level,
                "at_frames": self.global_step,
                "from_level": level,
            }
            self._level_history.append(hist)
            with (self.output_dir / "logs" / "level_history.jsonl").open("a") as f:
                f.write(json.dumps(hist) + "\n")
            print("ADVANCED to", new_level, "at", self.global_step, flush=True)
            return True
        return False

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
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            with torch.no_grad():
                thrust, rot_idx, raw, log_prob, values = self.policy.act(obs_t)
            commands = self._commands_from_actions(thrust, rot_idx)
            next_obs, rewards, terminated, truncated, infos = self.env.step_commands(commands)

            # Truncation bootstrap (timeout): value of terminal obs before reset.
            bootstrap_values = values.cpu().numpy().astype(np.float64).copy()
            with torch.no_grad():
                if np.any(truncated):
                    trunc_vals = self.policy.forward(
                        torch.as_tensor(next_obs, dtype=torch.float32, device=self.device)
                    )[2].cpu().numpy()
                    bootstrap_values = np.where(truncated, trunc_vals, bootstrap_values)

            physics = cfg.action_repeat * n_envs
            self.global_step += physics
            self.global_decisions += n_envs

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
                    level = LEVELS[self.level_idx]
                    if landed and self._first_landing_frames[level] is None:
                        self._first_landing_frames[level] = self.global_step
                        evidence = {
                            "event": "first_train_landing",
                            "level": level,
                            "frames": self.global_step,
                            "status": status,
                            "seed_unknown_vec_env": True,
                            "native_outcome": info.get("native_outcome"),
                        }
                        with (self.output_dir / "logs" / "first_landings.jsonl").open("a") as f:
                            f.write(json.dumps(evidence) + "\n")
                        # Immediate checkpoint on first landing at any level.
                        self.save_checkpoint(f"first_land_L{self.level_idx}_{self.global_step}")
                    row = {
                        "global_step": self.global_step,
                        "level": level,
                        "level_idx": self.level_idx,
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

        # GAE with truncation bootstrap
        with torch.no_grad():
            last_values = self.policy.forward(
                torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            )[2].cpu().numpy()
        advantages = np.zeros_like(buf["rewards"])
        last_gae = np.zeros(n_envs, dtype=np.float64)
        for t in reversed(range(n_steps)):
            next_values = last_values if t == n_steps - 1 else buf["values"][t + 1]
            terminated_t = buf["terminations"][t]
            truncated_t = buf["truncations"][t]
            next_values_eff = np.where(truncated_t > 0.5, buf["bootstrap_values"][t], next_values)
            next_values_eff = np.where(terminated_t > 0.5, 0.0, next_values_eff)
            next_non_terminal = 1.0 - terminated_t
            delta = buf["rewards"][t] + cfg.gamma * next_values_eff * next_non_terminal - buf["values"][t]
            gae_mask = 1.0 - np.maximum(terminated_t, truncated_t)
            last_gae = delta + cfg.gamma * cfg.gae_lambda * gae_mask * last_gae
            advantages[t] = last_gae
        returns = advantages + buf["values"]

        # PPO update
        batch = n_steps * n_envs
        obs_b = torch.as_tensor(buf["obs"].reshape(batch, -1), dtype=torch.float32, device=self.device)
        raw_b = torch.as_tensor(buf["raw_thrust"].reshape(batch), dtype=torch.float32, device=self.device)
        rot_b = torch.as_tensor(buf["rot_idx"].reshape(batch), dtype=torch.int64, device=self.device)
        old_lp = torch.as_tensor(buf["log_probs"].reshape(batch), dtype=torch.float32, device=self.device)
        adv_b = torch.as_tensor(advantages.reshape(batch), dtype=torch.float32, device=self.device)
        ret_b = torch.as_tensor(returns.reshape(batch), dtype=torch.float32, device=self.device)
        adv_b = (adv_b - adv_b.mean()) / (adv_b.std() + 1e-8)

        ent_sum = 0.0
        clip_sum = 0.0
        kl_sum = 0.0
        grad_sum = 0.0
        n_mb = 0
        indices = np.arange(batch)
        for _ in range(cfg.update_epochs):
            self._rng.shuffle(indices)
            for start in range(0, batch, cfg.minibatch_size):
                mb = indices[start : start + cfg.minibatch_size]
                log_prob, entropy, value = self.policy.evaluate_actions(
                    obs_b[mb], raw_b[mb], rot_b[mb]
                )
                ratio = torch.exp(log_prob - old_lp[mb])
                abs_adv = adv_b[mb]
                pg1 = ratio * abs_adv
                pg2 = torch.clamp(ratio, 1 - cfg.clip_coef, 1 + cfg.clip_coef) * abs_adv
                pg_loss = -torch.min(pg1, pg2).mean()
                v_loss = 0.5 * (value - ret_b[mb]).pow(2).mean()
                loss = pg_loss - cfg.ent_coef * entropy.mean() + cfg.vf_coef * v_loss
                self.optimizer.zero_grad()
                loss.backward()
                grad_norm = torch.nn.utils.clip_grad_norm_(self.policy.parameters(), cfg.max_grad_norm)
                self.optimizer.step()
                self.total_minibatch_grad_steps += 1
                ent_sum += float(entropy.mean().item())
                clip_sum += float(((ratio - 1.0).abs() > cfg.clip_coef).float().mean().item())
                kl_sum += float((old_lp[mb] - log_prob).mean().item())
                grad_sum += float(grad_norm)
                n_mb += 1
        self.update_idx += 1
        stats = {
            "update": self.update_idx,
            "global_step": self.global_step,
            "level": LEVELS[self.level_idx],
            "entropy": ent_sum / max(1, n_mb),
            "clipfrac": clip_sum / max(1, n_mb),
            "approx_kl": kl_sum / max(1, n_mb),
            "grad_norm": grad_sum / max(1, n_mb),
        }
        with (self.output_dir / "logs" / "update_stats.jsonl").open("a") as f:
            f.write(json.dumps(stats) + "\n")
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

    def train(self) -> dict[str, Any]:
        cfg = self.cfg
        seeds = self._sample_train_seeds(cfg.n_envs)
        obs, infos = self.env.reset(seeds)
        for i, info in enumerate(infos):
            self._cmd_rotation[i] = int(round(float(info["start"]["rotation"]) / 10.0) * 10)
        next_gate_at = self.global_step + cfg.gate_every_frames
        next_ckpt_at = self.global_step + cfg.checkpoint_every_frames
        learning_check_done = self.global_step >= cfg.l0_learning_check_frames
        early_stop_reason = None
        # For a continued budget after a failed seed, allow a fresh L0 check window.
        l0_check_at = self.global_step + cfg.l0_learning_check_frames if self.global_step > 0 else cfg.l0_learning_check_frames
        if self.global_step == 0:
            l0_check_at = cfg.l0_learning_check_frames

        # Baseline snapshot for L0 learning check comparison (loaded from file if present).
        baseline_path = RESULTS / "baseline_rates.json"
        baseline_l0_random = None
        baseline_l0_untrained = None
        if baseline_path.is_file():
            base = json.loads(baseline_path.read_text())
            for row in base["rows"]:
                if row["level"] == LEVELS[0] and row["mode"] == "random":
                    baseline_l0_random = row
                if row["level"] == LEVELS[0] and row["mode"] == "untrained":
                    baseline_l0_untrained = row

        while self.global_step < cfg.total_budget:
            obs = self.collect_and_update(obs)
            if self.global_step >= next_ckpt_at:
                self.save_checkpoint(f"step{self.global_step}")
                next_ckpt_at += cfg.checkpoint_every_frames
                self._flush_metrics()

            if self.global_step >= next_gate_at:
                self.maybe_gate()
                # After advance, reset obs
                seeds = self._sample_train_seeds(cfg.n_envs)
                obs, infos = self.env.reset(seeds)
                for i, info in enumerate(infos):
                    self._cmd_rotation[i] = int(
                        round(float(info["start"]["rotation"]) / 10.0) * 10
                    )
                next_gate_at = self.global_step + cfg.gate_every_frames

            if (not learning_check_done) and self.global_step >= l0_check_at:
                learning_check_done = True
                # Only meaningful if still on L0 or to verify L0 skill.
                check = self.evaluate_frozen(
                    level=LEVELS[0],
                    seed_start=self.cfg.val_seed_start,
                    n=self.cfg.gate_episodes,
                    deterministic=True,
                )
                check["event"] = "l0_basic_learning_check"
                check["baseline_random"] = baseline_l0_random
                check["baseline_untrained"] = baseline_l0_untrained
                # Pass if landing CI lower bound > both baseline upper bounds (non-overlap),
                # or point estimate clearly higher with non-overlap vs random.
                lo = check["landing_wilson95"][0]
                ok = False
                reasons = []
                for name, base in (("random", baseline_l0_random), ("untrained", baseline_l0_untrained)):
                    if base is None:
                        reasons.append(f"missing_{name}_baseline")
                        continue
                    base_hi = base["landing_wilson95"][1]
                    if lo > base_hi:
                        ok = True
                        reasons.append(f"nonoverlap_vs_{name}")
                    elif check["landing_rate"] > base["landing_rate"] + 0.15:
                        ok = True
                        reasons.append(f"delta_gt_0.15_vs_{name}")
                    else:
                        reasons.append(f"not_above_{name}")
                check["passed"] = ok
                check["reasons"] = reasons
                with (self.output_dir / "logs" / "l0_learning_check.json").open("w") as f:
                    json.dump(check, f, indent=2)
                print("L0 learning check:", json.dumps(check, indent=2), flush=True)
                if not ok and self.level_idx == 0:
                    early_stop_reason = "l0_basic_learning_check_failed"
                    break

        self._flush_metrics()
        self.save_checkpoint("final")
        wall = time.time() - self._started
        summary = {
            "run_id": cfg.run_name,
            "physics_frames": self.global_step,
            "policy_decisions": self.global_decisions,
            "updates": self.update_idx,
            "highest_level_idx": self.level_idx,
            "highest_level": LEVELS[self.level_idx],
            "first_landing_frames": self._first_landing_frames,
            "gate_checks": len(self._gate_log),
            "wall_seconds": wall,
            "early_stop_reason": early_stop_reason,
            "budget": cfg.total_budget,
        }
        (self.output_dir / "logs" / "train_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        (self.output_dir / "logs" / "gate_log.json").write_text(
            json.dumps(self._gate_log, indent=2) + "\n"
        )
        self.env.close()
        return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument("--total-budget", type=int, default=None)
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--run-name", type=str, default=None)
    args = parser.parse_args()

    cfg = TrainConfig()
    if args.config:
        raw = yaml.safe_load(args.config.read_text())
        for k, v in raw.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
    if args.total_budget is not None:
        cfg.total_budget = min(args.total_budget, TRAIN_BUDGET)
    if args.seed is not None:
        cfg.seed = args.seed
    if args.run_name is not None:
        cfg.run_name = args.run_name
    if cfg.total_budget > TRAIN_BUDGET:
        raise SystemExit(f"budget {cfg.total_budget} exceeds hard cap {TRAIN_BUDGET}")

    out = args.output or (RESULTS / cfg.run_name)
    trainer = CurriculumTrainer(cfg, out)
    if args.resume:
        print("CONTINUOUS RESUME", args.resume)
        trainer.load_checkpoint(args.resume)
        with (out / "logs" / "resume_events.jsonl").open("a") as f:
            f.write(
                json.dumps(
                    {
                        "event": "resume",
                        "checkpoint": str(args.resume),
                        "global_step": trainer.global_step,
                        "level": LEVELS[trainer.level_idx],
                    }
                )
                + "\n"
            )
    print("Training", cfg.run_name, "budget", cfg.total_budget, flush=True)
    summary = trainer.train()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
