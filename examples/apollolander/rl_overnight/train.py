#!/usr/bin/env python3
"""Overnight PPO trainer on the verified upstream ApolloLander backend.

Every policy starts from random weights. Physics/native landing rules never change.
Reward shaping variants are training-signal only; judgment is by native landings.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
import yaml

from rewardbench.rl.env import EnvConfig
from rewardbench.rl.ppo import PPOConfig, PPOTrainer
from rewardbench.rl.upstream_env import VectorApolloLanderUpstreamEnv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RESULTS = HERE / "results"


class OvernightPPOTrainer(PPOTrainer):
    """PPOTrainer bound to upstream-vm envs + richer metadata."""

    def __init__(
        self,
        env_config: EnvConfig,
        ppo_config: PPOConfig,
        output_dir: Path | str,
        reward_mode: str = "research_shaped",
        family: str = "A",
        run_id: str = "",
    ) -> None:
        self.reward_mode = reward_mode
        self.family = family
        self.run_id = run_id or ppo_config.run_name
        # Build parent without its VectorApolloLanderEnv — replace after.
        self.env_config = env_config
        self.cfg = ppo_config
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "checkpoints").mkdir(exist_ok=True)
        (self.output_dir / "logs").mkdir(exist_ok=True)
        (self.output_dir / "optimizer").mkdir(exist_ok=True)

        self._set_seeds(self.cfg.seed)
        torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "1"))))
        self.device = torch.device(self.cfg.device)
        self.env = VectorApolloLanderUpstreamEnv(
            self.cfg.n_envs, env_config, reward_mode=reward_mode
        )
        from rewardbench.rl.policy import ActorCritic

        self.policy = ActorCritic(
            obs_dim=self.env.observation_dim,
            n_actions=self.env.n_actions,
            hidden=self.cfg.hidden,
        ).to(self.device)
        self.optimizer = torch.optim.Adam(
            self.policy.parameters(), lr=self.cfg.learning_rate, eps=1e-5
        )
        self.global_step = 0
        self.global_decisions = 0
        self.update_idx = 0
        self.total_minibatch_grad_steps = 0
        self.total_optimizer_epochs = 0
        self._rng = np.random.default_rng(self.cfg.seed + 17)
        self._train_seeds = np.arange(
            self.cfg.train_seed_start,
            self.cfg.train_seed_start + self.cfg.train_seed_count,
            dtype=np.int64,
        )
        from rewardbench.rl.reserved_seeds import assert_seeds_allowed

        assert_seeds_allowed(self._train_seeds.tolist(), context="overnight.train_seed_pool")
        self._episode_returns = np.zeros(self.cfg.n_envs, dtype=np.float64)
        self._episode_fuel = np.zeros(self.cfg.n_envs, dtype=np.float64)
        self._metrics_path = self.output_dir / "logs" / "learning_curve.csv"
        self._metrics_rows: list[dict[str, Any]] = []
        self._write_run_metadata()

    def _git_sha(self) -> str:
        try:
            return (
                subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
                .decode()
                .strip()
            )
        except Exception:  # noqa: BLE001
            return "unknown"

    def _write_run_metadata(self) -> None:
        upstream_commit = (
            ROOT / "frontend/apollolander/upstream/UPSTREAM_COMMIT.txt"
        ).read_text(encoding="utf-8").strip()
        meta = {
            "run_id": self.run_id,
            "family": self.family,
            "observation_kind": "state-observation RL, not visual learning",
            "observation_disclosure": (
                "numerical state from upstream Lander engine; training reward may include "
                "shaping depending on reward_mode; NOT screenshots"
            ),
            "reward_mode": self.reward_mode,
            "env_config": self.env_config.to_dict(),
            "env_config_hash": self.env_config.config_hash(),
            "ppo_config": self.cfg.to_dict(),
            "physics_backend_train": "upstream_vm_host (unmodified Lander.js/Landscape.js via Node vm)",
            "physics_backend_eval": "upstream_vm_host",
            "simulator_label": "ORIGINAL upstream ApolloLander (Seb Lee-Delisle) via headless vm host",
            "parity_status": "PASS — see docs/rl_overnight/PARITY_REPORT.md",
            "upstream_commit": upstream_commit,
            "source_commit": self._git_sha(),
            "python": sys.version,
            "node": subprocess.check_output(["node", "-v"]).decode().strip(),
            "torch_version": torch.__version__,
            "device": str(self.device),
            "cuda_available": torch.cuda.is_available(),
            "action_repeat": self.env_config.action_repeat,
            "action_mapping": {
                "thrust": "lander.thrust(0..1)",
                "rotation": "lander.setRotation(10°-quantized [-90,90])",
            },
            "reserved_seeds": "2000000..2000015 inclusive (never used)",
            "train_seed_pool": [
                int(self.cfg.train_seed_start),
                int(self.cfg.train_seed_start + self.cfg.train_seed_count - 1),
            ],
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        (self.output_dir / "run_metadata.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )

    def save_checkpoint(self, tag: str) -> Path:
        path = super().save_checkpoint(tag)
        # Also dump SHA256 and a separate optimizer snapshot path.
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        meta = {
            "tag": tag,
            "path": str(path),
            "sha256": digest,
            "global_step": self.global_step,
            "physics_frames": self.global_step,
            "policy_decisions": self.global_decisions,
            "update_idx": self.update_idx,
            "reward_mode": self.reward_mode,
            "family": self.family,
            "backend": "upstream_vm_host",
        }
        (self.output_dir / "checkpoints" / f"{tag}.sha256.json").write_text(
            json.dumps(meta, indent=2) + "\n", encoding="utf-8"
        )
        return path

    def train(self) -> dict[str, Any]:
        summary = super().train()
        summary["reward_mode"] = self.reward_mode
        summary["family"] = self.family
        summary["run_id"] = self.run_id
        summary["physics_frames"] = self.global_step
        summary["policy_decisions"] = self.global_decisions
        summary["action_repeat"] = self.env_config.action_repeat
        summary["simulator_label"] = (
            "ORIGINAL upstream ApolloLander via headless Node vm host"
        )
        summary["parity_status"] = "PASS"
        (self.output_dir / "logs" / "train_summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        self.env.close()
        return summary


def load_config(path: Path) -> tuple[EnvConfig, PPOConfig, dict]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    env_raw = dict(raw["env"])
    for key in ("action_space", "physics_backend_train", "physics_backend_eval", "reward_mode"):
        env_raw.pop(key, None)
    env_cfg = EnvConfig(
        max_steps=int(env_raw["max_steps"]),
        research_mode=bool(env_raw["research_mode"]),
        start_schedule_version=str(env_raw["start_schedule_version"]),
        vary_fuel=bool(env_raw["vary_fuel"]),
        action_repeat=int(env_raw["action_repeat"]),
        bonuses=bool(env_raw["bonuses"]),
        locked_camera=bool(env_raw["locked_camera"]),
        observation_kind=str(
            raw.get("observation_kind", "state-observation RL, not visual learning")
        ),
        physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
    )
    ppo_raw = dict(raw["ppo"])
    ppo_cfg = PPOConfig(**{k: ppo_raw[k] for k in PPOConfig.__dataclass_fields__ if k in ppo_raw})
    return env_cfg, ppo_cfg, raw


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--total-env-steps", type=int, default=None)
    parser.add_argument("--run-name", type=str, default=None)
    parser.add_argument("--resume", type=Path, default=None)
    args = parser.parse_args()

    env_cfg, ppo_cfg, raw = load_config(args.config)
    if args.total_env_steps is not None:
        ppo_cfg.total_env_steps = args.total_env_steps
    if args.run_name is not None:
        ppo_cfg.run_name = args.run_name
    reward_mode = str(raw.get("reward_mode", raw.get("env", {}).get("reward_mode", "research_shaped")))
    family = str(raw.get("family", "A"))
    out = args.output or (RESULTS / ppo_cfg.run_name)
    out.mkdir(parents=True, exist_ok=True)
    (out / "config_snapshot.yaml").write_text(args.config.read_text(encoding="utf-8"), encoding="utf-8")

    # Freeze config hash before step 0.
    print("run:", ppo_cfg.run_name, "family:", family, "reward_mode:", reward_mode)
    print("backend: ORIGINAL upstream via Node vm host")
    print("env_config_hash:", env_cfg.config_hash())
    print("output:", out)
    trainer = OvernightPPOTrainer(env_cfg, ppo_cfg, out, reward_mode=reward_mode, family=family)
    if args.resume is not None:
        print("resuming from", args.resume)
        trainer.load_checkpoint(args.resume)
    summary = trainer.train()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
