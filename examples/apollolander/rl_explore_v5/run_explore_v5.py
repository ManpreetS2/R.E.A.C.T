#!/usr/bin/env python3
"""Exploration-bottleneck diagnostics — NO TRAINING, ≤100k diagnostic frames.

Compares player-legal action representations × start sets under matched random
and untrained (clean-init) policies. Logs terminal contact violations.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.starts import (  # noqa: E402
    PAD_MID_X,
    PAD_Y,
    PHYSICS_SCALE,
    derive_start,
)
from rewardbench.rl.continuous_policy import (  # noqa: E402
    ROTATION_DELTAS,
    ContinuousThrustActorCritic,
)
from rewardbench.rl.diagnostic_budget import DiagnosticBudget, DiagnosticBudgetExhausted  # noqa: E402
from rewardbench.rl.physics_python import ROTATION_BINS  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed  # noqa: E402
from rewardbench.rl.upstream_env import UpstreamSession  # noqa: E402

HERE = Path(__file__).resolve().parent
OUT = HERE / "results" / "EXPLORE_v5"
DIAG_CAP = 100_000
MAX_STEPS = 400
# Matched seeds for every cell (new, non-reserved).
SEED_START = 530_000
N_EPISODES = 12  # tight budget; Wilson still informative for rare events

# Near-miss definition (fixed before outcomes):
# Pad-aligned contact (landable_contact & within_pad) that is NOT a landing,
# with exactly one of {rotation==0, vy<0.15} failed, within tolerance:
NEAR_MISS_ROT_TOL_DEG = 10.0  # |rotation|≤10 if rotation is the sole failure
NEAR_MISS_VY_TOL = 0.30  # vy<0.30 if vy is the sole failure (safe is 0.15)


def wilson(s: int, n: int) -> list[float]:
    if n <= 0:
        return [0.0, 0.0]
    z = 1.96
    p = s / n
    denom = 1.0 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [max(0.0, center - margin), min(1.0, center + margin)]


@dataclass
class RepSpec:
    name: str
    thrust_mode: str  # continuous | discrete4
    rotation_mode: str  # delta | absolute | hold_heavy_delta
    action_repeat: int
    player_mapping: str


REPS: list[RepSpec] = [
    RepSpec(
        "cont_delta_ar1",
        "continuous",
        "delta",
        1,
        "Touch thrust slider continuous; setRotation ±10°/0 each decision (1 frame). "
        "Unlike keyboard, decisions every physics frame.",
    ),
    RepSpec(
        "cont_delta_ar4",
        "continuous",
        "delta",
        4,
        "Same as keyboard-ish hold: one setRotation/thrust command held ~4 frames "
        "(≈67ms), near the 80ms keyboard rotate rate limit.",
    ),
    RepSpec(
        "cont_delta_ar8",
        "continuous",
        "delta",
        8,
        "Command held 8 frames (~133ms); slower than keyboard max rotate rate.",
    ),
    RepSpec(
        "cont_delta_ar16",
        "continuous",
        "delta",
        16,
        "Command held 16 frames (~267ms); player holding a key / not re-tapping.",
    ),
    RepSpec(
        "disc4_delta_ar8",
        "discrete4",
        "delta",
        8,
        "Thrust in {0,0.25,0.5,1} (UP key is binary 0/1; touch is continuous — "
        "discrete bins are a coarsening of touch). Delta setRotation as above.",
    ),
    RepSpec(
        "cont_absolute_ar8",
        "continuous",
        "absolute",
        8,
        "Touch absolute angle via setRotation to one of 19 bins (-90..90/10°), "
        "held 8 frames.",
    ),
    RepSpec(
        "cont_holdheavy_ar8",
        "continuous",
        "hold_heavy_delta",
        8,
        "Action layout {-10,0,0,0,+10}: 3/5 mass on hold by layout (maps to "
        "releasing arrow keys), not NN bias. Held 8 frames.",
    ),
]


def l0_start(seed: int) -> dict[str, float]:
    return derive_start(
        seed, version="apollolander.starts.curriculum_l0_v3", vary_fuel=False
    ).as_dict()


def l0_near_start(seed: int) -> dict[str, float]:
    u = (seed % 1000) / 1000.0
    return {
        "x": PAD_MID_X + (-2.0 + 4.0 * u),
        "y": PAD_Y - (6.0 + 3.0 * u),
        "vx": -0.005 + 0.01 * u,
        "vy": 0.01 + 0.01 * u,
        "rotation": 0.0,
        "fuel": 1000.0,
        "scale": PHYSICS_SCALE,
    }


STARTS = {
    "L0": l0_start,
    "L0_near": l0_near_start,
}


class ActionSampler:
    def __init__(self, rep: RepSpec, mode: str, policy: ContinuousThrustActorCritic | None, rng: np.random.Generator):
        self.rep = rep
        self.mode = mode  # random | untrained
        self.policy = policy
        self.rng = rng
        self.cmd_rot = 0

    def reset_cmd(self, start_rot: float) -> None:
        self.cmd_rot = int(round(float(start_rot) / 10.0) * 10)

    def sample(self, obs: np.ndarray) -> dict[str, float | int]:
        if self.mode == "untrained":
            assert self.policy is not None
            with torch.no_grad():
                t = torch.as_tensor(obs[None], dtype=torch.float32)
                thrust_t, rot_idx, _, _, _ = self.policy.act(t)
                thrust = float(thrust_t.item())
                ri = int(rot_idx.item())
            if self.rep.rotation_mode == "absolute":
                self.cmd_rot = int(ROTATION_BINS[ri])
            elif self.rep.rotation_mode == "hold_heavy_delta":
                # Untrained net still has 3-way head; map via delta then OK.
                # For hold_heavy we use a separate 5-logit layout only in random mode;
                # for untrained, use standard delta head (matched architecture for delta reps).
                delta = int(ROTATION_DELTAS[ri])
                self.cmd_rot = int(np.clip(self.cmd_rot + delta, -90, 90))
                self.cmd_rot = int(round(self.cmd_rot / 10.0) * 10)
            else:
                delta = int(ROTATION_DELTAS[ri])
                self.cmd_rot = int(np.clip(self.cmd_rot + delta, -90, 90))
                self.cmd_rot = int(round(self.cmd_rot / 10.0) * 10)
            if self.rep.thrust_mode == "discrete4":
                # Snap continuous sample to nearest bin (player-coarsened).
                bins = np.array([0.0, 0.25, 0.5, 1.0])
                thrust = float(bins[np.argmin(np.abs(bins - thrust))])
            return {"thrust": thrust, "rotation": self.cmd_rot}

        # random
        if self.rep.thrust_mode == "continuous":
            thrust = float(self.rng.uniform(0.0, 1.0))
        else:
            thrust = float(self.rng.choice([0.0, 0.25, 0.5, 1.0]))

        if self.rep.rotation_mode == "absolute":
            self.cmd_rot = int(self.rng.choice(list(ROTATION_BINS)))
        elif self.rep.rotation_mode == "hold_heavy_delta":
            layout = (-10, 0, 0, 0, 10)
            delta = int(self.rng.choice(layout))
            self.cmd_rot = int(np.clip(self.cmd_rot + delta, -90, 90))
            self.cmd_rot = int(round(self.cmd_rot / 10.0) * 10)
        else:
            delta = int(self.rng.choice(ROTATION_DELTAS))
            self.cmd_rot = int(np.clip(self.cmd_rot + delta, -90, 90))
            self.cmd_rot = int(round(self.cmd_rot / 10.0) * 10)
        return {"thrust": thrust, "rotation": self.cmd_rot}


def make_untrained(rep: RepSpec, seed: int) -> ContinuousThrustActorCritic:
    rot_mode = "absolute" if rep.rotation_mode == "absolute" else "delta"
    torch.manual_seed(seed)
    pol = ContinuousThrustActorCritic(
        hidden=128,
        rotation_mode=rot_mode,
        soft_thrust_prior=False,
        hold_attitude_prior=False,
    )
    pol.reset_parameters_clean()
    pol.eval()
    return pol


def classify_terminal(native: dict[str, Any] | None, status: str, contact: dict[str, Any] | None) -> dict[str, Any]:
    """Classify landing / near-miss / violations from pre-mutation contact snapshot."""
    src = native or {}
    rot = float(src.get("rotation", (contact or {}).get("rotation", 0.0)))
    vy = float(src.get("vy", (contact or {}).get("vy", 0.0)))
    vx = float(src.get("vx", 0.0))
    within = bool(src.get("within_pad", False))
    landable = bool(src.get("landable_contact", False))
    fuel = float(src.get("fuel", (contact or {}).get("fuel", 0.0)))
    frame_steps = None

    rot_ok = abs(rot) < 1e-6  # exact 0 after quantization settle
    vy_ok = vy < 0.15
    perfect = bool(src.get("perfect", False)) if status == "landed" else (rot_ok and vy < 0.075)

    violations = []
    if status == "timeout":
        return {
            "outcome": "timeout",
            "pad_aligned_contact": False,
            "violations": ["timeout_no_contact"],
            "near_miss": False,
            "rotation": rot,
            "vy": vy,
            "vx": vx,
            "within_pad": within,
            "landable_contact": landable,
            "fuel": fuel,
            "perfect": False,
            "hard": False,
        }

    if status in ("landed", "hard_landing"):
        return {
            "outcome": "perfect" if status == "landed" else "hard",
            "pad_aligned_contact": True,
            "violations": [],
            "near_miss": False,
            "rotation": rot,
            "vy": vy,
            "vx": vx,
            "within_pad": True,
            "landable_contact": True,
            "fuel": fuel,
            "perfect": status == "landed",
            "hard": status == "hard_landing",
            "designated": bool(src.get("designated", False)),
            "pad_x1": src.get("pad_x1"),
            "pad_x2": src.get("pad_x2"),
        }

    # crash
    if not landable:
        violations.append("terrain_or_non_landable")
    else:
        if not within:
            violations.append("not_within_pad")
        if not rot_ok:
            violations.append("rotation_nonzero")
        if not vy_ok:
            violations.append("vy_too_fast")

    pad_aligned = landable and within
    near_miss = False
    if pad_aligned and status == "crashed":
        fail_rot = not rot_ok
        fail_vy = not vy_ok
        n_fail = int(fail_rot) + int(fail_vy)
        if n_fail == 1:
            if fail_rot and abs(rot) <= NEAR_MISS_ROT_TOL_DEG and vy_ok:
                near_miss = True
            if fail_vy and rot_ok and vy < NEAR_MISS_VY_TOL:
                near_miss = True

    top = violations[0] if violations else "unknown"
    return {
        "outcome": "crash",
        "pad_aligned_contact": pad_aligned,
        "violations": violations,
        "top_violation": top,
        "near_miss": near_miss,
        "rotation": rot,
        "vy": vy,
        "vx": vx,
        "within_pad": within,
        "landable_contact": landable,
        "fuel": fuel,
        "perfect": False,
        "hard": False,
        "designated": bool(src.get("designated", False)),
        "pad_x1": src.get("pad_x1"),
        "pad_x2": src.get("pad_x2"),
        "joint_violation_key": "+".join(sorted(violations)) if violations else "none",
    }


def run_episode(
    session: UpstreamSession,
    *,
    start: dict[str, float],
    sampler: ActionSampler,
    action_repeat: int,
    max_steps: int,
) -> tuple[dict[str, Any], int]:
    msg = session.call(
        {
            "cmd": "reset",
            "config": {
                "maxSteps": max_steps,
                "lockedCamera": True,
                "bonuses": False,
                "rewardMode": "touchdown_v1",
                "start": start,
            },
        }
    )
    obs_raw = msg["observation"]
    obs = np.array(
        [
            obs_raw["x"],
            obs_raw["y"],
            obs_raw["vx"],
            obs_raw["vy"],
            obs_raw["rotation"],
            obs_raw["fuel"],
            obs_raw.get("altitude", 0),
            obs_raw.get("dx", 0),
            obs_raw.get("dy", 0),
            obs_raw.get("thrust", 0),
        ],
        dtype=np.float32,
    )
    # Match training obs dim — check actual obs from host via env if needed.
    # Upstream host observe may differ; use keys present.
    sampler.reset_cmd(start["rotation"])
    frames = 0
    status = "flying"
    native = None
    contact = None
    steps = 0
    while True:
        command = sampler.sample(obs)
        for _ in range(action_repeat):
            step_msg = session.call({"cmd": "step", "action": command})
            frames += 1
            steps += 1
            result = step_msg["result"]
            status = result.get("status", status)
            if result.get("done"):
                native = step_msg.get("step", {}).get("nativeOutcome") or result.get("nativeOutcome")
                contact = step_msg.get("step", {}).get("contactMetrics")
                # Prefer result-level nativeOutcome
                native = result.get("nativeOutcome") or native
                classified = classify_terminal(native, status, contact)
                classified["status"] = status
                classified["steps"] = int(result.get("steps", steps))
                classified["frame"] = classified["steps"]
                classified["fuel"] = float(
                    (native or {}).get("fuel", (contact or {}).get("fuel", 0.0))
                )
                classified["command_last"] = command
                return classified, frames
            # update obs
            o = step_msg["observation"]
            obs = np.array(
                [
                    o["x"],
                    o["y"],
                    o["vx"],
                    o["vy"],
                    o["rotation"],
                    o["fuel"],
                    o.get("altitude", 0),
                    o.get("dx", 0),
                    o.get("dy", 0),
                    o.get("thrust", o.get("thrustBuild", 0)),
                ],
                dtype=np.float32,
            )


def obs_dim_ok() -> None:
    # ContinuousThrustActorCritic expects OBS_DIM=10
    pass


def run_cell(
    *,
    budget: DiagnosticBudget,
    session: UpstreamSession,
    start_name: str,
    start_fn: Callable[[int], dict],
    rep: RepSpec,
    policy_mode: str,
    n: int,
    seed_start: int,
) -> dict[str, Any]:
    rng = np.random.default_rng(91000 + seed_start + sum(ord(c) for c in rep.name) % 1000)
    policy = None
    if policy_mode == "untrained":
        if rep.rotation_mode == "hold_heavy_delta":
            # Matched clean delta network (layout hold-heavy is random-only).
            policy = make_untrained(
                RepSpec(rep.name, rep.thrust_mode, "delta", rep.action_repeat, rep.player_mapping),
                seed=42 + seed_start % 97,
            )
        else:
            policy = make_untrained(rep, seed=42 + seed_start % 97)
    sampler = ActionSampler(rep, policy_mode, policy, rng)

    episodes = []
    frames_used = 0
    for i in range(n):
        seed = seed_start + i
        assert_seed_allowed(seed, context="explore_v5")
        start = start_fn(seed)
        if not budget.can_afford(max(1, MAX_STEPS)):
            break
        try:
            ep, fr = run_episode(
                session,
                start=start,
                sampler=sampler,
                action_repeat=rep.action_repeat,
                max_steps=MAX_STEPS,
            )
        except Exception as exc:  # noqa: BLE001
            ep = {"outcome": "error", "error": str(exc), "violations": ["error"], "near_miss": False}
            fr = 0
        ep["seed"] = seed
        episodes.append(ep)
        frames_used += fr
        budget.charge(fr, reason=f"{start_name}/{rep.name}/{policy_mode}/ep{i}")

    def count(pred):
        return sum(1 for e in episodes if pred(e))

    n_done = len(episodes)
    perfect = count(lambda e: e.get("outcome") == "perfect")
    hard = count(lambda e: e.get("outcome") == "hard")
    land = perfect + hard
    near = count(lambda e: e.get("near_miss"))
    pad_c = count(lambda e: e.get("pad_aligned_contact"))
    contact_any = count(lambda e: e.get("landable_contact") or e.get("outcome") in ("perfect", "hard", "crash"))
    # landable_contact true or crash/land
    landable_c = count(lambda e: e.get("landable_contact") or e.get("outcome") in ("perfect", "hard"))
    crash = count(lambda e: e.get("outcome") == "crash")
    timeout = count(lambda e: e.get("outcome") == "timeout")

    single_v = Counter()
    joint_v = Counter()
    for e in episodes:
        for v in e.get("violations") or []:
            single_v[v] += 1
        joint_v[e.get("joint_violation_key") or ("none" if e.get("outcome") in ("perfect", "hard") else "unknown")] += 1

    top_violation = single_v.most_common(1)[0][0] if single_v else "none"
    return {
        "start": start_name,
        "rep": rep.name,
        "policy": policy_mode,
        "action_repeat": rep.action_repeat,
        "thrust_mode": rep.thrust_mode,
        "rotation_mode": rep.rotation_mode,
        "player_mapping": rep.player_mapping,
        "n": n_done,
        "seed_start": seed_start,
        "max_steps": MAX_STEPS,
        "diagnostic_frames": frames_used,
        "counts": {
            "perfect": perfect,
            "hard": hard,
            "land": land,
            "near_miss": near,
            "pad_aligned_contact": pad_c,
            "landable_contact": landable_c,
            "crash": crash,
            "timeout": timeout,
        },
        "landing_rate": land / n_done if n_done else 0.0,
        "landing_wilson95": wilson(land, n_done),
        "near_miss_rate": near / n_done if n_done else 0.0,
        "near_miss_wilson95": wilson(near, n_done),
        "pad_aligned_contact_rate": pad_c / n_done if n_done else 0.0,
        "top_violation": top_violation,
        "single_condition_violations": dict(single_v),
        "joint_violations": dict(joint_v),
        "episodes": episodes,
    }


def open_loop_feasibility(budget: DiagnosticBudget, session: UpstreamSession) -> list[dict]:
    """Labeled physical-feasibility check ONLY — not a policy."""
    rows = []
    for start_name, start_fn in STARTS.items():
        eps = []
        frames = 0
        for i in range(8):
            seed = 540_000 + (0 if start_name == "L0" else 100) + i
            assert_seed_allowed(seed)
            start = start_fn(seed)
            msg = session.call(
                {
                    "cmd": "reset",
                    "config": {
                        "maxSteps": MAX_STEPS,
                        "lockedCamera": True,
                        "bonuses": False,
                        "rewardMode": "touchdown_v1",
                        "start": start,
                    },
                }
            )
            done = False
            while not done:
                step_msg = session.call(
                    {"cmd": "step", "action": {"thrust": 0.22, "rotation": 0}}
                )
                frames += 1
                result = step_msg["result"]
                done = bool(result["done"])
                if done:
                    native = result.get("nativeOutcome")
                    contact = step_msg.get("step", {}).get("contactMetrics")
                    cls = classify_terminal(native, result["status"], contact)
                    cls["seed"] = seed
                    eps.append(cls)
        budget.charge(frames, reason=f"open_loop_feasibility/{start_name}")
        land = sum(1 for e in eps if e["outcome"] in ("perfect", "hard"))
        rows.append(
            {
                "label": "OPEN_LOOP_SOFT_HOLD_FEASIBILITY_ONLY",
                "start": start_name,
                "n": len(eps),
                "land": land,
                "counts": Counter(e["outcome"] for e in eps),
                "diagnostic_frames": frames,
                "episodes": eps,
            }
        )
    return rows


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "logs").mkdir(exist_ok=True)
    budget = DiagnosticBudget(hard_cap=DIAG_CAP)
    assert_seeds_allowed(range(SEED_START, SEED_START + 500))

    # Offline rotation analysis first (0 frames).
    import subprocess

    subprocess.check_call([sys.executable, str(HERE / "analyze_rotation_hold.py")])

    session = UpstreamSession.start()
    cells: list[dict[str, Any]] = []
    try:
        # Feasibility (small).
        feas = open_loop_feasibility(budget, session)
        (OUT / "logs" / "feasibility_open_loop.json").write_text(
            json.dumps(feas, indent=2) + "\n"
        )

        # Primary matrix: all reps × both starts × random.
        seed_cursor = SEED_START
        for start_name, start_fn in STARTS.items():
            for rep in REPS:
                if budget.remaining() < N_EPISODES * 40:
                    print("STOP matrix: remaining", budget.remaining())
                    break
                print(f"CELL random {start_name} {rep.name} spent={budget.spent}", flush=True)
                cell = run_cell(
                    budget=budget,
                    session=session,
                    start_name=start_name,
                    start_fn=start_fn,
                    rep=rep,
                    policy_mode="random",
                    n=N_EPISODES,
                    seed_start=seed_cursor,
                )
                cells.append(cell)
                seed_cursor += 1000
                print(
                    f"  land={cell['counts']['land']} near={cell['counts']['near_miss']} "
                    f"pad={cell['counts']['pad_aligned_contact']} top={cell['top_violation']} "
                    f"frames={cell['diagnostic_frames']}",
                    flush=True,
                )

        # Untrained on key reps only (matched seeds offset).
        key_reps = [r for r in REPS if r.name in ("cont_delta_ar1", "cont_delta_ar8", "cont_holdheavy_ar8")]
        for start_name, start_fn in STARTS.items():
            for rep in key_reps:
                if budget.remaining() < N_EPISODES * 40:
                    print("STOP untrained: remaining", budget.remaining())
                    break
                print(f"CELL untrained {start_name} {rep.name} spent={budget.spent}", flush=True)
                cell = run_cell(
                    budget=budget,
                    session=session,
                    start_name=start_name,
                    start_fn=start_fn,
                    rep=rep,
                    policy_mode="untrained",
                    n=N_EPISODES,
                    seed_start=seed_cursor,
                )
                cells.append(cell)
                seed_cursor += 1000
                print(
                    f"  land={cell['counts']['land']} near={cell['counts']['near_miss']} "
                    f"pad={cell['counts']['pad_aligned_contact']} top={cell['top_violation']}",
                    flush=True,
                )
    except DiagnosticBudgetExhausted as exc:
        print("BUDGET EXHAUSTED", exc, flush=True)
    finally:
        session.close()

    # Summaries without huge episode dumps in table file.
    summary_cells = []
    for c in cells:
        slim = {k: v for k, v in c.items() if k != "episodes"}
        summary_cells.append(slim)

    # Aggregate violation table across random L0 cont_delta_ar1 for detail.
    violation_focus = next(
        (c for c in cells if c["start"] == "L0" and c["rep"] == "cont_delta_ar1" and c["policy"] == "random"),
        None,
    )

    out = {
        "diagnostic_hard_cap": DIAG_CAP,
        "diagnostic_budget": budget.snapshot(),
        "near_miss_definition": {
            "pad_aligned_contact": "landable_contact AND within_pad",
            "sole_failure_tolerances": {
                "rotation_deg_abs_le": NEAR_MISS_ROT_TOL_DEG,
                "vy_lt": NEAR_MISS_VY_TOL,
                "safe_vy": 0.15,
            },
            "rule": (
                "Near-miss iff pad-aligned contact, not a landing, exactly one of "
                "{rotation==0, vy<0.15} fails, and that failure is within tolerance."
            ),
        },
        "n_episodes_per_cell": N_EPISODES,
        "max_steps": MAX_STEPS,
        "seed_start": SEED_START,
        "cells": summary_cells,
        "violation_detail_L0_cont_delta_ar1_random": {
            "single": violation_focus["single_condition_violations"] if violation_focus else {},
            "joint": violation_focus["joint_violations"] if violation_focus else {},
            "episode_terminals": [
                {
                    "seed": e["seed"],
                    "outcome": e["outcome"],
                    "rotation": e.get("rotation"),
                    "vy": e.get("vy"),
                    "vx": e.get("vx"),
                    "within_pad": e.get("within_pad"),
                    "landable_contact": e.get("landable_contact"),
                    "near_miss": e.get("near_miss"),
                    "violations": e.get("violations"),
                    "frame": e.get("frame"),
                    "fuel": e.get("fuel"),
                }
                for e in (violation_focus["episodes"] if violation_focus else [])
            ],
        },
        "any_random_or_untrained_landing": any(c["counts"]["land"] > 0 for c in cells),
    }
    (OUT / "logs" / "explore_cells.json").write_text(json.dumps(out, indent=2) + "\n")
    # Full episodes separately
    (OUT / "logs" / "explore_cells_full.json").write_text(json.dumps(cells, indent=2) + "\n")
    (OUT / "logs" / "diagnostic_budget.json").write_text(
        json.dumps(budget.snapshot(), indent=2) + "\n"
    )
    print("DONE spent", budget.spent, "remaining", budget.remaining())
    print("any landing", out["any_random_or_untrained_landing"])


if __name__ == "__main__":
    main()
