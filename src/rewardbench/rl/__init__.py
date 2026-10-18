"""Optional CPU reinforcement-learning pilot for ApolloLander.

State-observation RL (numerical state vectors + shaped rewards; NOT screenshots).
Training may use the Python port of the custom Node simulator
(``frontend/apollolander/experiment/physics.js``); final evaluation and footage
must use the Node ``ApolloLanderAdapter`` path. Port equivalence is port-vs-Node
only, not upstream browser-game parity.
"""

from __future__ import annotations

__all__ = [
    "ACTION_REPEAT",
    "OBSERVATION_KIND",
    "SIMULATOR_LABEL",
    "RESERVED_SEEDS",
    "ApolloLanderPythonEnv",
    "ActorCritic",
    "PPOConfig",
    "PPOTrainer",
]

OBSERVATION_KIND = "state-observation RL pilot, not visual learning"
SIMULATOR_LABEL = (
    "custom Node ApolloLander simulator (frontend/apollolander/experiment/physics.js)"
)
ACTION_REPEAT = 1  # documented default; overridden by config when > 1

from rewardbench.rl.env import ApolloLanderPythonEnv  # noqa: E402
from rewardbench.rl.policy import ActorCritic  # noqa: E402
from rewardbench.rl.ppo import PPOConfig, PPOTrainer  # noqa: E402
from rewardbench.rl.reserved_seeds import RESERVED_SEEDS  # noqa: E402
