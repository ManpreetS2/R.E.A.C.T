"""Parameterized rocket-controller schema.

A controller is JSON data describing a heuristic, a linear map, or a seeded
random policy. Nothing in this module calls ``exec``, ``eval``, or
``compile``, and unknown fields are rejected so generated Python cannot hide
inside the payload.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from rewardbench.environments.lunarlander.actions import N_ACTIONS, N_OBSERVATIONS
from rewardbench.environments.lunarlander.seeds import MAX_SEED

SCHEMA_ID = "rewardbench.lunarlander.controller.v1"
POLICIES: tuple[str, ...] = ("heuristic", "linear", "random")

# Keys that would only be meaningful if we executed caller-supplied code.
FORBIDDEN_KEYS = frozenset(
    {
        "code",
        "python",
        "exec",
        "eval",
        "script",
        "source",
        "command",
        "shell",
        "pickle",
        "lambda",
        "import",
        "__import__",
        "builtins",
        "globals",
        "locals",
        "compile",
        "function",
        "callable",
    }
)

# Inclusive bounds. The published Gymnasium heuristic sits inside this box.
HEURISTIC_BOUNDS: dict[str, tuple[float, float]] = {
    "angle_target_x_gain": (-5.0, 5.0),
    "angle_target_vx_gain": (-5.0, 5.0),
    "angle_target_limit": (0.0, 1.5),
    "hover_x_gain": (0.0, 3.0),
    "angle_error_gain": (-5.0, 5.0),
    "angular_velocity_gain": (-5.0, 5.0),
    "hover_error_gain": (-5.0, 5.0),
    "vertical_velocity_gain": (-5.0, 5.0),
    "main_engine_threshold": (0.0, 1.0),
    "side_engine_threshold": (0.0, 1.0),
    "contact_vertical_velocity_gain": (0.0, 5.0),
}

# Gains from Gymnasium's published discrete heuristic.
REFERENCE_HEURISTIC_PARAMETERS: dict[str, float] = {
    "angle_target_x_gain": 0.5,
    "angle_target_vx_gain": 1.0,
    "angle_target_limit": 0.4,
    "hover_x_gain": 0.55,
    "angle_error_gain": 0.5,
    "angular_velocity_gain": 1.0,
    "hover_error_gain": 0.5,
    "vertical_velocity_gain": 0.5,
    "main_engine_threshold": 0.05,
    "side_engine_threshold": 0.05,
    "contact_vertical_velocity_gain": 0.5,
}

LINEAR_LIMIT = 50.0
DEFAULT_CLIP_OBS = 10.0
MAX_DEPTH = 8
MAX_STRING_LENGTH = 200
MAX_JSON_CHARS = 100_000

_TOP_LEVEL_KEYS = {
    "heuristic": frozenset({"schema", "policy", "parameters"}),
    "linear": frozenset({"schema", "policy", "weights", "bias", "clip_obs"}),
    "random": frozenset({"schema", "policy", "seed"}),
}
_OPTIONAL_KEYS = {"clip_obs"}


class ControllerRejected(ValueError):
    """The payload is not a safe controller. The environment must not be stepped."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class NormalizedController:
    """Validated numeric controller. Contains no executable payload."""

    policy: str
    parameters: tuple[tuple[str, float], ...] | None = None
    weights: tuple[tuple[float, ...], ...] | None = None
    bias: tuple[float, ...] | None = None
    clip_obs: float | None = None
    seed: int | None = None

    def parameter_map(self) -> dict[str, float]:
        return dict(self.parameters or ())


@dataclass(frozen=True)
class ControllerStatus:
    valid: bool
    reason: str | None
    policy: str | None


def controller_schema_document() -> dict[str, Any]:
    """JSON-serializable description of the controller an LLM is allowed to edit."""
    return {
        "schema": SCHEMA_ID,
        "actions": ["idle", "left_engine", "main_engine", "right_engine"],
        "observation": [
            "x",
            "y",
            "vx",
            "vy",
            "angle",
            "angular_velocity",
            "leg1_contact",
            "leg2_contact",
        ],
        "policies": {
            "heuristic": {
                "parameters": {
                    name: {"minimum": low, "maximum": high}
                    for name, (low, high) in HEURISTIC_BOUNDS.items()
                },
                "reference_parameters": dict(REFERENCE_HEURISTIC_PARAMETERS),
            },
            "linear": {
                "weights": {"shape": [N_ACTIONS, N_OBSERVATIONS], "minimum": -LINEAR_LIMIT, "maximum": LINEAR_LIMIT},
                "bias": {"length": N_ACTIONS, "minimum": -LINEAR_LIMIT, "maximum": LINEAR_LIMIT},
                "clip_obs": {"default": DEFAULT_CLIP_OBS, "minimum_exclusive": 0.0, "maximum": 100.0},
                "action_rule": "argmax of clipped_observation · weights[action] + bias[action]; lowest index wins ties",
            },
            "random": {
                "seed": {"minimum": 0, "maximum": MAX_SEED},
                "action_rule": "uniform over the four discrete engines, seeded per episode",
            },
        },
        "rejected": [
            "arbitrary Python",
            "unknown fields",
            "non-finite numbers",
            "values outside the published bounds",
        ],
        "roles": {
            "reference_heuristic": "benchmark only; evaluate() does not substitute it for a missing model proposal",
            "model_revision": "a model submits revision 1, 2, 3, ... as data in this schema",
            "success": "asleep, no hull contact, inside the viewport, and body x between the flag poles",
        },
    }


def reference_controller() -> dict[str, Any]:
    """Deterministic published heuristic, expressed in the safe schema."""
    return {
        "schema": SCHEMA_ID,
        "policy": "heuristic",
        "parameters": dict(REFERENCE_HEURISTIC_PARAMETERS),
    }


def random_controller(seed: int = 0) -> dict[str, Any]:
    """Seeded random-policy baseline. ``seed`` is mixed with each episode seed."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("random controller seed must be an integer")
    if seed < 0 or seed > MAX_SEED:
        raise ValueError(f"random controller seed must be between 0 and {MAX_SEED}")
    return {"schema": SCHEMA_ID, "policy": "random", "seed": seed}


# Zero steering and thresholds at the top of the allowed range. Engines stay off.
IMPERFECT_HEURISTIC_PARAMETERS: dict[str, float] = {
    "angle_target_x_gain": 0.0,
    "angle_target_vx_gain": 0.0,
    "angle_target_limit": 0.4,
    "hover_x_gain": 0.0,
    "angle_error_gain": 0.0,
    "angular_velocity_gain": 0.0,
    "hover_error_gain": 0.0,
    "vertical_velocity_gain": 0.0,
    "main_engine_threshold": 1.0,
    "side_engine_threshold": 1.0,
    "contact_vertical_velocity_gain": 0.0,
}


def imperfect_heuristic_controller() -> dict[str, Any]:
    """A legal but poor starting proposal.

    This is not the reference benchmark and it is not a learned policy.
    Models may replace it with their own revision-1 parameters.
    """
    return {
        "schema": SCHEMA_ID,
        "policy": "heuristic",
        "parameters": dict(IMPERFECT_HEURISTIC_PARAMETERS),
    }


def thrust_biased_controller() -> dict[str, Any]:
    """Hand-specified linear policy that always fires the main engine.

    It exists so a second revision can be scored against a first one.
    It is not the output of a language model.
    """
    return {
        "schema": SCHEMA_ID,
        "policy": "linear",
        "weights": [[0.0] * N_OBSERVATIONS for _ in range(N_ACTIONS)],
        "bias": [0.0, 0.0, 1.0, 0.0],
    }


def idle_controller() -> dict[str, Any]:
    """Linear controller that always selects idle. Useful as a crash baseline."""
    return {
        "schema": SCHEMA_ID,
        "policy": "linear",
        "weights": [[0.0] * N_OBSERVATIONS for _ in range(N_ACTIONS)],
        "bias": [1.0, 0.0, 0.0, 0.0],
    }


def validate_controller(payload: Mapping[str, Any] | str) -> ControllerStatus:
    try:
        normalized = normalize_controller(payload)
    except ControllerRejected as exc:
        return ControllerStatus(valid=False, reason=exc.reason, policy=None)
    return ControllerStatus(valid=True, reason=None, policy=normalized.policy)


def normalize_controller(payload: Mapping[str, Any] | str) -> NormalizedController:
    data = _parse_payload(payload)
    _reject_forbidden(data)
    schema = data.get("schema")
    if schema != SCHEMA_ID:
        raise ControllerRejected(
            f"unsupported controller schema {schema!r}; expected {SCHEMA_ID}"
        )
    policy = data.get("policy")
    if not isinstance(policy, str) or policy not in POLICIES:
        raise ControllerRejected(
            f"unknown controller policy {policy!r}; expected one of {', '.join(POLICIES)}"
        )
    _check_top_level_keys(data, policy)
    if policy == "heuristic":
        return _normalize_heuristic(data["parameters"])
    if policy == "linear":
        return _normalize_linear(data)
    return _normalize_random(data["seed"])


def _parse_payload(payload: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, str):
        if len(payload) > MAX_JSON_CHARS:
            raise ControllerRejected("controller JSON exceeds the size limit")
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ControllerRejected(f"controller is not valid JSON: {exc.msg}") from exc
    elif isinstance(payload, Mapping):
        parsed = dict(payload)
    else:
        raise ControllerRejected(
            f"controller must be a JSON object, got {type(payload).__name__}"
        )
    if not isinstance(parsed, dict):
        raise ControllerRejected("controller JSON must be an object")
    return parsed


def _reject_forbidden(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ControllerRejected("controller payload is nested too deeply")
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ControllerRejected("controller keys must be strings")
            if len(key) > MAX_STRING_LENGTH:
                raise ControllerRejected("controller key is too long")
            if key.startswith("_") or key.lower() in FORBIDDEN_KEYS:
                raise ControllerRejected(f"forbidden controller field {key!r}")
            _reject_forbidden(nested, depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 64:
            raise ControllerRejected("controller list is too long")
        for nested in value:
            _reject_forbidden(nested, depth + 1)
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise ControllerRejected("controller string is too long")
        return
    if value is None or isinstance(value, (int, float)):
        return
    raise ControllerRejected(
        f"controller contains unsupported value type {type(value).__name__}"
    )


def _check_top_level_keys(data: Mapping[str, Any], policy: str) -> None:
    allowed = _TOP_LEVEL_KEYS[policy]
    extra = sorted(set(data) - allowed)
    if extra:
        raise ControllerRejected(f"unknown controller field {extra[0]!r}")
    required = allowed - _OPTIONAL_KEYS
    missing = sorted(required - set(data))
    if missing:
        raise ControllerRejected(f"missing controller field {missing[0]!r}")


def _finite_float(value: Any, field: str) -> float:
    # Reject bool before int: ``bool`` is a subclass of ``int``.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ControllerRejected(f"{field} must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        raise ControllerRejected(f"{field} must be a finite number")
    return number


def _normalize_heuristic(parameters: Any) -> NormalizedController:
    if not isinstance(parameters, Mapping):
        raise ControllerRejected("heuristic parameters must be an object")
    extra = sorted(set(parameters) - set(HEURISTIC_BOUNDS))
    if extra:
        raise ControllerRejected(f"unknown heuristic parameter {extra[0]!r}")
    missing = sorted(set(HEURISTIC_BOUNDS) - set(parameters))
    if missing:
        raise ControllerRejected(f"missing heuristic parameter {missing[0]!r}")
    values: list[tuple[str, float]] = []
    for name, (low, high) in HEURISTIC_BOUNDS.items():
        number = _finite_float(parameters[name], field=name)
        if number < low or number > high:
            raise ControllerRejected(f"{name} must be between {low} and {high}")
        values.append((name, number))
    return NormalizedController(policy="heuristic", parameters=tuple(values))


def _normalize_linear(data: Mapping[str, Any]) -> NormalizedController:
    weights = data["weights"]
    bias = data["bias"]
    if not isinstance(weights, list) or len(weights) != N_ACTIONS:
        raise ControllerRejected("linear weights must have 4 rows, one per action")
    parsed_rows: list[tuple[float, ...]] = []
    for row_index, row in enumerate(weights):
        if not isinstance(row, list) or len(row) != N_OBSERVATIONS:
            raise ControllerRejected(
                f"linear weights row {row_index} must contain 8 observation weights"
            )
        parsed_row: list[float] = []
        for column_index, value in enumerate(row):
            number = _finite_float(value, field=f"weights[{row_index}][{column_index}]")
            if abs(number) > LINEAR_LIMIT:
                raise ControllerRejected(
                    f"weights[{row_index}][{column_index}] exceeds +/-{LINEAR_LIMIT}"
                )
            parsed_row.append(number)
        parsed_rows.append(tuple(parsed_row))
    if not isinstance(bias, list) or len(bias) != N_ACTIONS:
        raise ControllerRejected("linear bias must contain 4 values")
    parsed_bias: list[float] = []
    for index, value in enumerate(bias):
        number = _finite_float(value, field=f"bias[{index}]")
        if abs(number) > LINEAR_LIMIT:
            raise ControllerRejected(f"bias[{index}] exceeds +/-{LINEAR_LIMIT}")
        parsed_bias.append(number)
    clip_obs = DEFAULT_CLIP_OBS
    if "clip_obs" in data:
        clip_obs = _finite_float(data["clip_obs"], field="clip_obs")
        if clip_obs <= 0.0 or clip_obs > 100.0:
            raise ControllerRejected("clip_obs must be in (0, 100]")
    return NormalizedController(
        policy="linear",
        weights=tuple(parsed_rows),
        bias=tuple(parsed_bias),
        clip_obs=clip_obs,
    )


def _normalize_random(seed: Any) -> NormalizedController:
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ControllerRejected("random seed must be an integer")
    if seed < 0 or seed > MAX_SEED:
        raise ControllerRejected(f"random seed must be between 0 and {MAX_SEED}")
    return NormalizedController(policy="random", seed=seed)
