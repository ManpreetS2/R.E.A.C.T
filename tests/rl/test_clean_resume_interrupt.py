"""Forced interrupt + resume must keep learning-curve rows and first landings."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "examples" / "apollolander" / "rl_clean_v4"))

from rewardbench.rl.continuous_policy import ContinuousThrustActorCritic  # noqa: E402
from rewardbench.rl.train_integrity import count_learning_curve_rows  # noqa: E402

# Import after path setup
from train_clean_l0 import CleanConfig, CleanL0Trainer  # noqa: E402


def test_forced_interrupt_resume_preserves_metrics(tmp_path: Path, monkeypatch) -> None:
    """Simulate kill after first landing, then resume from checkpoint."""
    # Avoid spinning real upstream envs during construct: patch Vector env.
    class _DummyVec:
        def __init__(self, *a, **k):
            self.envs = []

        def close(self):
            return None

        def reset(self, seeds):
            import numpy as np

            n = len(seeds)
            obs = np.zeros((n, 10), dtype=np.float32)
            infos = [{"start": {"rotation": 0.0}} for _ in range(n)]
            return obs, infos

    monkeypatch.setattr("train_clean_l0.VectorApolloLanderUpstreamEnv", _DummyVec)

    out = tmp_path / "CLEAN_interrupt"
    cfg = CleanConfig(
        run_name="CLEAN_interrupt",
        total_budget=1024,
        n_envs=2,
        val_episodes=2,
        diagnostic_hard_cap=400_000,
    )
    trainer = CleanL0Trainer(cfg, out)

    # Pre-interrupt artifacts (as if training wrote them then died).
    logs = out / "logs"
    with (logs / "learning_curve.csv").open("w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "global_step",
                "level",
                "level_idx",
                "return",
                "status",
                "landed",
                "perfect",
                "hard",
                "crashed",
                "timed_out",
                "fuel_used",
                "steps",
            ],
        )
        w.writeheader()
        w.writerow(
            {
                "global_step": "512",
                "level": cfg.level,
                "level_idx": "0",
                "return": "5.0",
                "status": "landed",
                "landed": "True",
                "perfect": "True",
                "hard": "False",
                "crashed": "False",
                "timed_out": "False",
                "fuel_used": "1.0",
                "steps": "100",
            }
        )
        w.writerow(
            {
                "global_step": "800",
                "level": cfg.level,
                "level_idx": "0",
                "return": "-2.0",
                "status": "crashed",
                "landed": "False",
                "perfect": "False",
                "hard": "False",
                "crashed": "True",
                "timed_out": "False",
                "fuel_used": "2.0",
                "steps": "50",
            }
        )
    with (logs / "first_landings.jsonl").open("w") as f:
        f.write(
            json.dumps(
                {
                    "event": "first_train_landing",
                    "level": cfg.level,
                    "frames": 512,
                    "status": "landed",
                }
            )
            + "\n"
        )

    ckpt = out / "checkpoints" / "interrupt_512.pt"
    torch.save(
        {
            "policy": trainer.policy.state_dict(),
            "optimizer": trainer.optimizer.state_dict(),
            "global_step": 512,
            "global_decisions": 512,
            "update_idx": 1,
            "level_idx": 0,
            "level": cfg.level,
            "cfg": cfg.__dict__,
            "rng_state": trainer._rng.bit_generator.state,
        },
        ckpt,
    )

    # Fresh trainer "process" resume.
    trainer2 = CleanL0Trainer(cfg, out)
    assert trainer2._first_landing_frames[cfg.level] is None  # reset on new process
    pre_rows = count_learning_curve_rows(logs / "learning_curve.csv")
    assert pre_rows == 2

    trainer2.load_checkpoint(ckpt)
    assert trainer2.global_step == 512
    assert trainer2._first_landing_frames[cfg.level] == 512
    assert trainer2._resume_preserved["learning_curve_rows_preserved"] == 2
    # CSV must still have both pre-interrupt rows (not truncated).
    assert count_learning_curve_rows(logs / "learning_curve.csv") == 2
    with (logs / "learning_curve.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows[0]["landed"] == "True"
    assert rows[0]["global_step"] == "512"
