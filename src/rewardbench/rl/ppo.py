"""CPU-only PyTorch PPO trainer for the ApolloLander RL pilot."""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch

from rewardbench.rl.env import EnvConfig, VectorApolloLanderEnv
from rewardbench.rl.policy import ActorCritic


@dataclass
class PPOConfig:
    total_env_steps: int = 2_000_000
    n_envs: int = 8
    rollout_steps: int = 256
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_coef: float = 0.2
    ent_coef: float = 0.01
    vf_coef: float = 0.5
    max_grad_norm: float = 0.5
    update_epochs: int = 4
    minibatch_size: int = 512
    hidden: int = 128
    seed: int = 0
    checkpoint_every_steps: int = 200_000
    device: str = "cpu"
    # Training seed pool: development only. Eval seeds are reserved separately.
    train_seed_start: int = 10_000
    train_seed_count: int = 200_000
    run_name: str = "ppo_pilot"
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RolloutBuffer:
    obs: np.ndarray
    actions: np.ndarray
    log_probs: np.ndarray
    rewards: np.ndarray
    dones: np.ndarray
    values: np.ndarray
    advantages: np.ndarray = field(init=False)
    returns: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.advantages = np.zeros_like(self.rewards, dtype=np.float64)
        self.returns = np.zeros_like(self.rewards, dtype=np.float64)


class PPOTrainer:
    def __init__(
        self,
        env_config: EnvConfig,
        ppo_config: PPOConfig,
        output_dir: Path | str,
    ) -> None:
        self.env_config = env_config
        self.cfg = ppo_config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "checkpoints").mkdir(exist_ok=True)
        (self.output_dir / "logs").mkdir(exist_ok=True)

        self._set_seeds(self.cfg.seed)
        self.device = torch.device(self.cfg.device)
        self.env = VectorApolloLanderEnv(self.cfg.n_envs, env_config)
        self.policy = ActorCritic(
            obs_dim=self.env.observation_dim,
            n_actions=self.env.n_actions,
            hidden=self.cfg.hidden,
        ).to(self.device)
        self.optimizer = torch.optim.Adam(self.policy.parameters(), lr=self.cfg.learning_rate, eps=1e-5)

        self.global_step = 0
        self.update_idx = 0
        self._rng = np.random.default_rng(self.cfg.seed + 17)
        self._train_seeds = np.arange(
            self.cfg.train_seed_start,
            self.cfg.train_seed_start + self.cfg.train_seed_count,
            dtype=np.int64,
        )
        if self._train_seeds.max() >= 1_000_000:
            raise ValueError("training seeds must stay in the development pool (< 1_000_000)")

        self._episode_returns = np.zeros(self.cfg.n_envs, dtype=np.float64)
        self._episode_fuel = np.zeros(self.cfg.n_envs, dtype=np.float64)
        self._metrics_path = self.output_dir / "logs" / "learning_curve.csv"
        self._metrics_rows: list[dict[str, Any]] = []
        self._write_run_metadata()

    def _set_seeds(self, seed: int) -> None:
        np.random.seed(seed)
        torch.manual_seed(seed)

    def _write_run_metadata(self) -> None:
        meta = {
            "observation_kind": self.env_config.observation_kind,
            "env_config": self.env_config.to_dict(),
            "env_config_hash": self.env_config.config_hash(),
            "ppo_config": self.cfg.to_dict(),
            "physics_backend_train": self.env_config.physics_backend,
            "physics_backend_eval": "original Node ApolloLanderAdapter (required)",
            "torch_version": torch.__version__,
            "device": str(self.device),
            "cuda_available": torch.cuda.is_available(),
        }
        path = self.output_dir / "run_metadata.json"
        path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")

    def _sample_train_seeds(self, n: int) -> np.ndarray:
        idx = self._rng.integers(0, len(self._train_seeds), size=n)
        return self._train_seeds[idx]

    def save_checkpoint(self, tag: str) -> Path:
        path = self.output_dir / "checkpoints" / f"{tag}.pt"
        payload = {
            "tag": tag,
            "global_step": self.global_step,
            "update_idx": self.update_idx,
            "policy_state_dict": self.policy.state_dict(),
            "optimizer_state_dict": self.optimizer.state_dict(),
            "env_config": self.env_config.to_dict(),
            "env_config_hash": self.env_config.config_hash(),
            "ppo_config": self.cfg.to_dict(),
            "observation_kind": self.env_config.observation_kind,
            "random_init": tag.endswith("step0") or self.global_step == 0,
        }
        torch.save(payload, path)
        return path

    def load_checkpoint(self, path: Path | str) -> None:
        payload = torch.load(path, map_location=self.device, weights_only=False)
        self.policy.load_state_dict(payload["policy_state_dict"])
        if "optimizer_state_dict" in payload:
            self.optimizer.load_state_dict(payload["optimizer_state_dict"])
        self.global_step = int(payload.get("global_step", 0))
        self.update_idx = int(payload.get("update_idx", 0))

    def _flush_metrics(self) -> None:
        if not self._metrics_rows:
            return
        fieldnames = list(self._metrics_rows[0].keys())
        write_header = not self._metrics_path.exists()
        with self._metrics_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(self._metrics_rows)
        self._metrics_rows.clear()

    def _recent_episode_summary(self) -> dict[str, float | int]:
        if not self._metrics_path.exists():
            return {"episodes": 0, "mean_return": float("nan"), "landing_rate": float("nan")}
        rows: list[dict[str, str]] = []
        with self._metrics_path.open("r", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if not rows:
            return {"episodes": 0, "mean_return": float("nan"), "landing_rate": float("nan")}
        # Use all completed episodes so far (raw rates, not smoothed).
        returns = [float(r["episodic_return"]) for r in rows]
        lands = [float(r["landing_success"]) for r in rows]
        return {
            "episodes": len(rows),
            "mean_return": float(sum(returns) / len(returns)),
            "landing_rate": float(sum(lands) / len(lands)),
            "crash_rate": float(sum(float(r["crash"]) for r in rows) / len(rows)),
            "timeout_rate": float(sum(float(r["timeout"]) for r in rows) / len(rows)),
        }

    def _record_episodes(self, infos: list[dict[str, Any]], dones: np.ndarray) -> None:
        for i, done in enumerate(dones):
            if not done:
                continue
            info = infos[i]
            row = {
                "update": self.update_idx,
                "global_step": self.global_step,
                "episodic_return": float(self._episode_returns[i]),
                "landing_success": 1 if info.get("landed") else 0,
                "crash": 1 if info.get("crashed") else 0,
                "timeout": 1 if info.get("timed_out") else 0,
                "fuel_used": float(info.get("fuel_used", self._episode_fuel[i])),
                "steps": int(info.get("steps", 0)),
                "status": info.get("status", ""),
            }
            self._metrics_rows.append(row)
            self._episode_returns[i] = 0.0
            self._episode_fuel[i] = 0.0

    def collect_rollout(self, obs: np.ndarray) -> tuple[RolloutBuffer, np.ndarray]:
        n_steps = self.cfg.rollout_steps
        n_envs = self.cfg.n_envs
        buf = RolloutBuffer(
            obs=np.zeros((n_steps, n_envs, self.env.observation_dim), dtype=np.float32),
            actions=np.zeros((n_steps, n_envs), dtype=np.int64),
            log_probs=np.zeros((n_steps, n_envs), dtype=np.float64),
            rewards=np.zeros((n_steps, n_envs), dtype=np.float64),
            dones=np.zeros((n_steps, n_envs), dtype=np.float64),
            values=np.zeros((n_steps, n_envs), dtype=np.float64),
        )
        for t in range(n_steps):
            obs_t = torch.as_tensor(obs, dtype=torch.float32, device=self.device)
            with torch.no_grad():
                actions, log_probs, values = self.policy.act(obs_t)
            actions_np = actions.cpu().numpy()
            next_obs, rewards, terminated, truncated, infos = self.env.step(actions_np)
            dones = np.logical_or(terminated, truncated)
            physics_steps = self.env_config.action_repeat * n_envs
            self.global_step += physics_steps

            self._episode_returns += rewards
            for i, info in enumerate(infos):
                self._episode_fuel[i] = float(info.get("fuel_used", self._episode_fuel[i]))

            buf.obs[t] = obs
            buf.actions[t] = actions_np
            buf.log_probs[t] = log_probs.cpu().numpy()
            buf.rewards[t] = rewards
            buf.dones[t] = dones.astype(np.float64)
            buf.values[t] = values.cpu().numpy()

            self._record_episodes(infos, dones)

            # Auto-reset finished envs with fresh development training seeds.
            if np.any(dones):
                reset_seeds = self._sample_train_seeds(int(np.sum(dones)))
                seed_iter = iter(reset_seeds.tolist())
                for i, done in enumerate(dones):
                    if done:
                        o, _ = self.env.envs[i].reset(int(next(seed_iter)))
                        next_obs[i] = o
                        self._episode_returns[i] = 0.0
                        self._episode_fuel[i] = 0.0
            obs = next_obs

        # GAE
        with torch.no_grad():
            last_values = self.policy.forward(torch.as_tensor(obs, dtype=torch.float32, device=self.device))[1]
            last_values_np = last_values.cpu().numpy()
        last_gae = 0.0
        for t in reversed(range(n_steps)):
            if t == n_steps - 1:
                next_non_terminal = 1.0 - buf.dones[t]
                next_values = last_values_np
            else:
                next_non_terminal = 1.0 - buf.dones[t]
                next_values = buf.values[t + 1]
            delta = buf.rewards[t] + self.cfg.gamma * next_values * next_non_terminal - buf.values[t]
            last_gae = delta + self.cfg.gamma * self.cfg.gae_lambda * next_non_terminal * last_gae
            buf.advantages[t] = last_gae
        buf.returns = buf.advantages + buf.values
        return buf, obs

    def update(self, buf: RolloutBuffer) -> dict[str, float]:
        n_steps, n_envs = buf.rewards.shape
        batch_size = n_steps * n_envs
        obs = torch.as_tensor(buf.obs.reshape(batch_size, -1), dtype=torch.float32, device=self.device)
        actions = torch.as_tensor(buf.actions.reshape(batch_size), dtype=torch.int64, device=self.device)
        old_log_probs = torch.as_tensor(buf.log_probs.reshape(batch_size), dtype=torch.float32, device=self.device)
        advantages = torch.as_tensor(buf.advantages.reshape(batch_size), dtype=torch.float32, device=self.device)
        returns = torch.as_tensor(buf.returns.reshape(batch_size), dtype=torch.float32, device=self.device)
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        indices = np.arange(batch_size)
        mb = self.cfg.minibatch_size
        loss_sum = 0.0
        ent_sum = 0.0
        n_mb = 0
        for _ in range(self.cfg.update_epochs):
            self._rng.shuffle(indices)
            for start in range(0, batch_size, mb):
                end = start + mb
                mb_idx = indices[start:end]
                mb_obs = obs[mb_idx]
                mb_actions = actions[mb_idx]
                mb_old_logp = old_log_probs[mb_idx]
                mb_adv = advantages[mb_idx]
                mb_ret = returns[mb_idx]
                new_logp, entropy, values = self.policy.evaluate_actions(mb_obs, mb_actions)
                ratio = torch.exp(new_logp - mb_old_logp)
                pg1 = ratio * mb_adv
                pg2 = torch.clamp(ratio, 1.0 - self.cfg.clip_coef, 1.0 + self.cfg.clip_coef) * mb_adv
                policy_loss = -torch.min(pg1, pg2).mean()
                value_loss = 0.5 * ((values - mb_ret) ** 2).mean()
                entropy_loss = entropy.mean()
                loss = policy_loss + self.cfg.vf_coef * value_loss - self.cfg.ent_coef * entropy_loss
                self.optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.policy.parameters(), self.cfg.max_grad_norm)
                self.optimizer.step()
                loss_sum += float(loss.item())
                ent_sum += float(entropy_loss.item())
                n_mb += 1
        self.update_idx += 1
        return {
            "loss": loss_sum / max(n_mb, 1),
            "entropy": ent_sum / max(n_mb, 1),
        }

    def train(self) -> dict[str, Any]:
        wall_start = time.perf_counter()
        self.save_checkpoint("step0")
        seeds = self._sample_train_seeds(self.cfg.n_envs)
        obs, _ = self.env.reset(seeds)
        next_ckpt = self.cfg.checkpoint_every_steps
        update_stats: list[dict[str, Any]] = []

        while self.global_step < self.cfg.total_env_steps:
            buf, obs = self.collect_rollout(obs)
            stats = self.update(buf)
            self._flush_metrics()
            # Aggregate recently completed episodes from the CSV tail for the console.
            ep_summary = self._recent_episode_summary()
            stats_row = {
                "update": self.update_idx,
                "global_step": self.global_step,
                "loss": stats["loss"],
                "entropy": stats["entropy"],
                "wall_seconds": time.perf_counter() - wall_start,
                **ep_summary,
            }
            update_stats.append(stats_row)
            print(
                f"update={self.update_idx} step={self.global_step} "
                f"loss={stats['loss']:.4f} ent={stats['entropy']:.4f} "
                f"land={ep_summary.get('landing_rate', float('nan')):.3f} "
                f"mean_r={ep_summary.get('mean_return', float('nan')):.2f} "
                f"eps={ep_summary.get('episodes', 0)} "
                f"wall={stats_row['wall_seconds']:.1f}s",
                flush=True,
            )
            while self.global_step >= next_ckpt:
                self.save_checkpoint(f"step{next_ckpt}")
                next_ckpt += self.cfg.checkpoint_every_steps

        self.save_checkpoint("final")
        self._flush_metrics()
        wall = time.perf_counter() - wall_start
        summary = {
            "total_env_steps": self.global_step,
            "updates": self.update_idx,
            "wall_seconds": wall,
            "steps_per_sec_effective": self.global_step / wall if wall > 0 else 0.0,
            "env_config_hash": self.env_config.config_hash(),
        }
        (self.output_dir / "logs" / "train_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        (self.output_dir / "logs" / "update_stats.json").write_text(
            json.dumps(update_stats, indent=2) + "\n", encoding="utf-8"
        )
        return summary
