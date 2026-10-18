"""Versioned ApolloLander research starting-state schedules.

Demonstration mode keeps the original fixed start. Research mode derives a
start from the episode seed with a documented, versioned mapping so that:

- the same seed always yields the same physical start
- different models compared on the same seeds face identical conditions
- development and held-out seed pools induce disjoint start schedules

Terrain, pad, physics constants, and the landing verifier are unchanged.
``scale`` stays at the collision value 0.25.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from rewardbench.environments.lunarlander.seeds import (
    HELD_OUT_SEED_START,
    development_seeds,
    held_out_seeds,
    validate_seed_split,
)

# Bump this string when ranges or channels change. Old experiment ids that
# recorded the previous version remain interpretable from their logs.
START_SCHEDULE_VERSION = "apollolander.starts.v1"

# Fixed-map pad midpoint from landscape noise seed 12039.
PAD_X1 = 6873.6
PAD_X2 = 7052.8
PAD_MID_X = (PAD_X1 + PAD_X2) / 2.0
# Primary landable pad Y for the same fixed landscape (measured via upstream host).
PAD_Y = 679.4358077547447

# Original demonstration / fixed-mode start (IMPLEMENTATION.md).
STANDARD_START: dict[str, float] = {
    "x": PAD_MID_X - 160.0,
    "y": 150.0,
    "vx": 0.415,
    "vy": 0.0,
    "rotation": -90.0,
    "fuel": 1000.0,
    "scale": 0.25,
}

# v1 research ranges. Chosen to keep the ship above the terrain, left of the
# pad, and within the locked camera arena used by the experiment page.
DX_FROM_PAD_MIN = -240.0
DX_FROM_PAD_MAX = -80.0
Y_MIN = 90.0
Y_MAX = 210.0
VX_MIN = 0.20
VX_MAX = 0.63
VY_MIN = -0.04
VY_MAX = 0.06
ROTATION_CHOICES: tuple[float, ...] = (-90.0, -80.0, -70.0, -60.0, -50.0, -40.0, -30.0)
FUEL_MIN = 850.0
FUEL_MAX = 1000.0
PHYSICS_SCALE = 0.25
# Lander bottom offset at collision scale: bottom = y + 13 * scale.
LANDER_BOTTOM_OFFSET = 13.0 * PHYSICS_SCALE

START_FIELDS = ("x", "y", "vx", "vy", "rotation", "fuel", "scale")


@dataclass(frozen=True)
class StartState:
    """One complete lander spawn used by the Node physics reset."""

    x: float
    y: float
    vx: float
    vy: float
    rotation: float
    fuel: float
    scale: float = PHYSICS_SCALE

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


@dataclass(frozen=True)
class StartScheduleSpec:
    """Documented bounds for a schedule version."""

    version: str
    dx_from_pad: tuple[float, float]
    y: tuple[float, float]
    vx: tuple[float, float]
    vy: tuple[float, float]
    rotations: tuple[float, ...]
    fuel: tuple[float, float]
    scale: float
    vary_fuel_default: bool


SCHEDULE_V1 = StartScheduleSpec(
    version=START_SCHEDULE_VERSION,
    dx_from_pad=(DX_FROM_PAD_MIN, DX_FROM_PAD_MAX),
    y=(Y_MIN, Y_MAX),
    vx=(VX_MIN, VX_MAX),
    vy=(VY_MIN, VY_MAX),
    rotations=ROTATION_CHOICES,
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)

# Curriculum aid ONLY (Family D). Nearer / more upright starts. Not proof of
# skill on the real start distribution — final eval always uses v1 / held-out.
SCHEDULE_CURRICULUM_EASY = StartScheduleSpec(
    version="apollolander.starts.curriculum_easy_v1",
    dx_from_pad=(-60.0, -20.0),
    y=(500.0, 620.0),
    vx=(0.0, 0.08),
    vy=(0.0, 0.05),
    rotations=(-20.0, -10.0, 0.0, 10.0, 20.0),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)

# Progressive curriculum v3 levels (physically legitimate in-world states).
# y ranges are lander.pos.y; approximate altitude ≈ PAD_Y - y - LANDER_BOTTOM_OFFSET.
# Final judgment always uses apollolander.starts.v1 / held-out seeds.
SCHEDULE_CURRICULUM_L0 = StartScheduleSpec(
    version="apollolander.starts.curriculum_l0_v3",
    dx_from_pad=(-8.0, 8.0),
    y=(PAD_Y - 18.0, PAD_Y - 12.0),  # ~9–15 px above pad
    vx=(-0.01, 0.01),
    vy=(0.01, 0.035),
    rotations=(0.0,),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)
# V5/V6 L0-near: ~3–6 px above pad (y = PAD_Y−9…PAD_Y−6), upright, low velocity.
# Physically legitimate in-world states a player/soft-drop can reach.
SCHEDULE_L0_NEAR_V6 = StartScheduleSpec(
    version="apollolander.starts.l0_near_v6",
    dx_from_pad=(-2.0, 2.0),
    y=(PAD_Y - 9.0, PAD_Y - 6.0),
    vx=(-0.005, 0.005),
    vy=(0.01, 0.02),
    rotations=(0.0,),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)
SCHEDULE_CURRICULUM_L1 = StartScheduleSpec(
    version="apollolander.starts.curriculum_l1_v3",
    dx_from_pad=(-40.0, 40.0),
    y=(PAD_Y - 80.0, PAD_Y - 40.0),  # ~37–77 px
    vx=(-0.04, 0.04),
    vy=(0.0, 0.05),
    rotations=(-10.0, 0.0, 10.0),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)
SCHEDULE_CURRICULUM_L2 = StartScheduleSpec(
    version="apollolander.starts.curriculum_l2_v3",
    dx_from_pad=(-100.0, 20.0),
    y=(PAD_Y - 200.0, PAD_Y - 100.0),  # ~97–197 px
    vx=(-0.05, 0.12),
    vy=(-0.02, 0.06),
    rotations=(-30.0, -20.0, -10.0, 0.0, 10.0, 20.0),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)
SCHEDULE_CURRICULUM_L3 = StartScheduleSpec(
    version="apollolander.starts.curriculum_l3_v3",
    dx_from_pad=(-180.0, -40.0),
    y=(PAD_Y - 400.0, PAD_Y - 220.0),  # ~217–397 px
    vx=(0.05, 0.35),
    vy=(-0.03, 0.06),
    rotations=(-60.0, -50.0, -40.0, -30.0, -20.0, -10.0, 0.0),
    fuel=(FUEL_MIN, FUEL_MAX),
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)
# L4 == normal research-mode start distribution (alias of v1).
SCHEDULE_CURRICULUM_L4 = StartScheduleSpec(
    version="apollolander.starts.curriculum_l4_v3",
    dx_from_pad=SCHEDULE_V1.dx_from_pad,
    y=SCHEDULE_V1.y,
    vx=SCHEDULE_V1.vx,
    vy=SCHEDULE_V1.vy,
    rotations=SCHEDULE_V1.rotations,
    fuel=SCHEDULE_V1.fuel,
    scale=PHYSICS_SCALE,
    vary_fuel_default=False,
)

CURRICULUM_V3_LEVELS: tuple[str, ...] = (
    SCHEDULE_CURRICULUM_L0.version,
    SCHEDULE_CURRICULUM_L1.version,
    SCHEDULE_CURRICULUM_L2.version,
    SCHEDULE_CURRICULUM_L3.version,
    SCHEDULE_CURRICULUM_L4.version,
)

_SCHEDULES: dict[str, StartScheduleSpec] = {
    SCHEDULE_V1.version: SCHEDULE_V1,
    SCHEDULE_CURRICULUM_EASY.version: SCHEDULE_CURRICULUM_EASY,
    SCHEDULE_CURRICULUM_L0.version: SCHEDULE_CURRICULUM_L0,
    SCHEDULE_CURRICULUM_L1.version: SCHEDULE_CURRICULUM_L1,
    SCHEDULE_CURRICULUM_L2.version: SCHEDULE_CURRICULUM_L2,
    SCHEDULE_CURRICULUM_L3.version: SCHEDULE_CURRICULUM_L3,
    SCHEDULE_CURRICULUM_L4.version: SCHEDULE_CURRICULUM_L4,
    SCHEDULE_L0_NEAR_V6.version: SCHEDULE_L0_NEAR_V6,
}


def schedule_spec(version: str = START_SCHEDULE_VERSION) -> StartScheduleSpec:
    if version not in _SCHEDULES:
        known = ", ".join(sorted(_SCHEDULES))
        raise ValueError(f"unknown ApolloLander start schedule {version!r}; known: {known}")
    return _SCHEDULES[version]


def standard_start() -> StartState:
    values = STANDARD_START
    return StartState(**{key: float(values[key]) for key in START_FIELDS})


def derive_start(
    seed: int,
    *,
    version: str = START_SCHEDULE_VERSION,
    vary_fuel: bool | None = None,
) -> StartState:
    """Map an episode seed to a reproducible research start.

    Development seeds (``< 1_000_000``) and held-out seeds (``>= 1_000_000``)
    use the same formula, so matched model comparisons share conditions when
    they share seeds. The pools remain disjoint because the seed integers are
    disjoint; catalogs built from each pool therefore never share a start.
    """
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("episode seed must be a non-negative integer")
    spec = schedule_spec(version)
    use_fuel = spec.vary_fuel_default if vary_fuel is None else bool(vary_fuel)
    dx = _lerp(spec.dx_from_pad[0], spec.dx_from_pad[1], _unit(version, seed, "dx"))
    y = _lerp(spec.y[0], spec.y[1], _unit(version, seed, "y"))
    vx = _lerp(spec.vx[0], spec.vx[1], _unit(version, seed, "vx"))
    vy = _lerp(spec.vy[0], spec.vy[1], _unit(version, seed, "vy"))
    rotation = spec.rotations[_index(version, seed, "rotation", len(spec.rotations))]
    if use_fuel:
        fuel = _lerp(spec.fuel[0], spec.fuel[1], _unit(version, seed, "fuel"))
    else:
        fuel = STANDARD_START["fuel"]
    return StartState(
        x=PAD_MID_X + dx,
        y=y,
        vx=vx,
        vy=vy,
        rotation=rotation,
        fuel=fuel,
        scale=spec.scale,
    )


def development_start_catalog(
    count: int,
    *,
    version: str = START_SCHEDULE_VERSION,
    vary_fuel: bool | None = None,
    seed_start: int = 0,
) -> list[tuple[int, StartState]]:
    """Starts induced by the development seed pool (for Agent 1 configs)."""
    seeds = development_seeds(count, start=seed_start)
    return [(seed, derive_start(seed, version=version, vary_fuel=vary_fuel)) for seed in seeds]


def held_out_start_catalog(
    count: int,
    *,
    version: str = START_SCHEDULE_VERSION,
    vary_fuel: bool | None = None,
    seed_start: int = 0,
) -> list[tuple[int, StartState]]:
    """Starts induced by the held-out seed pool. Not for controller development."""
    seeds = held_out_seeds(count, start=seed_start)
    return [(seed, derive_start(seed, version=version, vary_fuel=vary_fuel)) for seed in seeds]


def assert_schedules_disjoint(
    development: Sequence[tuple[int, StartState]],
    held_out: Sequence[tuple[int, StartState]],
) -> None:
    """Reject overlapping seed pools or identical start tuples across splits."""
    dev_seeds = [seed for seed, _ in development]
    hold_seeds = [seed for seed, _ in held_out]
    validate_seed_split(dev_seeds, "development")
    validate_seed_split(hold_seeds, "held_out")
    if set(dev_seeds) & set(hold_seeds):
        raise ValueError("development and held-out start catalogs share episode seeds")
    if any(seed >= HELD_OUT_SEED_START for seed in dev_seeds):
        raise ValueError("development start catalog contains held-out seeds")
    if any(seed < HELD_OUT_SEED_START for seed in hold_seeds):
        raise ValueError("held-out start catalog contains development seeds")
    dev_starts = {_start_key(start) for _, start in development}
    hold_starts = {_start_key(start) for _, start in held_out}
    overlap = dev_starts & hold_starts
    if overlap:
        raise ValueError(
            "development and held-out start catalogs share identical starting states; "
            f"example key {next(iter(overlap))!r}"
        )


def checked_start(start: Mapping[str, float] | None) -> dict[str, float] | None:
    """Validate an explicit start override (demonstration / alternate flights)."""
    if start is None:
        return None
    allowed = set(START_FIELDS)
    extra = sorted(set(start) - allowed)
    if extra:
        raise ValueError(f"unknown start field {extra[0]!r}")
    missing = sorted(allowed - set(start))
    if missing:
        raise ValueError(f"missing start field {missing[0]!r}")
    parsed: dict[str, float] = {}
    for key in START_FIELDS:
        value = start[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"start.{key} must be a finite number")
        number = float(value)
        if number != number or number in {float("inf"), float("-inf")}:
            raise ValueError(f"start.{key} must be a finite number")
        parsed[key] = number
    return parsed


def schedule_document(version: str = START_SCHEDULE_VERSION) -> dict[str, Any]:
    """JSON-serializable description for logs and Agent 1 configuration notes."""
    spec = schedule_spec(version)
    return {
        "version": spec.version,
        "pad_mid_x": PAD_MID_X,
        "standard_start": dict(STANDARD_START),
        "dx_from_pad": list(spec.dx_from_pad),
        "y": list(spec.y),
        "vx": list(spec.vx),
        "vy": list(spec.vy),
        "rotations": list(spec.rotations),
        "fuel": list(spec.fuel),
        "scale": spec.scale,
        "vary_fuel_default": spec.vary_fuel_default,
        "channels": ["dx", "y", "vx", "vy", "rotation", "fuel"],
        "hash": "sha256(f'{version}:{seed}:{channel}')[:12] / 16**12",
        "development_seed_rule": f"seeds in 0..{HELD_OUT_SEED_START - 1}",
        "held_out_seed_rule": f"seeds at and above {HELD_OUT_SEED_START}",
    }


def _unit(version: str, seed: int, channel: str) -> float:
    digest = hashlib.sha256(f"{version}:{seed}:{channel}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(16**12)


def _index(version: str, seed: int, channel: str, size: int) -> int:
    if size < 1:
        raise ValueError("rotation choice table cannot be empty")
    digest = hashlib.sha256(f"{version}:{seed}:{channel}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16) % size


def _lerp(low: float, high: float, unit: float) -> float:
    return low + (high - low) * unit


def _start_key(start: StartState) -> tuple[float, ...]:
    # Quantize lightly so float formatting cannot invent false overlaps.
    return tuple(round(getattr(start, field), 9) for field in START_FIELDS)
