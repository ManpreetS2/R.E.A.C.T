"""Progressive research start distributions for the original-game Gym wrapper.

Terrain / pad geometry come from upstream Landscape noise seed 12039.
PAD_* constants match ``rewardbench.environments.apollolander.starts``.
"""

from __future__ import annotations

from typing import Any

# Widest landable segment on the fixed map (IMPLEMENTATION.md).
PAD_X1 = 6873.6
PAD_X2 = 7052.8
PAD_MID_X = (PAD_X1 + PAD_X2) / 2.0
# Pad surface y is ~679.44 on this map; bridge reports live pad.y in reset info.

STANDARD_FIXED: dict[str, float] = {
    "x": PAD_MID_X - 160.0,
    "y": 150.0,
    "vx": 0.415,
    "vy": 0.0,
    "rotation": -90.0,
    "fuel": 1000.0,
    "scale": 0.25,
}

# Progressive tiers (explicit overrides; bridge start_mode=research).
# Chosen so gravity + tilt make no-input fail while a real controller can land.
START_DISTRIBUTIONS: dict[str, dict[str, Any]] = {
    # Tier 0 — near pad, mild tilt, modest height. Still needs rotate+brake.
    "pilot_near": {
        "label": "pilot_near",
        "rationale": (
            "dx≈−40, y=280, rotation=−30. High enough that free-fall crashes; "
            "close enough that a short upright+brake sequence can land."
        ),
        "start": {
            "x": PAD_MID_X - 40.0,
            "y": 280.0,
            "vx": 0.05,
            "vy": 0.02,
            "rotation": -30.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
    },
    # Tier 1 — larger offset + steeper tilt (still easier than full fixed).
    "pilot_offset": {
        "label": "pilot_offset",
        "rationale": "dx≈−100, rotation=−60; requires translation and attitude.",
        "start": {
            "x": PAD_MID_X - 100.0,
            "y": 220.0,
            "vx": 0.20,
            "vy": 0.0,
            "rotation": -60.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
    },
    # Tier 2 — original fixed spawn (harder milestone).
    "original_fixed": {
        "label": "original_fixed",
        "rationale": "Upstream casual-play spawn (pad mid − 160, rotation −90).",
        "start": dict(STANDARD_FIXED),
    },
}


def resolve_start(name: str) -> dict[str, float]:
    if name not in START_DISTRIBUTIONS:
        known = ", ".join(sorted(START_DISTRIBUTIONS))
        raise KeyError(f"unknown start distribution {name!r}; known: {known}")
    return dict(START_DISTRIBUTIONS[name]["start"])
