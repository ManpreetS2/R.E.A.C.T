"""Translate demonstration_guidance absolute commands into the V7 learner space.

Learner space (same as V6 unless feasibility fails):
  - thrust continuous in [0, 1]
  - rotation delta in {-10, 0, +10} degrees
  - action_repeat = 8 (one decision every 8 physics frames)

Expert (guidance) emits absolute rotation snapped to 10° and continuous thrust.
Translation (called once per decision):
  - thrust = expert thrust, held for action_repeat frames
  - delta = sign(expert_abs - current_abs) clipped to a single ±10/0 step
  - applied absolute = clip(current + delta, -90, 90) snapped to 10°
"""

from __future__ import annotations

from typing import Any, Mapping

from rewardbench.environments.apollolander.schema import (
    DEMONSTRATION_GUIDANCE,
    guidance_action,
)

ROTATION_DELTAS = (-10, 0, 10)
ACTION_REPEAT = 8


def snap10(rotation: float) -> int:
    return int(round(float(rotation) / 10.0) * 10)


def clip_rotation(rotation: int) -> int:
    return int(max(-90, min(90, rotation)))


def raw_expert_command(observation: Mapping[str, float]) -> dict[str, float | int]:
    """Absolute expert command (training-only; never call at learner eval)."""
    cmd = guidance_action(observation, DEMONSTRATION_GUIDANCE)
    return {"thrust": float(cmd["thrust"]), "rotation": int(cmd["rotation"])}


def translate_to_learner(
    observation: Mapping[str, float],
    current_abs_rotation: int,
) -> dict[str, Any]:
    """Map one expert call into a learner decision + applied absolute command."""
    raw = raw_expert_command(observation)
    cur = clip_rotation(snap10(current_abs_rotation))
    target = clip_rotation(int(raw["rotation"]))
    diff = target - cur
    if diff > 0:
        delta = 10
    elif diff < 0:
        delta = -10
    else:
        delta = 0
    applied = clip_rotation(cur + delta)
    applied = snap10(applied)
    rot_idx = ROTATION_DELTAS.index(delta)
    return {
        "raw_expert": raw,
        "learner": {
            "thrust": float(raw["thrust"]),
            "rotation_delta": int(delta),
            "rotation_idx": int(rot_idx),
        },
        "applied_absolute": {
            "thrust": float(raw["thrust"]),
            "rotation": int(applied),
        },
        "current_abs_before": cur,
        "target_abs": target,
    }


def obs_dict_from_host(raw: Mapping[str, Any]) -> dict[str, float]:
    """Fields required by guidance_action + logging."""
    return {
        "x": float(raw["x"]),
        "y": float(raw["y"]),
        "vx": float(raw["vx"]),
        "vy": float(raw["vy"]),
        "rotation": float(raw["rotation"]),
        "fuel": float(raw["fuel"]),
        "altitude": float(raw["altitude"]),
        "dx": float(raw["dx"]),
        "dy": float(raw["dy"]),
        "thrust": float(raw.get("thrust", raw.get("thrustBuild", 0.0))),
        "step": float(raw.get("step", 0)),
    }
