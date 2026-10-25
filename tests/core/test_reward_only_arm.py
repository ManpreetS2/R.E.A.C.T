"""The reward-only config is matched to the offline v1 pair and runs through the real loop."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rewardbench.config import load_config
from rewardbench.contracts import FeedbackCondition
from rewardbench.core.ids import experiment_id
from rewardbench.run.cli import main

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
REWARD_ONLY = CONFIGS / "apollolander_offline_development_rewardonly.yaml"
NOFEEDBACK = CONFIGS / "apollolander_offline_development_nofeedback.yaml"

MATCHED = (
    "environment_id", "provider", "model_id", "split", "seed", "num_revisions",
    "episodes_per_revision", "history_window", "max_episode_steps", "budget",
    "development_seeds", "held_out_seeds", "model_settings",
)


def test_reward_only_config_matches_no_feedback_except_condition_and_names() -> None:
    reward_only = load_config(REWARD_ONLY)
    baseline = load_config(NOFEEDBACK)
    assert reward_only.feedback_condition is FeedbackCondition.REWARD_ONLY
    for field in MATCHED:
        assert getattr(reward_only, field) == getattr(baseline, field), field
    assert reward_only.metadata["adapter_kwargs"] == baseline.metadata["adapter_kwargs"]
    assert experiment_id(reward_only) != experiment_id(baseline)


@pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")
def test_reward_only_arm_runs_end_to_end_with_prompt_log(tmp_path: Path) -> None:
    database = tmp_path / "reward_only.sqlite"
    prompts = tmp_path / "prompts"
    code = main([
        "--config", str(REWARD_ONLY), "--mode", "mock",
        "--database", str(database), "--prompt-log", str(prompts),
    ])
    assert code == 0
    with sqlite3.connect(database) as connection:
        attempts = connection.execute(
            "SELECT revision_index, valid FROM attempts ORDER BY revision_index"
        ).fetchall()
        rewards = connection.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
    assert [row[0] for row in attempts] == [0, 1] and all(row[1] for row in attempts)
    assert rewards == 2
    first, second = sorted(prompts.glob("revision_*.txt"))
    assert "No earlier controller" in first.read_text()
    revised = second.read_text()
    assert "reward=" in revised
    for hidden in ("success=", "steps=", "metrics="):
        assert hidden not in revised
