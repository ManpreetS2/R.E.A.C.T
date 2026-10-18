"""Optional CPU reinforcement-learning pilot for ApolloLander.

This package is state-observation RL (not visual / pixel learning). Training
may use the verified Python physics port; final evaluation and footage must
use the original Node ``ApolloLanderAdapter`` path.
"""

from __future__ import annotations

__all__ = [
    "ACTION_REPEAT",
    "OBSERVATION_KIND",
    "ApolloLanderPythonEnv",
    "ActorCritic",
    "PPOConfig",
    "PPOTrainer",
]

OBSERVATION_KIND = "state-observation RL pilot, not visual learning"
ACTION_REPEAT = 1  # documented default; overridden by config when > 1

from rewardbench.rl.env import ApolloLanderPythonEnv  # noqa: E402
from rewardbench.rl.policy import ActorCritic  # noqa: E402
from rewardbench.rl.ppo import PPOConfig, PPOTrainer  # noqa: E402
