"""Bounded ApolloLander controller data.

Controllers are numbers. Nothing here evaluates JavaScript or Python supplied
by a model. The guidance numbers below are a hand-specified demonstration,
not the output of a language model.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
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


# What each guidance parameter does, for the model prompt. Qualitative only: no tuned values (Mission 008
# showed a supplied numeric example is copied verbatim, so the prompt carries no complete controller).
GUIDANCE_PARAMETER_GUIDE: dict[str, str] = {
    "vx_gain": "desired horizontal speed per unit of dx; higher approaches the pad faster from far away",
    "vx_limit": "largest desired horizontal speed toward the pad",
    "rotation_gain": "tilt per unit of horizontal-speed error when not aligned; higher corrects faster but can overshoot",
    "aligned_rotation_gain": "tilt per unit of horizontal-speed error when aligned",
    "aligned_rotation_limit": "largest tilt (degrees) allowed when aligned",
    "cruise_rotation_limit": "largest tilt (degrees) allowed when not aligned; big tilts brake harder but lift less",
    "aligned_dx": "aligned requires |dx| below this distance",
    "aligned_vx": "aligned requires |vx| below this speed",
    "descent_aligned": "target downward speed while aligned (above altitude_mid)",
    "descent_cruise": "target downward speed while not aligned (above altitude_mid)",
    "descent_mid": "target downward speed below altitude_mid",
    "descent_low": "target downward speed below altitude_low, i.e. the speed the ship is steered to at touchdown",
    "altitude_mid": "altitude where descent_mid takes over",
    "altitude_low": "altitude where descent_low takes over (it overrides descent_mid)",
    "altitude_upright": "below this altitude, while aligned, rotation is forced to 0 (upright)",
    "hover_thrust": "baseline thrust before corrections; about 1/3 cancels gravity when upright",
    "vy_gain": "thrust added per unit that vy exceeds the target descent speed; higher holds the target more tightly",
    "brake_thrust": "extra thrust per unit of |vx error| when not aligned",
}

GUIDANCE_LAW = (
    "How the guidance policy acts. Every step it reads the latest observation and computes, in order:",
    "1. desired_vx = clamp(dx * vx_gain, -vx_limit, vx_limit); vx_error = vx - desired_vx.",
    "2. aligned = |dx| < aligned_dx and |vx| < aligned_vx.",
    "3. rotation = clamp(-vx_error * aligned_rotation_gain, +-aligned_rotation_limit) when aligned, otherwise "
    "clamp(-vx_error * rotation_gain, +-cruise_rotation_limit); forced to 0 when aligned and altitude < "
    "altitude_upright; then rounded to the nearest 10 degrees.",
    "4. target_vy = descent_aligned when aligned, otherwise descent_cruise; replaced by descent_mid when altitude "
    "< altitude_mid, then by descent_low when altitude < altitude_low.",
    "5. thrust = hover_thrust + (vy - target_vy) * vy_gain, plus |vx_error| * brake_thrust when not aligned; "
    "clamped to 0..1.",
)

# Constants mirrored from frontend/apollolander/experiment/physics.js (checked by a test).
MECHANICS_CONSTANTS = {
    "gravity": 0.0005,
    "thrustAcceleration": 0.0015,
    "drag": 0.9997,
    "rotationLerp": 0.3,
    "thrustLerp": 0.2,
    "fuelPerStep": 0.2,
    "safeVerticalSpeed": 0.15,
    "perfectVerticalSpeed": 0.075,
}


def flight_mechanics(*, max_steps: int, start_summary: str) -> tuple[str, ...]:
    """Accurate physics for the prompt. Identical for every feedback condition; no tuned numbers."""

    c = MECHANICS_CONSTANTS
    return (
        f"Time: one step is 1/60 s. An episode ends at touchdown, at a crash, or after {max_steps} steps (timeout).",
        "Coordinates: x grows to the right and y grows DOWNWARD. vx > 0 is moving right. vy > 0 is moving down "
        "(descending); vy < 0 is climbing.",
        "Observations the controller uses: dx = pad center x minus ship x (dx > 0: the pad is to the right), "
        "vx, vy, and altitude = height of the ship's base above the terrain directly below it.",
        f"Gravity adds {c['gravity']} to vy every step.",
        f"Thrust: the engine accelerates the ship by {c['thrustAcceleration']} x engine level per step along the "
        f"ship's axis. The engine level moves {round(c['thrustLerp'] * 100)}% of the way to the commanded thrust "
        "each step, so thrust changes lag. Upright, thrust of about 1/3 cancels gravity; more slows a descent "
        "or climbs, less falls faster.",
        f"Rotation: the ship turns {round(c['rotationLerp'] * 100)}% of the remaining way to the commanded angle "
        "each step. 0 is upright and thrusts straight up. Positive rotation tilts the thrust to push the ship "
        "right (+x); negative pushes it left. Tilting also reduces the upward part of the thrust.",
        f"Braking: horizontal drag is tiny (vx is multiplied by {c['drag']} each step), so horizontal speed is "
        "removed only by tilted thrust.",
        f"Fuel: the engine burns {c['fuelPerStep']} x engine level fuel per step; with no fuel it stops.",
        start_summary,
        "Success: the ship must touch the designated pad with its whole base on the pad, rotation exactly 0, and "
        f"downward speed vy below {c['safeVerticalSpeed']} at contact; below {c['perfectVerticalSpeed']} is a "
        "gentle landing. Touching the pad tilted or faster, or touching any slope, is a crash. Settling on flat "
        "ground that is not the pad is not a success. No touchdown before the step limit is a timeout.",
        "Score (the environment's own): rewards getting closer to the pad and staying upright, charges for fuel "
        "burned, and ranks outcomes: gentle pad landing best, then hard pad landing, then settling off the pad, "
        "then timeout; a crash is worst.",
    )


def resolve_policies(policies: Sequence[str] | None) -> tuple[str, ...]:
    """Canonical, ordered policy subset; ``None`` means every policy."""

    if policies is None:
        return POLICIES
    chosen = tuple(policies)
    if not chosen or any(p not in POLICIES for p in chosen) or len(set(chosen)) != len(chosen):
        raise ValueError(f"allowed_policies must be distinct values from {POLICIES}")
    return tuple(p for p in POLICIES if p in chosen)


class ControllerRejected(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ControllerStatus:
    valid: bool
    reason: str | None
    policy: str | None


_POLICY_SCHEMAS: dict[str, dict[str, Any]] = {
    "guidance": {
        "parameters": {name: {"minimum": low, "maximum": high} for name, (low, high) in GUIDANCE_BOUNDS.items()}
    },
    "constant": {"thrust": [0, 1], "rotation": [-90, 90]},
    "random": {
        "seed": [0, MAX_CONTROLLER_SEED],
        "note": "Deterministic open-loop baseline; mixes controller seed with episode seed and step.",
    },
}
_POLICY_FIELDS = {
    "guidance": (
        'requires "parameters": an object holding every guidance parameter named in the schema, '
        "each a concrete number within its bounds"
    ),
    "constant": 'requires "thrust" (number from 0 to 1) and "rotation" (integer multiple of 10 from -90 to 90)',
    "random": 'requires "seed" (integer from 0 to 4294967295)',
}
_OBJECTIVE = (
    "Design ONE controller that lands the ship gently and upright on the designated pad from every start in "
    "this experiment, without crashing or timing out, using little fuel. The same controller flies every start "
    "unchanged and keeps adjusting thrust and rotation from each new observation."
)
_DEFAULT_START_SUMMARY = "Starts: every episode uses the same fixed start."


def controller_schema_document(
    allowed_policies: Sequence[str] | None = None,
    *,
    max_steps: int = 8000,
    start_summary: str = _DEFAULT_START_SUMMARY,
) -> dict[str, Any]:
    policies = resolve_policies(allowed_policies)
    instance: dict[str, Any] = {
        "objective": _OBJECTIVE,
        "mechanics": list(flight_mechanics(max_steps=max_steps, start_summary=start_summary)),
        "required_fields": ["schema", "policy"],
        "policy_fields": {name: _POLICY_FIELDS[name] for name in policies},
    }
    if "guidance" in policies:
        instance["guidance_law"] = list(GUIDANCE_LAW)
        instance["parameter_guide"] = dict(GUIDANCE_PARAMETER_GUIDE)
        # A shape with placeholders, deliberately not valid JSON, so nothing in the prompt is a copyable controller.
        instance["shape"] = (
            '{"schema":"' + SCHEMA_ID + '","policy":"guidance","parameters":{'
            + ",".join(f'"{name}":<number>' for name in GUIDANCE_BOUNDS) + "}}"
        )
    return {
        "schema": SCHEMA_ID,
        "commands": {
            "thrust": {"minimum": 0, "maximum": 1},
            "rotation": {"minimum": -90, "maximum": 90, "step": 10},
        },
        "policies": {name: _POLICY_SCHEMAS[name] for name in policies},
        "rejected": ["JavaScript", "unknown fields", "missing fields", "non-finite numbers", "values outside bounds"]
        + ([] if policies == POLICIES else ["policies not listed here"]),
        "note": "The reference Gymnasium heuristic is not used here. Missing or out-of-range values are rejected, never filled in.",
        "instance": instance,
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


def validate_controller(
    payload: Mapping[str, Any] | str,
    allowed_policies: Sequence[str] | None = None,
) -> ControllerStatus:
    try:
        normalized = normalize_controller(payload, allowed_policies)
    except ControllerRejected as exc:
        return ControllerStatus(False, exc.reason, None)
    return ControllerStatus(True, None, normalized["policy"])


def normalize_controller(
    payload: Mapping[str, Any] | str,
    allowed_policies: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Validate and normalize; never fills in, repairs or substitutes a value."""

    permitted = resolve_policies(allowed_policies)
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
    policy = parsed.get("policy")
    allowed = ", ".join(permitted)
    if policy is None and "policies" in parsed:
        # Checked first so an echoed schema (whose long notes fail the checks below) gets the useful message.
        raise ControllerRejected(
            "controller is missing the required 'policy' field (this looks like the schema document, not a "
            f"controller instance); allowed policies: {allowed}"
        )
    _reject_forbidden(parsed)
    if parsed.get("schema") != SCHEMA_ID:
        raise ControllerRejected(f"unsupported controller schema {parsed.get('schema')!r}")
    if policy is None:
        raise ControllerRejected(f"controller is missing the required 'policy' field; allowed policies: {allowed}")
    if policy not in POLICIES:
        raise ControllerRejected(f"unknown controller policy {policy!r}; allowed policies: {allowed}")
    if policy not in permitted:
        raise ControllerRejected(
            f"controller policy {policy!r} is not allowed in this experiment; allowed policies: {allowed}"
        )
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
