"""Faithful Python port of ``frontend/apollolander/experiment/physics.js``.

Uses the fixed landscape dumped from the Node session (same simplex seed 12039
map). Every ``step()`` is one unmodified original physics update. Intended for
fast CPU training only; final evaluation must use the Node adapter.

Equivalence is proven in ``tests/rl/test_physics_equivalence.py`` against the
original Node session within the repo replay tolerance (1e-9).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PHYSICS = {
    "gravity": 0.0005,
    "thrustAcceleration": 0.0015,
    "topSpeed": 0.35,
    "drag": 0.9997,
    "rotationLerp": 0.3,
    "safeVerticalSpeed": 0.15,
    "perfectVerticalSpeed": 0.075,
    "defaultFuel": 1000,
    "defaultScale": 0.25,
    "physicsHz": 60,
}

REWARD = {
    "perfectLanding": 100,
    "hardLanding": 40,
    "crash": -100,
    "timeout": -25,
    "fuelPerUnit": 0.05,
    "progressScale": 0.5,
}

DEFAULT_LANDSCAPE = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "apollolander"
    / "rl_pilot"
    / "landscape_map.json"
)


@dataclass
class Line:
    p1x: float
    p1y: float
    p2x: float
    p2y: float
    landable: bool
    designated: bool


def load_landscape(path: Path | str | None = None) -> dict[str, Any]:
    landscape_path = Path(path) if path is not None else DEFAULT_LANDSCAPE
    with landscape_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    lines = [
        Line(
            p1x=float(line["p1"]["x"]),
            p1y=float(line["p1"]["y"]),
            p2x=float(line["p2"]["x"]),
            p2y=float(line["p2"]["y"]),
            landable=bool(line["landable"]),
            designated=bool(line["designated"]),
        )
        for line in payload["lines"]
    ]
    zone = payload["zone"]
    return {
        "tile_width": float(payload["tileWidth"]),
        "zone": {
            "x1": float(zone["x1"]),
            "x2": float(zone["x2"]),
            "y": float(zone["y"]),
            "index": int(zone["index"]),
            "width": float(zone["width"]),
        },
        "lines": lines,
        "points": payload["points"],
        "path": str(landscape_path),
    }


def rotate_vector(x: float, y: float, degrees: float) -> tuple[float, float]:
    radians = degrees * math.pi / 180.0
    cos = math.cos(radians)
    sin = math.sin(radians)
    return x * cos - y * sin, x * sin + y * cos


def point_below_line(px: float, py: float, line: Line) -> bool:
    span = line.p2x - line.p1x
    if span == 0:
        return False
    dist = (px - line.p1x) / span
    y_hit = line.p1y + (line.p2y - line.p1y) * dist
    return dist > 0 and dist < 1 and y_hit <= py


def normalize_action(action: dict[str, Any]) -> dict[str, float | int]:
    if not isinstance(action, dict):
        raise ValueError("action must be an object with thrust and rotation")
    forbidden = {"code", "js", "javascript", "script", "eval", "function"}
    for key in action:
        if key in forbidden or str(key).startswith("_"):
            raise ValueError(f"forbidden action field {key}")
        if key not in {"thrust", "rotation"}:
            raise ValueError(f"unknown action field {key}")
    thrust = action["thrust"]
    rotation = action["rotation"]
    if not isinstance(thrust, (int, float)) or isinstance(thrust, bool) or not math.isfinite(float(thrust)):
        raise ValueError("thrust must be a finite number from 0 to 1")
    thrust_f = float(thrust)
    if thrust_f < 0 or thrust_f > 1:
        raise ValueError("thrust must be a finite number from 0 to 1")
    if not isinstance(rotation, (int, float)) or isinstance(rotation, bool) or not math.isfinite(float(rotation)):
        raise ValueError("rotation must be a finite number from -90 to 90")
    rotation_f = float(rotation)
    if rotation_f < -90 or rotation_f > 90:
        raise ValueError("rotation must be a finite number from -90 to 90")
    if abs(rotation_f / 10.0 - round(rotation_f / 10.0)) > 1e-9:
        raise ValueError("rotation must be a multiple of 10 degrees")
    return {"thrust": thrust_f, "rotation": int(round(rotation_f))}


class ApolloPhysicsPython:
    """One lander simulation matching the Node experiment physics."""

    def __init__(self, landscape: dict[str, Any] | None = None) -> None:
        self.landscape = landscape if landscape is not None else load_landscape()
        self.lines: list[Line] = self.landscape["lines"]
        self.tile_width = float(self.landscape["tile_width"])
        self.zone = self.landscape["zone"]
        self.config: dict[str, Any] | None = None
        self.state: dict[str, Any] | None = None

    def standard_start(self) -> dict[str, float]:
        mid = (self.zone["x1"] + self.zone["x2"]) / 2.0
        return {
            "x": mid - 160.0,
            "y": 150.0,
            "vx": 0.415,
            "vy": 0.0,
            "rotation": -90.0,
            "fuel": float(PHYSICS["defaultFuel"]),
            "scale": float(PHYSICS["defaultScale"]),
        }

    def reset(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        raw = dict(config or {})
        fallback = self.standard_start()
        start = dict(fallback)
        start.update(raw.get("start") or {})
        for key in ("x", "y", "vx", "vy", "rotation", "fuel", "scale"):
            value = start[key]
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise ValueError(f"start.{key} must be a finite number")
            start[key] = float(value)
        if raw.get("bonuses"):
            raise ValueError("landing-zone bonuses are disabled for controlled trials")
        self.config = {
            "start": start,
            "maxSteps": int(raw.get("maxSteps") or 3600),
            "lockedCamera": raw.get("lockedCamera", True) is not False,
            "bonuses": False,
        }
        self.state = {
            "x": start["x"],
            "y": start["y"],
            "vx": start["vx"],
            "vy": start["vy"],
            "rotation": start["rotation"],
            "targetRotation": start["rotation"],
            "fuel": start["fuel"],
            "fuelUsed": 0.0,
            "scale": start["scale"],
            "thrust": 0.0,
            "thrustBuild": 0.0,
            "active": True,
            "step": 0,
            "status": "flying",
            "landed": False,
            "crashed": False,
            "inLandingZone": False,
            "timedOut": False,
            "perfect": False,
            "hard": False,
            "altitude": 0.0,
            "totalReward": 0.0,
            "lastPotential": None,
            "terminalReward": 0.0,
            "verified": None,
            "done": False,
        }
        self.state["altitude"] = self._altitude_at(self.state["x"], self.state["y"], self.state["scale"])
        self.state["lastPotential"] = self._potential(self.state)
        return self.observe()

    def observe(self) -> dict[str, Any]:
        assert self.state is not None
        mid = (self.zone["x1"] + self.zone["x2"]) / 2.0
        return {
            "x": self.state["x"],
            "y": self.state["y"],
            "vx": self.state["vx"],
            "vy": self.state["vy"],
            "rotation": self.state["rotation"],
            "fuel": self.state["fuel"],
            "altitude": self.state["altitude"],
            "thrust": self.state["thrustBuild"],
            "zoneLeft": self.zone["x1"],
            "zoneRight": self.zone["x2"],
            "zoneY": self.zone["y"],
            "dx": mid - self.state["x"],
            "dy": self.zone["y"] - self.state["y"],
            "step": self.state["step"],
            "status": self.state["status"],
        }

    def step(self, action: dict[str, Any]) -> dict[str, Any]:
        assert self.state is not None and self.config is not None
        if self.state["done"]:
            return {
                "reward": 0.0,
                "breakdown": {"shaping": 0.0, "fuelPenalty": 0.0, "terminal": 0.0},
                "done": True,
                "status": self.state["status"],
            }
        command = normalize_action(action)
        self.state["step"] += 1
        self.state["targetRotation"] = float(command["rotation"])
        self.state["thrust"] = float(command["thrust"]) if self.state["fuel"] > 0 else 0.0

        self.state["rotation"] += (self.state["targetRotation"] - self.state["rotation"]) * PHYSICS["rotationLerp"]
        if abs(self.state["rotation"] - self.state["targetRotation"]) < 0.1:
            self.state["rotation"] = self.state["targetRotation"]

        fuel_used = 0.0
        if self.state["active"]:
            self.state["thrustBuild"] += (self.state["thrust"] - self.state["thrustBuild"]) * 0.2
            if self.state["thrustBuild"] > 0:
                tx, ty = rotate_vector(
                    0.0,
                    -PHYSICS["thrustAcceleration"] * self.state["thrustBuild"],
                    self.state["rotation"],
                )
                self.state["vx"] += tx
                self.state["vy"] += ty
                fuel_used = 0.2 * self.state["thrustBuild"]
                self.state["fuel"] -= fuel_used
                self.state["fuelUsed"] += fuel_used
                if self.state["fuel"] < 0:
                    self.state["fuel"] = 0.0
            self.state["x"] += self.state["vx"]
            self.state["y"] += self.state["vy"]
            self.state["vx"] *= PHYSICS["drag"]
            self.state["vy"] += PHYSICS["gravity"]
            # Original assignment writes velY and does not clamp vel.y. Preserved.
            if self.state["fuel"] <= 0:
                self.state["thrust"] = 0.0

        self.state["altitude"] = self._altitude_at(self.state["x"], self.state["y"], self.state["scale"])
        contact = self._collide()
        next_potential = self._potential(self.state)
        shaping = (next_potential - self.state["lastPotential"]) * REWARD["progressScale"]
        self.state["lastPotential"] = next_potential
        fuel_penalty = fuel_used * REWARD["fuelPerUnit"]
        terminal = 0.0
        if contact is not None and self.state["status"] == "flying":
            terminal = self._apply_contact(contact)
        elif self.state["step"] >= self.config["maxSteps"] and self.state["status"] == "flying":
            self.state["status"] = "timeout"
            self.state["timedOut"] = True
            self.state["done"] = True
            self.state["active"] = False
            terminal = float(REWARD["timeout"])
        if self.state["status"] != "flying":
            self.state["done"] = True
        reward = shaping - fuel_penalty + terminal
        self.state["totalReward"] += reward
        self.state["terminalReward"] += terminal
        return {
            "reward": reward,
            "breakdown": {"shaping": shaping, "fuelPenalty": fuel_penalty, "terminal": terminal},
            "done": self.state["done"],
            "status": self.state["status"],
            "applied": command,
        }

    def get_result(self) -> dict[str, Any]:
        assert self.state is not None
        return {
            "status": self.state["status"],
            "landed": self.state["landed"],
            "crashed": self.state["crashed"],
            "inLandingZone": self.state["inLandingZone"],
            "timedOut": self.state["timedOut"],
            "perfect": self.state["perfect"],
            "hard": self.state["hard"],
            "steps": self.state["step"],
            "reward": self.state["totalReward"],
            "fuelUsed": self.state["fuelUsed"],
            "fuelRemaining": self.state["fuel"],
            "verified": self.state["verified"],
            "done": self.state["done"],
        }

    def map_info(self) -> dict[str, Any]:
        return {
            "tileWidth": self.tile_width,
            "zone": {
                "x1": self.zone["x1"],
                "x2": self.zone["x2"],
                "y": self.zone["y"],
                "index": self.zone["index"],
                "width": self.zone["width"],
            },
            "points": self.landscape["points"],
            "physics": dict(PHYSICS),
            "reward": dict(REWARD),
        }

    def _wrap_x(self, x: float) -> float:
        wrapped = x % self.tile_width
        if wrapped < 0:
            wrapped += self.tile_width
        return wrapped

    def _altitude_at(self, x: float, y: float, scale: float) -> float:
        wrapped = self._wrap_x(x)
        for line in self.lines:
            if wrapped < line.p1x or wrapped > line.p2x:
                continue
            span = line.p2x - line.p1x
            dist = 0.0 if span == 0 else (wrapped - line.p1x) / span
            ground = line.p1y + (line.p2y - line.p1y) * dist
            return ground - (y + 13.0 * scale)
        return 0.0

    def _potential(self, ship: dict[str, Any]) -> float:
        mid = (self.zone["x1"] + self.zone["x2"]) / 2.0
        dx = (ship["x"] - mid) / 100.0
        dy = (ship["y"] - self.zone["y"]) / 100.0
        return -math.hypot(dx, dy) - abs(ship["rotation"]) / 90.0

    def _apply_contact(self, contact: dict[str, Any]) -> float:
        assert self.state is not None
        self.state["verified"] = contact
        self.state["active"] = False
        self.state["thrust"] = 0.0
        self.state["thrustBuild"] = 0.0
        if contact["kind"] == "landed":
            self.state["inLandingZone"] = bool(contact["designated"])
            self.state["perfect"] = bool(contact["perfect"])
            self.state["hard"] = not bool(contact["perfect"])
            if contact["designated"] and contact["perfect"]:
                self.state["status"] = "landed"
                self.state["landed"] = True
                return float(REWARD["perfectLanding"])
            if contact["designated"]:
                self.state["status"] = "hard_landing"
                self.state["landed"] = True
                return float(REWARD["hardLanding"])
            self.state["status"] = "landed_outside_zone"
            self.state["landed"] = False
            return 0.0
        self.state["status"] = "crashed"
        self.state["crashed"] = True
        self.state["landed"] = False
        return float(REWARD["crash"])

    def _collide(self) -> dict[str, Any] | None:
        assert self.state is not None
        half_width = 10.0 * self.state["scale"]
        right = (self.state["x"] + half_width) % self.tile_width
        left = (self.state["x"] - half_width) % self.tile_width
        while right < 0:
            right += self.tile_width
            left += self.tile_width
        bottom = self.state["y"] + 13.0 * self.state["scale"]
        for i, line in enumerate(self.lines):
            if right < line.p1x or left > line.p2x:
                continue
            if line.landable:
                if bottom >= line.p1y:
                    inside = left > line.p1x and right < line.p2x
                    upright = self.state["rotation"] == 0
                    slow = self.state["vy"] < PHYSICS["safeVerticalSpeed"]
                    if inside and upright and slow:
                        return {
                            "kind": "landed",
                            "designated": line.designated,
                            "perfect": self.state["vy"] < PHYSICS["perfectVerticalSpeed"],
                            "lineIndex": i,
                            "rotation": self.state["rotation"],
                            "vy": self.state["vy"],
                            "left": left,
                            "right": right,
                            "bottom": bottom,
                            "segmentY": line.p1y,
                        }
                    return {
                        "kind": "crashed",
                        "reason": "attitude_or_speed" if inside else "not_fully_on_segment",
                        "lineIndex": i,
                        "rotation": self.state["rotation"],
                        "vy": self.state["vy"],
                        "left": left,
                        "right": right,
                        "bottom": bottom,
                    }
            elif bottom > line.p2y or bottom > line.p1y:
                if point_below_line(left, bottom, line) or point_below_line(right, bottom, line):
                    return {
                        "kind": "crashed",
                        "reason": "slope_contact",
                        "lineIndex": i,
                        "rotation": self.state["rotation"],
                        "vy": self.state["vy"],
                        "left": left,
                        "right": right,
                        "bottom": bottom,
                    }
        return None


def observation_vector(observation: dict[str, Any]) -> np.ndarray:
    """Fixed-length state vector for the RL policy (not pixels)."""
    return np.asarray(
        [
            float(observation["x"]),
            float(observation["y"]),
            float(observation["vx"]),
            float(observation["vy"]),
            float(observation["rotation"]),
            float(observation["fuel"]),
            float(observation["altitude"]),
            float(observation["dx"]),
            float(observation["dy"]),
            float(observation["thrust"]),
        ],
        dtype=np.float64,
    )


OBS_DIM = 10
OBS_LABELS = (
    "x",
    "y",
    "vx",
    "vy",
    "rotation",
    "fuel",
    "altitude",
    "dx",
    "dy",
    "thrust_build",
)

# Normalization scales chosen from documented ranges / map extents (not learned).
OBS_SCALE = np.asarray(
    [8000.0, 800.0, 1.0, 1.0, 90.0, 1000.0, 400.0, 400.0, 400.0, 1.0],
    dtype=np.float64,
)


def normalize_obs(raw: np.ndarray) -> np.ndarray:
    return (raw / OBS_SCALE).astype(np.float32)


# Discrete action parameterization: MultiDiscrete-equivalent flat index.
THRUST_BINS = np.asarray([0.0, 0.25, 0.5, 0.75, 1.0], dtype=np.float64)
ROTATION_BINS = np.asarray(list(range(-90, 100, 10)), dtype=np.int64)
N_THRUST = len(THRUST_BINS)
N_ROTATION = len(ROTATION_BINS)
N_ACTIONS = N_THRUST * N_ROTATION


def decode_action(index: int) -> dict[str, float | int]:
    if index < 0 or index >= N_ACTIONS:
        raise ValueError(f"action index {index} out of range [0, {N_ACTIONS})")
    thrust_i = index // N_ROTATION
    rot_i = index % N_ROTATION
    return {"thrust": float(THRUST_BINS[thrust_i]), "rotation": int(ROTATION_BINS[rot_i])}


def encode_action(thrust: float, rotation: int) -> int:
    thrust_i = int(np.argmin(np.abs(THRUST_BINS - float(thrust))))
    rot_i = int(np.argmin(np.abs(ROTATION_BINS.astype(np.float64) - float(rotation))))
    return thrust_i * N_ROTATION + rot_i
