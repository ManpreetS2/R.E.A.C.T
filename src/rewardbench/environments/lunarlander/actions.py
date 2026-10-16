"""Discrete LunarLander-v3 actions.

Gymnasium's ``LunarLander-v3`` discrete action space is:
0 idle, 1 left orientation engine, 2 main engine, 3 right orientation engine.
"""

from __future__ import annotations

IDLE = 0
LEFT_ENGINE = 1
MAIN_ENGINE = 2
RIGHT_ENGINE = 3

ACTION_NAMES: tuple[str, ...] = (
    "idle",
    "left_engine",
    "main_engine",
    "right_engine",
)

# Discrete-engine fuel costs charged by Gymnasium on each frame.
# Main engine power is 1.0 and each side engine power is 1.0 in discrete mode,
# so the environment subtracts exactly these amounts.
MAIN_ENGINE_FUEL_COST = 0.30
SIDE_ENGINE_FUEL_COST = 0.03

# Box2D step rate used by Gymnasium's LunarLander.
PHYSICS_FPS = 50

N_ACTIONS = 4
N_OBSERVATIONS = 8


def action_name(action: int) -> str:
    if action < 0 or action >= len(ACTION_NAMES):
        raise ValueError(f"action {action} is outside LunarLander's discrete space")
    return ACTION_NAMES[action]


def fuel_cost(action: int) -> float:
    if action == MAIN_ENGINE:
        return MAIN_ENGINE_FUEL_COST
    if action in (LEFT_ENGINE, RIGHT_ENGINE):
        return SIDE_ENGINE_FUEL_COST
    if action == IDLE:
        return 0.0
    raise ValueError(f"action {action} is outside LunarLander's discrete space")
