#!/usr/bin/env python3
"""Generate parity action traces that END in each native terminal category.

PARITY / REFERENCE ONLY. Never used to train or initialize the neural net.

Uses the hand-tuned demonstration_guidance_controller (and a few scripted
open-loop sequences) against the upstream Node vm host to produce real
episodes that terminate as:
  - perfect landings (landed, vy < 0.075, rotation == 0)
  - hard landings (landed, 0.075 <= vy < 0.15, rotation == 0)
  - crashes (several geometries, including near-boundary pad contacts)
  - completed timeouts (full max_steps)

Writes JSON traces under results/parity_traces/.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.schema import (  # noqa: E402
    DEMONSTRATION_GUIDANCE,
    guidance_action,
)
from rewardbench.environments.apollolander.starts import (  # noqa: E402
    PAD_MID_X,
    PAD_Y,
    derive_start,
)
from rewardbench.rl.reserved_seeds import assert_seed_allowed  # noqa: E402
from rewardbench.rl.upstream_env import UpstreamSession  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "results" / "parity_traces"
OUT.mkdir(parents=True, exist_ok=True)

# Diagnostic frame budget counter (parity generation only).
DIAG_FRAMES = 0


def _call(session: UpstreamSession, payload: dict[str, Any]) -> dict[str, Any]:
    return session.call(payload)


def _run_episode(
    session: UpstreamSession,
    *,
    start: dict[str, float],
    max_steps: int,
    policy: str,
    seed: int | None = None,
) -> dict[str, Any]:
    global DIAG_FRAMES
    msg = _call(
        session,
        {"cmd": "reset", "config": {"start": start, "maxSteps": max_steps, "rewardMode": "touchdown_v1"}},
    )
    obs = msg["observation"]
    actions: list[dict[str, float | int]] = []
    frames: list[dict[str, Any]] = []
    for step_i in range(max_steps):
        if policy == "guidance":
            obs_for_g = dict(obs)
            obs_for_g["step"] = step_i
            action = guidance_action(obs_for_g, DEMONSTRATION_GUIDANCE)
        elif policy == "soft_drop":
            # Hold upright; modulate thrust to target soft vy.
            vy = float(obs["vy"])
            thrust = 0.45 if vy > 0.06 else (0.25 if vy > 0.04 else 0.12)
            action = {"thrust": thrust, "rotation": 0}
        elif policy == "hard_drop":
            # Upright but intentionally too fast for perfect, still < 0.15.
            vy = float(obs["vy"])
            if vy < 0.09:
                thrust = 0.05
            elif vy > 0.14:
                thrust = 0.55
            else:
                thrust = 0.18
            action = {"thrust": thrust, "rotation": 0}
        elif policy == "tilt_crash":
            action = {"thrust": 0.1, "rotation": 30}
        elif policy == "coast_crash":
            action = {"thrust": 0.0, "rotation": int(obs.get("rotation", 0))}
        elif policy == "hover_timeout":
            # Try to hold altitude near start to force full max_steps.
            vy = float(obs["vy"])
            thrust = 0.34 + max(-0.2, min(0.4, (vy - 0.0) * 8.0))
            action = {"thrust": float(max(0.0, min(1.0, thrust))), "rotation": 0}
        else:
            raise ValueError(policy)

        actions.append({"thrust": float(action["thrust"]), "rotation": int(action["rotation"])})
        stepped = _call(session, {"cmd": "step", "action": actions[-1]})
        DIAG_FRAMES += 1
        obs = stepped["observation"]
        frames.append(
            {
                "x": obs["x"],
                "y": obs["y"],
                "vx": obs["vx"],
                "vy": obs["vy"],
                "rotation": obs["rotation"],
                "fuel": obs["fuel"],
                "thrustBuild": obs.get("thrustBuild", obs.get("thrust", 0)),
            }
        )
        result = stepped["result"]
        if result["done"]:
            return {
                "start": start,
                "max_steps": max_steps,
                "actions": actions,
                "frames": frames,
                "terminal": {
                    "status": result["status"],
                    "nativeScore": result.get("nativeScore", 0),
                    "nativeOutcome": result.get("nativeOutcome"),
                    "steps": result.get("steps"),
                },
                "policy": policy,
                "seed": seed,
                "physics_frames": len(actions),
            }
    result = _call(session, {"cmd": "result"})["result"]
    return {
        "start": start,
        "max_steps": max_steps,
        "actions": actions,
        "frames": frames,
        "terminal": {
            "status": result["status"],
            "nativeScore": result.get("nativeScore", 0),
            "nativeOutcome": result.get("nativeOutcome"),
            "steps": result.get("steps"),
        },
        "policy": policy,
        "seed": seed,
        "physics_frames": len(actions),
    }


def _classify(status: str) -> str:
    if status == "landed":
        return "perfect_landing"
    if status == "hard_landing":
        return "hard_landing"
    if status == "crashed":
        return "crash"
    if status == "timeout":
        return "timeout"
    return status


def collect() -> dict[str, Any]:
    global DIAG_FRAMES
    DIAG_FRAMES = 0
    session = UpstreamSession.start()
    catalog: dict[str, list[dict[str, Any]]] = {
        "perfect_landing": [],
        "hard_landing": [],
        "crash": [],
        "timeout": [],
    }
    try:
        # --- Perfect landings via L0 soft drop + guidance on research starts ---
        for i, dy in enumerate((14.0, 16.0, 12.0, 15.0)):
            start = {
                "x": PAD_MID_X + (-4.0 + i),
                "y": PAD_Y - dy,
                "vx": 0.0,
                "vy": 0.02,
                "rotation": 0.0,
                "fuel": 1000.0,
                "scale": 0.25,
            }
            ep = _run_episode(session, start=start, max_steps=800, policy="soft_drop", seed=900100 + i)
            if _classify(ep["terminal"]["status"]) == "perfect_landing":
                catalog["perfect_landing"].append(ep)

        for seed in (42, 77, 120, 333, 501):
            assert_seed_allowed(seed, context="parity_trace.guidance")
            start = derive_start(seed, version="apollolander.starts.v1").as_dict()
            ep = _run_episode(session, start=start, max_steps=8000, policy="guidance", seed=seed)
            cls = _classify(ep["terminal"]["status"])
            if cls in catalog and len(catalog[cls]) < 6:
                catalog[cls].append(ep)

        # --- Hard landings: upright contact with 0.075 <= vy < 0.15 ---
        for i, target_vy in enumerate((0.10, 0.11, 0.12, 0.095)):
            start = {
                "x": PAD_MID_X + (i - 1) * 3.0,
                "y": PAD_Y - 22.0,
                "vx": 0.0,
                "vy": target_vy,
                "rotation": 0.0,
                "fuel": 1000.0,
                "scale": 0.25,
            }
            ep = _run_episode(session, start=start, max_steps=400, policy="hard_drop", seed=900200 + i)
            if _classify(ep["terminal"]["status"]) == "hard_landing":
                catalog["hard_landing"].append(ep)
            elif _classify(ep["terminal"]["status"]) == "perfect_landing":
                # Retry with less thrust authority by starting faster / lower.
                start["y"] = PAD_Y - 10.0
                start["vy"] = 0.13
                ep = _run_episode(session, start=start, max_steps=200, policy="hard_drop", seed=900210 + i)
                if _classify(ep["terminal"]["status"]) == "hard_landing":
                    catalog["hard_landing"].append(ep)

        # --- Crashes: tilted, boundary, fast ---
        crash_starts = [
            # Tilted on pad
            {
                "name": "tilt_on_pad",
                "start": {
                    "x": PAD_MID_X,
                    "y": PAD_Y - 30.0,
                    "vx": 0.0,
                    "vy": 0.08,
                    "rotation": 30.0,
                    "fuel": 800.0,
                    "scale": 0.25,
                },
                "policy": "tilt_crash",
                "max_steps": 400,
            },
            # Near left pad boundary (feet straddle edge)
            {
                "name": "near_left_boundary",
                "start": {
                    "x": 6873.6 + 8.0,
                    "y": PAD_Y - 25.0,
                    "vx": -0.05,
                    "vy": 0.1,
                    "rotation": 0.0,
                    "fuel": 800.0,
                    "scale": 0.25,
                },
                "policy": "coast_crash",
                "max_steps": 400,
            },
            # Near right pad boundary
            {
                "name": "near_right_boundary",
                "start": {
                    "x": 7052.8 - 8.0,
                    "y": PAD_Y - 25.0,
                    "vx": 0.05,
                    "vy": 0.1,
                    "rotation": 0.0,
                    "fuel": 800.0,
                    "scale": 0.25,
                },
                "policy": "coast_crash",
                "max_steps": 400,
            },
            # Fast upright (vy >= 0.15 → crash despite rotation 0)
            {
                "name": "fast_upright",
                "start": {
                    "x": PAD_MID_X,
                    "y": PAD_Y - 40.0,
                    "vx": 0.0,
                    "vy": 0.22,
                    "rotation": 0.0,
                    "fuel": 800.0,
                    "scale": 0.25,
                },
                "policy": "coast_crash",
                "max_steps": 400,
            },
            # Terrain left of pad
            {
                "name": "terrain_left",
                "start": {
                    "x": PAD_MID_X - 220.0,
                    "y": 520.0,
                    "vx": 0.0,
                    "vy": 0.15,
                    "rotation": -20.0,
                    "fuel": 500.0,
                    "scale": 0.25,
                },
                "policy": "coast_crash",
                "max_steps": 800,
            },
        ]
        for i, spec in enumerate(crash_starts):
            ep = _run_episode(
                session,
                start=spec["start"],
                max_steps=spec["max_steps"],
                policy=spec["policy"],
                seed=900300 + i,
            )
            ep["name"] = spec["name"]
            if _classify(ep["terminal"]["status"]) == "crash":
                catalog["crash"].append(ep)

        # --- Completed timeouts: full max_steps ---
        for i, max_steps in enumerate((200, 400, 800)):
            start = {
                "x": PAD_MID_X - 40.0,
                "y": 200.0,
                "vx": 0.05,
                "vy": 0.0,
                "rotation": 0.0,
                "fuel": 1000.0,
                "scale": 0.25,
            }
            ep = _run_episode(
                session,
                start=start,
                max_steps=max_steps,
                policy="hover_timeout",
                seed=900400 + i,
            )
            if _classify(ep["terminal"]["status"]) == "timeout" and ep["terminal"]["steps"] == max_steps:
                catalog["timeout"].append(ep)

        # One long full-episode timeout at research max_steps=4000 if budget allows.
        start = {
            "x": PAD_MID_X - 80.0,
            "y": 180.0,
            "vx": 0.1,
            "vy": 0.0,
            "rotation": 0.0,
            "fuel": 1000.0,
            "scale": 0.25,
        }
        ep = _run_episode(session, start=start, max_steps=4000, policy="hover_timeout", seed=900410)
        if _classify(ep["terminal"]["status"]) == "timeout" and ep["terminal"]["steps"] == 4000:
            catalog["timeout"].append(ep)

    finally:
        session.close()

    # Drop heavy per-frame payloads from the catalog index; keep actions.
    slim: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "diagnostic_physics_frames": DIAG_FRAMES,
        "note": (
            "REFERENCE/PARITY ONLY. Traces from hand-tuned guidance or scripted "
            "open-loop controllers. Never used to train the neural network."
        ),
        "categories": {},
    }
    for cat, eps in catalog.items():
        slim["categories"][cat] = []
        for idx, ep in enumerate(eps):
            path = OUT / f"{cat}_{idx:02d}.json"
            # Keep frames for long-traj parity; may be large for timeout 4000.
            path.write_text(json.dumps(ep), encoding="utf-8")
            slim["categories"][cat].append(
                {
                    "path": str(path.relative_to(HERE.parent)),
                    "status": ep["terminal"]["status"],
                    "steps": ep["terminal"]["steps"],
                    "nativeScore": ep["terminal"]["nativeScore"],
                    "nativeOutcome": ep["terminal"]["nativeOutcome"],
                    "policy": ep["policy"],
                    "seed": ep.get("seed"),
                    "name": ep.get("name"),
                    "physics_frames": ep["physics_frames"],
                }
            )
    index_path = OUT / "index.json"
    index_path.write_text(json.dumps(slim, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: len(v) for k, v in catalog.items()}, indent=2))
    print("diagnostic_physics_frames", DIAG_FRAMES)
    print("wrote", index_path)
    return slim


if __name__ == "__main__":
    collect()
