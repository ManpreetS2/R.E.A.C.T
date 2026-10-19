"""Progressive research start distributions for the original-game Gym wrapper.

Terrain / pad geometry come from upstream Landscape noise seed 12039.
PAD_* constants match ``rewardbench.environments.apollolander.starts``.

Schedule versions:
- ``pilot_near`` / ``pilot_offset`` / ``original_fixed``: fixed spawn (historical pilots).
- ``short_horizon.v1``: seed-varied short time-to-contact starts for diagnostics.
"""

from __future__ import annotations

import hashlib
from typing import Any

# Widest landable segment on the fixed map (IMPLEMENTATION.md).
PAD_X1 = 6873.6
PAD_X2 = 7052.8
PAD_MID_X = (PAD_X1 + PAD_X2) / 2.0
PAD_Y_APPROX = 679.44

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
START_DISTRIBUTIONS: dict[str, dict[str, Any]] = {
    "pilot_near": {
        "label": "pilot_near",
        "varied": False,
        "rationale": (
            "HISTORICAL pilot spawn — identical physical state every seed. "
            "dx≈−40, y=280, rotation=−30. Kept for reproducibility of PR #11 pilots."
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
    "pilot_offset": {
        "label": "pilot_offset",
        "varied": False,
        "rationale": "Historical; dx≈−100, rotation=−60.",
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
    "original_fixed": {
        "label": "original_fixed",
        "varied": False,
        "rationale": "Upstream casual-play spawn (pad mid − 160, rotation −90).",
        "start": dict(STANDARD_FIXED),
    },
}

# Short-horizon diagnostic templates (base states; seed variation applied on top).
# Heights chosen so free-fall is short but no-op still crashes (needs brake + upright).
SHORT_HORIZON_TEMPLATES: dict[str, dict[str, Any]] = {
    "sh_tilt20_mid": {
        "label": "sh_tilt20_mid",
        "target_ttc_frames": "150–350",
        "rationale": "Mild tilt (−20°), ~120px above pad band; needs rotate+brake.",
        "base": {
            "x": PAD_MID_X - 25.0,
            "y": 560.0,
            "vx": 0.04,
            "vy": 0.08,
            "rotation": -20.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
        # Seeded ranges (additive / discrete)
        "vary": {
            "dx": (-15.0, 15.0),  # applied to x relative to base
            "y": (-20.0, 10.0),
            "vx": (-0.03, 0.06),
            "vy": (-0.02, 0.05),
            "rotations": (-30.0, -20.0, -10.0, 10.0, 20.0, 30.0),
        },
    },
    "sh_tilt30_low": {
        "label": "sh_tilt30_low",
        "target_ttc_frames": "100–250",
        "rationale": "Lower altitude, −30°; shorter horizon, still no-op crash.",
        "base": {
            "x": PAD_MID_X - 20.0,
            "y": 600.0,
            "vx": 0.03,
            "vy": 0.10,
            "rotation": -30.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
        "vary": {
            "dx": (-12.0, 12.0),
            "y": (-15.0, 5.0),
            "vx": (-0.02, 0.05),
            "vy": (-0.02, 0.04),
            "rotations": (-40.0, -30.0, -20.0, 20.0, 30.0, 40.0),
        },
    },
    "sh_upright_offset": {
        "label": "sh_upright_offset",
        "target_ttc_frames": "120–280",
        "rationale": "Near-upright but laterally offset — thrust/steering still required.",
        "base": {
            "x": PAD_MID_X - 55.0,
            "y": 580.0,
            "vx": 0.12,
            "vy": 0.06,
            "rotation": -10.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
        "vary": {
            "dx": (-20.0, 10.0),
            "y": (-15.0, 10.0),
            "vx": (-0.05, 0.08),
            "vy": (-0.02, 0.05),
            "rotations": (-20.0, -10.0, 0.0, 10.0, 20.0),
        },
    },
    # Contact-horizon: legal MultiDiscrete reference lands in ~100–300 physics frames.
    # No-op crashes in ~70–140 frames. Not a soft-drop (altitude / vy require braking).
    "sh_contact": {
        "label": "sh_contact",
        "target_ttc_frames": "100–300",
        "rationale": (
            "y≈665 (near pad), mild tilt, vy∈[0.08,0.16]. Sweep evidence: noop crash ~68–135 "
            "frames; MultiDiscrete reference lands ~106–252 frames; random land rate 0."
        ),
        "base": {
            "x": PAD_MID_X - 12.0,
            "y": 665.0,
            "vx": 0.02,
            "vy": 0.12,
            "rotation": -10.0,
            "fuel": 1000.0,
            "scale": 0.25,
        },
        "vary": {
            "dx": (-10.0, 10.0),
            "y": (-5.0, 3.0),
            "vx": (-0.02, 0.04),
            "vy": (-0.04, 0.04),
            "rotations": (-20.0, -10.0, 10.0, 20.0),
        },
    },
}

SHORT_HORIZON_VERSION = "short_horizon.v1"


def resolve_start(name: str) -> dict[str, float]:
    if name not in START_DISTRIBUTIONS:
        known = ", ".join(sorted(START_DISTRIBUTIONS))
        raise KeyError(f"unknown start distribution {name!r}; known: {known}")
    return dict(START_DISTRIBUTIONS[name]["start"])


def _unit(version: str, seed: int, channel: str) -> float:
    digest = hashlib.sha256(f"{version}:{seed}:{channel}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64


def _lerp(lo: float, hi: float, u: float) -> float:
    return float(lo + (hi - lo) * u)


def _index(version: str, seed: int, channel: str, n: int) -> int:
    digest = hashlib.sha256(f"{version}:{seed}:{channel}".encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % n


def derive_short_horizon_start(
    template: str,
    seed: int,
    *,
    version: str = SHORT_HORIZON_VERSION,
    vary: bool = True,
) -> dict[str, float]:
    """Map episode seed → reproducible short-horizon start."""
    if template not in SHORT_HORIZON_TEMPLATES:
        known = ", ".join(sorted(SHORT_HORIZON_TEMPLATES))
        raise KeyError(f"unknown short-horizon template {template!r}; known: {known}")
    if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative int")
    spec = SHORT_HORIZON_TEMPLATES[template]
    base = dict(spec["base"])
    if not vary:
        return base
    v = spec["vary"]
    dx = _lerp(v["dx"][0], v["dx"][1], _unit(version, seed, f"{template}:dx"))
    y_off = _lerp(v["y"][0], v["y"][1], _unit(version, seed, f"{template}:y"))
    vx = base["vx"] + _lerp(v["vx"][0], v["vx"][1], _unit(version, seed, f"{template}:vx"))
    vy = base["vy"] + _lerp(v["vy"][0], v["vy"][1], _unit(version, seed, f"{template}:vy"))
    rots = v["rotations"]
    rotation = float(rots[_index(version, seed, f"{template}:rot", len(rots))])
    return {
        "x": float(base["x"] + dx),
        "y": float(base["y"] + y_off),
        "vx": float(vx),
        "vy": float(vy),
        "rotation": rotation,
        "fuel": float(base["fuel"]),
        "scale": float(base["scale"]),
    }


def start_catalog(template: str, seeds: list[int]) -> list[dict[str, float]]:
    return [derive_short_horizon_start(template, s) for s in seeds]
