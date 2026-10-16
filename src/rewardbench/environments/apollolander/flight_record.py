"""ApolloLander flight manifests for objective replay and inspection.

A flight record captures enough information to re-run an episode from the
same seed and controller and check that the simulator outcome matches.
Environment-side code never sets ``autonomous_learning`` to true for
hand-specified or mock controllers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

# Bump when the fixed map, physics constants, or reward table change.
ENVIRONMENT_VERSION = "apollolander.env.v1"
FLIGHT_RECORD_SCHEMA = "rewardbench.apollolander.flight_record.v1"
LANDSCAPE_NOISE_SEED = 12039

# Provenance labels. Agent 1 should pass these through evaluate(origin=...).
ORIGIN_HAND_SPECIFIED = "hand_specified_demonstration"
ORIGIN_DETERMINISTIC_MOCK = "deterministic_mock"
ORIGIN_MODEL_GENERATED = "model_generated"
ORIGIN_UNSPECIFIED = "unspecified"
KNOWN_ORIGINS = frozenset(
    {
        ORIGIN_HAND_SPECIFIED,
        ORIGIN_DETERMINISTIC_MOCK,
        ORIGIN_MODEL_GENERATED,
        ORIGIN_UNSPECIFIED,
    }
)

# Deterministic replay tolerances (same Node binary, same schedule version).
REPLAY_REWARD_ABS_TOL = 1e-9
REPLAY_STATE_ABS_TOL = 1e-9
REPLAY_STEP_TOL = 0


def autonomous_learning_claimed(origin: str) -> bool:
    """Environment recordings never claim autonomous learning for demos/mocks."""
    return False


def canonicalize(value: Any) -> Any:
    """JSON-stable form used for hashes and sidecar files."""
    if isinstance(value, Mapping):
        return {str(key): canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value
    raise TypeError(f"cannot canonicalize {type(value).__name__}")


def trace_hash(trace: Sequence[Mapping[str, Any]]) -> str:
    """Stable identifier for an action sequence."""
    payload = json.dumps(canonicalize(list(trace)), separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def controller_hash(controller: Mapping[str, Any]) -> str:
    payload = json.dumps(canonicalize(dict(controller)), separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_flight_record(
    *,
    environment_id: str,
    environment_version: str = ENVIRONMENT_VERSION,
    research_mode: bool,
    start_schedule_version: str | None,
    vary_fuel: bool,
    seed: int,
    start: Mapping[str, float],
    controller: Mapping[str, Any],
    revision: int | None,
    origin: str,
    model: str,
    split: str | None,
    max_steps: int,
    result: Mapping[str, Any],
    zone: Mapping[str, Any],
    trace: Sequence[Mapping[str, Any]],
    fuel_penalty: float,
    terminal_reward: float,
    video_path: str | None = None,
    experiment_id: str | None = None,
    episode_index: int | None = None,
) -> dict[str, Any]:
    """Assemble the inspectable, replayable episode manifest."""
    actions = [dict(action) for action in trace]
    record = {
        "schema": FLIGHT_RECORD_SCHEMA,
        "environment_id": environment_id,
        "environment_version": environment_version,
        "landscape_noise_seed": LANDSCAPE_NOISE_SEED,
        "research_mode": bool(research_mode),
        "start_schedule_version": start_schedule_version if research_mode else None,
        "vary_fuel": bool(vary_fuel) if research_mode else False,
        "experiment_id": experiment_id,
        "episode_seed": int(seed),
        "episode_index": episode_index,
        "initial_state": {key: float(start[key]) for key in ("x", "y", "vx", "vy", "rotation", "fuel", "scale")},
        "controller": dict(controller),
        "controller_hash": controller_hash(controller),
        "revision_index": revision,
        "origin": origin,
        "model": model,
        "autonomous_learning": autonomous_learning_claimed(origin),
        "split": split,
        "max_steps": int(max_steps),
        "terminal": {
            "status": result.get("status"),
            "reward": float(result["reward"]),
            "landed": bool(result["landed"]),
            "crashed": bool(result["crashed"]),
            "in_landing_zone": bool(result["inLandingZone"])
            if "inLandingZone" in result
            else bool(result.get("in_landing_zone", False)),
            "timed_out": bool(result["timedOut"]) if "timedOut" in result else bool(result.get("timed_out", False)),
            "verified": result.get("verified"),
            "steps": int(result["steps"]),
            "fuel_used": float(result["fuelUsed"]) if "fuelUsed" in result else float(result.get("fuel_used", 0.0)),
            "fuel_remaining": float(result["fuelRemaining"])
            if "fuelRemaining" in result
            else float(result.get("fuel_remaining", 0.0)),
            "fuel_penalty": float(fuel_penalty),
            "terminal_reward": float(terminal_reward),
        },
        "zone": dict(zone),
        "trace": actions,
        "trace_hash": trace_hash(actions),
        "trace_length": len(actions),
        "video_path": video_path,
        "replay_tolerances": {
            "reward_abs": REPLAY_REWARD_ABS_TOL,
            "state_abs": REPLAY_STATE_ABS_TOL,
            "steps": REPLAY_STEP_TOL,
        },
    }
    return record


def write_flight_record(path: Path, record: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(canonicalize(dict(record)), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_flight_record(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compare_terminal(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    reward_tol: float = REPLAY_REWARD_ABS_TOL,
    step_tol: int = REPLAY_STEP_TOL,
) -> list[str]:
    """Return human-readable mismatches; empty means the terminals agree."""
    mismatches: list[str] = []
    for key in ("status", "landed", "crashed", "in_landing_zone", "timed_out"):
        if expected.get(key) != observed.get(key):
            mismatches.append(f"{key}: expected {expected.get(key)!r}, got {observed.get(key)!r}")
    if abs(int(expected.get("steps", -1)) - int(observed.get("steps", -2))) > step_tol:
        mismatches.append(f"steps: expected {expected.get('steps')}, got {observed.get('steps')}")
    try:
        if abs(float(expected["reward"]) - float(observed["reward"])) > reward_tol:
            mismatches.append(
                f"reward: expected {expected['reward']}, got {observed['reward']} (tol {reward_tol})"
            )
    except (KeyError, TypeError, ValueError) as exc:
        mismatches.append(f"reward: {exc}")
    return mismatches


def compare_observations(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    keys: Sequence[str] = ("x", "y", "vx", "vy", "rotation", "fuel"),
    abs_tol: float = REPLAY_STATE_ABS_TOL,
) -> list[str]:
    mismatches: list[str] = []
    for key in keys:
        try:
            left = float(expected[key])
            right = float(observed[key])
        except (KeyError, TypeError, ValueError) as exc:
            mismatches.append(f"observation.{key}: {exc}")
            continue
        if abs(left - right) > abs_tol:
            mismatches.append(f"observation.{key}: expected {left}, got {right} (tol {abs_tol})")
    return mismatches
