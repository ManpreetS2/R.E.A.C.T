#!/usr/bin/env python3
"""Headless bridge fidelity: reset identity, action traces, parallel independence."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.starts import resolve_start  # noqa: E402

OUT = ROOT / "outputs" / "parity"


def open_env(port: int, start: dict) -> ApolloLanderGym:
    return ApolloLanderGym(
        action_repeat=1,
        max_physics_frames=500,
        start_mode="research",
        start_override=start,
        reward_mode="progress_a",
        headless=True,
        port=port,
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    start = resolve_start("pilot_near")
    checks: dict = {"engine": "upstream-original", "passed": True, "failures": []}

    # 1) Reset reproducibility
    env = open_env(18770, start)
    try:
        o1, i1 = env.reset(seed=42)
        o2, i2 = env.reset(seed=42)
        if not np.allclose(o1, o2, atol=1e-5):
            checks["passed"] = False
            checks["failures"].append("reset_obs_mismatch")
        if i1["raw"]["x"] != i2["raw"]["x"] or i1["raw"]["rotation"] != i2["raw"]["rotation"]:
            checks["passed"] = False
            checks["failures"].append("reset_raw_mismatch")
        checks["reset_obs_max_delta"] = float(np.max(np.abs(o1 - o2)))

        # 2) Deterministic action trace → same outcome
        actions = [
            np.array([4, 2], dtype=np.int64),  # full thrust, +10
            np.array([4, 2], dtype=np.int64),
            np.array([2, 1], dtype=np.int64),
            np.array([1, 0], dtype=np.int64),
        ] * 20
        env.reset(seed=7)
        traj_a = []
        for a in actions:
            obs, _r, term, trunc, info = env.step(a)
            traj_a.append((obs.copy(), info["status"], info["physics_frames"]))
            if term or trunc:
                break
        env.reset(seed=7)
        traj_b = []
        for a in actions:
            obs, _r, term, trunc, info = env.step(a)
            traj_b.append((obs.copy(), info["status"], info["physics_frames"]))
            if term or trunc:
                break
        if len(traj_a) != len(traj_b):
            checks["passed"] = False
            checks["failures"].append("trace_length_mismatch")
        else:
            max_d = max(float(np.max(np.abs(a[0] - b[0]))) for a, b in zip(traj_a, traj_b))
            checks["trace_obs_max_delta"] = max_d
            if max_d > 1e-5 or traj_a[-1][1] != traj_b[-1][1]:
                checks["passed"] = False
                checks["failures"].append("trace_mismatch")
        checks["trace_final_status"] = traj_a[-1][1] if traj_a else None
    finally:
        env.close()

    # 3) Parallel envs independent (different ports / browsers)
    env_a = open_env(18771, start)
    env_b = open_env(18772, resolve_start("pilot_offset"))
    try:
        oa, ia = env_a.reset(seed=1)
        ob, ib = env_b.reset(seed=1)
        if np.allclose(oa, ob, atol=1e-3):
            # Different starts should differ
            checks["passed"] = False
            checks["failures"].append("parallel_starts_identical")
        # Step only A; B state should be unchanged until stepped
        raw_b_before = dict(ib["raw"])
        env_a.step(np.array([4, 1], dtype=np.int64))
        # Re-observe B via no-op evaluate observe — reset already done; step 0 thrust hold
        # We check that B's lander wasn't moved by reading after a 0-frame: call page observe
        assert env_b._page is not None
        raw_b_after = env_b._page.evaluate("() => window.ApolloOriginal.observe()")
        if abs(float(raw_b_after["x"]) - float(raw_b_before["x"])) > 1e-6:
            checks["passed"] = False
            checks["failures"].append("parallel_cross_talk")
        checks["parallel_xa"] = float(ia["raw"]["x"])
        checks["parallel_xb"] = float(ib["raw"]["x"])
        checks["pad_width_a"] = float(ia["raw"].get("pad_width", 0))
        # Pad should be the wide segment (~179 units)
        if checks["pad_width_a"] < 100:
            checks["passed"] = False
            checks["failures"].append("unexpected_pad_geometry")
    finally:
        env_a.close()
        env_b.close()

    # 4) Outcome coverage with scripted extremes (smoke)
    env = open_env(18770, start)
    outcomes = set()
    try:
        # No-op → expect crash/timeout
        env.reset(seed=0)
        while True:
            _o, _r, term, trunc, info = env.step(np.array([0, 1], dtype=np.int64))
            if term or trunc:
                outcomes.add(info["status"])
                break
        # Aggressive thrust while sideways → crash likely
        env.reset(seed=1)
        for _ in range(200):
            _o, _r, term, trunc, info = env.step(np.array([4, 0], dtype=np.int64))
            if term or trunc:
                outcomes.add(info["status"])
                break
    finally:
        env.close()
    checks["observed_statuses"] = sorted(outcomes)

    path = OUT / "parity_report.json"
    path.write_text(json.dumps(checks, indent=2))
    print(json.dumps(checks, indent=2))
    if not checks["passed"]:
        raise SystemExit("parity checks failed")


if __name__ == "__main__":
    main()
