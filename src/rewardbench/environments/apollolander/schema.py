"""Bounded ApolloLander controller data.

Controllers are numbers. Nothing here evaluates JavaScript or Python supplied
by a model. The guidance numbers below are a hand-specified demonstration,
not the output of a language model.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

SCHEMA_ID = "rewardbench.apollolander.controller.v1"
POLICIES = ("guidance", "constant", "random")
MAX_CONTROLLER_SEED = 2**32 - 1

GUIDANCE_BOUNDS: dict[str, tuple[float, float]] = {
    "vx_gain": (0.0, 0.02),
    "vx_limit": (0.01, 0.5),
    "rotation_gain": (0.0, 800.0),
    "aligned_rotation_gain": (0.0, 800.0),
    "aligned_rotation_limit": (0.0, 90.0),
    "cruise_rotation_limit": (0.0, 90.0),
    "aligned_dx": (0.0, 200.0),
    "aligned_vx": (0.0, 0.5),
    "descent_aligned": (0.0, 0.3),
    "descent_cruise": (0.0, 0.3),
    "descent_mid": (0.0, 0.3),
    "descent_low": (0.0, 0.2),
    "altitude_mid": (10.0, 400.0),
    "altitude_low": (1.0, 200.0),
    "altitude_upright": (1.0, 200.0),
    "hover_thrust": (0.0, 1.0),
    "vy_gain": (0.0, 40.0),
    "brake_thrust": (0.0, 10.0),
}

# Tuned by hand against the fixed map. Reported flights must keep this label.
DEMONSTRATION_GUIDANCE: dict[str, float] = {
    "vx_gain": 0.0025,
    "vx_limit": 0.18,
    "rotation_gain": 260.0,
    "aligned_rotation_gain": 400.0,
    "aligned_rotation_limit": 20.0,
    "cruise_rotation_limit": 60.0,
    "aligned_dx": 50.0,
    "aligned_vx": 0.03,
    "descent_aligned": 0.14,
    "descent_cruise": 0.06,
    "descent_mid": 0.06,
    "descent_low": 0.04,
    "altitude_mid": 80.0,
    "altitude_low": 30.0,
    "altitude_upright": 40.0,
    "hover_thrust": 0.333,
    "vy_gain": 9.0,
    "brake_thrust": 1.3,
}


# Prompt format illustration (see "instance" in the schema document). Deliberately a neutral open-loop
# constant, not the tuned guidance demonstration, so the prompt does not seed the experiment.
EXAMPLE_CONTROLLER: dict[str, Any] = {
    "schema": SCHEMA_ID,
    "policy": "constant",
    "thrust": 0.5,
    "rotation": 0,
}


class ControllerRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ControllerStatus:
    valid: bool
    reason: str | None
    policy: str | None


def controller_schema_document() -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "commands": {
            "thrust": {"minimum": 0, "maximum": 1},
            "rotation": {"minimum": -90, "maximum": 90, "step": 10},
        },
        "policies": {
            "guidance": {
                "parameters": {
                    name: {"minimum": low, "maximum": high}
                    for name, (low, high) in GUIDANCE_BOUNDS.items()
                }
            },
            "constant": {"thrust": [0, 1], "rotation": [-90, 90]},
            "random": {
                "seed": [0, MAX_CONTROLLER_SEED],
                "note": "Deterministic open-loop baseline; mixes controller seed with episode seed and step.",
            },
        },
        "rejected": ["JavaScript", "unknown fields", "non-finite numbers", "values outside bounds"],
        "note": "The reference Gymnasium heuristic is not used here. demonstration_guidance_controller is hand-specified. random is a scripted baseline, not learning.",
        "instance": {
            "required_fields": ["schema", "policy"],
            "policy_fields": {
                "guidance": (
                    'requires "parameters": an object holding every guidance parameter named in the schema, '
                    "each a number within its bounds"
                ),
                "constant": (
                    'requires "thrust" (number from 0 to 1) and "rotation" '
                    "(integer multiple of 10 from -90 to 90)"
                ),
                "random": 'requires "seed" (integer from 0 to 4294967295)',
            },
            "example": dict(EXAMPLE_CONTROLLER),
            "example_note": (
                "Format illustration only. It is not a recommended, tuned, or good controller; "
                "choose your own values."
            ),
        },
    }


def demonstration_guidance_controller() -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "policy": "guidance",
        "parameters": dict(DEMONSTRATION_GUIDANCE),
    }


def constant_controller(thrust: float, rotation: int) -> dict[str, Any]:
    return {
        "schema": SCHEMA_ID,
        "policy": "constant",
        "thrust": thrust,
        "rotation": rotation,
    }


def random_controller(seed: int = 0) -> dict[str, Any]:
    """Seeded random-policy baseline. Not a learning model.

    The controller seed is mixed with the episode seed and physics step so the
    same (controller, episode) pair always produces the same action sequence.
    """
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("random controller seed must be an integer")
    if seed < 0 or seed > MAX_CONTROLLER_SEED:
        raise ValueError(f"random controller seed must be between 0 and {MAX_CONTROLLER_SEED}")
    return {"schema": SCHEMA_ID, "policy": "random", "seed": seed}


def validate_controller(payload: Mapping[str, Any] | str) -> ControllerStatus:
    try:
        normalized = normalize_controller(payload)
    except ControllerRejected as exc:
        return ControllerStatus(False, exc.reason, None)
    return ControllerStatus(True, None, normalized["policy"])


def normalize_controller(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ControllerRejected(f"controller is not valid JSON: {exc.msg}") from exc
    elif isinstance(payload, Mapping):
        parsed = dict(payload)
    else:
        raise ControllerRejected("controller must be a JSON object")
    if not isinstance(parsed, dict):
        raise ControllerRejected("controller JSON must be an object")
    _reject_forbidden(parsed)
    if parsed.get("schema") != SCHEMA_ID:
        raise ControllerRejected(f"unsupported controller schema {parsed.get('schema')!r}")
    policy = parsed.get("policy")
    allowed = ", ".join(POLICIES)
    if policy is None:
        hint = " (this looks like the schema document, not a controller instance)" if "policies" in parsed else ""
        raise ControllerRejected(
            f"controller is missing the required 'policy' field{hint}; allowed policies: {allowed}"
        )
    if policy not in POLICIES:
        raise ControllerRejected(f"unknown controller policy {policy!r}; allowed policies: {allowed}")
    if policy == "guidance":
        return {"policy": "guidance", "parameters": _guidance_parameters(parsed.get("parameters"))}
    if policy == "random":
        return {"policy": "random", "seed": _controller_seed(parsed.get("seed"))}
    return {"policy": "constant", "thrust": _thrust(parsed.get("thrust")), "rotation": _rotation(parsed.get("rotation"))}


def guidance_action(observation: Mapping[str, float], parameters: Mapping[str, float]) -> dict[str, float | int]:
    desired_vx = _clamp(observation["dx"] * parameters["vx_gain"], -parameters["vx_limit"], parameters["vx_limit"])
    vx_error = observation["vx"] - desired_vx
    aligned = abs(observation["dx"]) < parameters["aligned_dx"] and abs(observation["vx"]) < parameters["aligned_vx"]
    if aligned:
        rotation = _clamp(-vx_error * parameters["aligned_rotation_gain"], -parameters["aligned_rotation_limit"], parameters["aligned_rotation_limit"])
    else:
        rotation = _clamp(-vx_error * parameters["rotation_gain"], -parameters["cruise_rotation_limit"], parameters["cruise_rotation_limit"])
    if observation["altitude"] < parameters["altitude_upright"] and aligned:
        rotation = 0.0
    if aligned:
        desired_vy = parameters["descent_aligned"]
    else:
        desired_vy = parameters["descent_cruise"]
    if observation["altitude"] < parameters["altitude_mid"]:
        desired_vy = parameters["descent_mid"]
    if observation["altitude"] < parameters["altitude_low"]:
        desired_vy = parameters["descent_low"]
    vy_error = observation["vy"] - desired_vy
    thrust = parameters["hover_thrust"] + vy_error * parameters["vy_gain"]
    if not aligned:
        thrust += abs(vx_error) * parameters["brake_thrust"]
    thrust = _clamp(thrust, 0.0, 1.0)
    snapped = int(round(_clamp(rotation, -90.0, 90.0) / 10.0) * 10)
    return {"thrust": thrust, "rotation": snapped}


def constant_action(controller: Mapping[str, Any]) -> dict[str, float | int]:
    return {"thrust": float(controller["thrust"]), "rotation": int(controller["rotation"])}


def random_action(
    observation: Mapping[str, float],
    *,
    controller_seed: int,
    episode_seed: int,
) -> dict[str, float | int]:
    """Deterministic pseudo-random thrust/rotation for baseline comparison."""
    step = int(observation.get("step", 0))
    digest = hashlib.sha256(
        f"apollolander.random.v1:{controller_seed}:{episode_seed}:{step}".encode("utf-8")
    ).digest()
    thrust = int.from_bytes(digest[0:2], "big") / 65535.0
    rotation = ((int.from_bytes(digest[2:4], "big") % 19) - 9) * 10
    return {"thrust": float(thrust), "rotation": int(rotation)}


def _controller_seed(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ControllerRejected("random seed must be an integer")
    if value < 0 or value > MAX_CONTROLLER_SEED:
        raise ControllerRejected(f"random seed must be between 0 and {MAX_CONTROLLER_SEED}")
    return value


def _guidance_parameters(parameters: Any) -> dict[str, float]:
    if not isinstance(parameters, Mapping):
        raise ControllerRejected("guidance parameters must be an object")
    extra = sorted(set(parameters) - set(GUIDANCE_BOUNDS))
    if extra:
        raise ControllerRejected(f"unknown guidance parameter {extra[0]!r}")
    missing = sorted(set(GUIDANCE_BOUNDS) - set(parameters))
    if missing:
        raise ControllerRejected(f"missing guidance parameter {missing[0]!r}")
    parsed: dict[str, float] = {}
    for name, (low, high) in GUIDANCE_BOUNDS.items():
        number = _finite(parameters[name], name)
        if number < low or number > high:
            raise ControllerRejected(f"{name} must be between {low} and {high}")
        parsed[name] = number
    return parsed


def _thrust(value: Any) -> float:
    number = _finite(value, "thrust")
    if number < 0 or number > 1:
        raise ControllerRejected("thrust must be between 0 and 1")
    return number


def _rotation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ControllerRejected("rotation must be a number")
    number = float(value)
    if not math.isfinite(number) or number < -90 or number > 90:
        raise ControllerRejected("rotation must be between -90 and 90")
    if abs(number / 10 - round(number / 10)) > 1e-9:
        raise ControllerRejected("rotation must be a multiple of 10 degrees")
    return int(round(number))


def _finite(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControllerRejected(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ControllerRejected(f"{field} must be a finite number")
    return number


def _reject_forbidden(value: Any, depth: int = 0) -> None:
    if depth > 6:
        raise ControllerRejected("controller payload is nested too deeply")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ControllerRejected("controller keys must be strings")
            lowered = key.lower()
            if key.startswith("_") or lowered in {"code", "js", "javascript", "script", "eval", "function", "python"}:
                raise ControllerRejected(f"forbidden controller field {key!r}")
            _reject_forbidden(nested, depth + 1)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden(nested, depth + 1)
    elif isinstance(value, str) and len(value) > 200:
        raise ControllerRejected("controller string is too long")


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value
