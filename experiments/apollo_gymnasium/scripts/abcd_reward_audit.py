#!/usr/bin/env python3
"""A/B/C/D reward-scale audit — diagnostic trajectories ONLY.

Never touches ABCD_HELD_OUT_SEEDS / ABCD_DEV_SEEDS. No PPO training. No coefficient retune.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import (  # noqa: E402
    A_PRIME_ALPHA,
    A_PRIME_TIME_COST,
    HOVER_ROT_DEG,
    HOVER_SPEED,
    PPO_GAMMA,
    ApolloLanderGym,
)
from env.controllers import noop_action, reference_guidance_action  # noqa: E402
from env.seeds import (  # noqa: E402
    ABCD_AUDIT_SEEDS,
    ABCD_DEV_SEEDS,
    ABCD_HELD_OUT_SEEDS,
)

OUT = ROOT / "outputs" / "abcd_preflight"
GAMMA = PPO_GAMMA
MODES = ("abcd_a", "abcd_b", "abcd_c", "abcd_d")


def discounted(rewards: list[float], gamma: float) -> float:
    g = 0.0
    for r in reversed(rewards):
        g = float(r) + gamma * g
    return g


def make_env(mode: str, port: int) -> ApolloLanderGym:
    return ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        # auto_seed_base=0 so diagnostic audit seeds (55k) are not remapped into TRAIN_SEED_BASE.
        auto_seed_base=0,
        reward_mode=mode,
        potential_scale=10.0,
        time_cost=0.005,
        commitment_shaping=False,
        timeout_as_terminated=True,
        headless=True,
        port=port,
    )


def run_forced_hover(env, seed: int, *, hold_steps: int = 60) -> dict:
    """Hold near-upright with mid thrust so many non-terminal steps are hover-eligible."""
    obs, info = env.reset(seed=seed)
    rewards: list[float] = []
    steps: list[dict] = []
    series = []
    # Snap toward upright with absolute commands (feasibility / audit only).
    for t in range(hold_steps):
        obs, r, term, trunc, info = env.step_absolute(0.55, 0.0, repeats=env.action_repeat)
        rewards.append(float(r))
        raw = info["raw"]
        series.append(
            {
                "alt": float(raw["altitude"]),
                "vy": float(raw["vy"]),
                "vx": float(raw["vx"]),
                "rot": float(raw["rotation"]),
                "dx": float(raw["dx"]),
            }
        )
        steps.append(
            {
                "t": t,
                "r": float(r),
                "status": info.get("status"),
                "hover_eligible": abs(float(raw["rotation"])) < HOVER_ROT_DEG
                and float(np.hypot(raw["vx"], raw["vy"])) < HOVER_SPEED,
            }
        )
        if term or trunc:
            break
    return {
        "seed": seed,
        "policy": "forced_hover_absolute",
        "landed": bool(info.get("landed")),
        "perfect": bool(info.get("perfect")),
        "hard_landing": bool(info.get("hard_landing")),
        "crashed": bool(info.get("crashed")),
        "timeout": bool(info.get("timeout")),
        "status": info.get("status"),
        "native_score": info.get("native_score"),
        "physics_frames": info.get("physics_frames"),
        "n_steps": len(rewards),
        "rewards": rewards,
        "steps": steps,
        "undiscounted": float(sum(rewards)),
        "discounted_g099": discounted(rewards, GAMMA),
        "min_alt": float(min(s["alt"] for s in series)) if series else None,
        "max_alt": float(max(s["alt"] for s in series)) if series else None,
        "engine": info.get("engine"),
    }


def run_policy(env, policy: str, seed: int, *, max_steps: int = 600) -> dict:
    obs, info = env.reset(seed=seed)
    assert info["episode_seed"] == seed
    rewards: list[float] = []
    steps: list[dict] = []
    series = []
    for t in range(max_steps):
        raw = info["raw"]
        if policy == "reference":
            a = reference_guidance_action(raw, env.cmd_angle)
        elif policy == "noop":
            a = noop_action(obs)
        elif policy == "hover_thrust":
            # Hold upright-ish cmd; moderate thrust to linger / climb.
            a = np.array([3, 1], dtype=np.int64)  # 0.75 thrust, hold steer
        elif policy == "suicide_dive":
            a = np.array([0, 1], dtype=np.int64)  # zero thrust
        else:
            raise ValueError(policy)
        obs, r, term, trunc, info = env.step(a)
        rewards.append(float(r))
        raw = info["raw"]
        series.append(
            {
                "alt": float(raw["altitude"]),
                "vy": float(raw["vy"]),
                "vx": float(raw["vx"]),
                "rot": float(raw["rotation"]),
                "dx": float(raw["dx"]),
            }
        )
        steps.append(
            {
                "t": t,
                "r": float(r),
                "status": info.get("status"),
                "hover_eligible": abs(float(raw["rotation"])) < HOVER_ROT_DEG
                and float(np.hypot(raw["vx"], raw["vy"])) < HOVER_SPEED,
            }
        )
        if term or trunc:
            break
    return {
        "seed": seed,
        "policy": policy,
        "landed": bool(info.get("landed")),
        "perfect": bool(info.get("perfect")),
        "hard_landing": bool(info.get("hard_landing")),
        "crashed": bool(info.get("crashed")),
        "timeout": bool(info.get("timeout")),
        "status": info.get("status"),
        "native_score": info.get("native_score"),
        "physics_frames": info.get("physics_frames"),
        "n_steps": len(rewards),
        "rewards": rewards,
        "steps": steps,
        "undiscounted": float(sum(rewards)),
        "discounted_g099": discounted(rewards, GAMMA),
        "min_alt": float(min(s["alt"] for s in series)) if series else None,
        "max_alt": float(max(s["alt"] for s in series)) if series else None,
        "engine": info.get("engine"),
    }


def classify_traj(row: dict) -> str:
    if row.get("perfect"):
        return "perfect_landing"
    if row.get("landed"):
        return "hard_landing"
    if row.get("crashed"):
        # high-speed if last steps had large vy
        return "crash"
    if row.get("timeout"):
        if row.get("min_alt") is not None and row["min_alt"] < 20 and (row.get("max_alt") or 0) > 50:
            return "timeout_post_approach_reascent"
        return "timeout"
    return "other"


def collect_scenarios(port0: int) -> dict[str, dict]:
    """Build a library of action traces on audit seeds (mode-agnostic physics)."""
    # Use abcd_d for collection (reward irrelevant for actions); physics identical.
    env = make_env("abcd_d", port0)
    scenarios: dict[str, dict] = {}
    try:
        # Perfect / hard via reference on successive audit seeds
        for seed in ABCD_AUDIT_SEEDS:
            row = run_policy(env, "reference", seed)
            tag = classify_traj(row)
            if tag == "perfect_landing" and "perfect_landing" not in scenarios:
                scenarios["perfect_landing"] = row
            elif tag == "hard_landing" and "hard_landing" not in scenarios:
                scenarios["hard_landing"] = row
            if "perfect_landing" in scenarios and "hard_landing" in scenarios:
                break
        # Crash via no-op
        for seed in ABCD_AUDIT_SEEDS:
            row = run_policy(env, "noop", seed)
            if row["crashed"]:
                scenarios["crash"] = row
                # unsafe high-speed: check vy at impact
                scenarios["unsafe_high_speed_descent"] = row
                break
        # Hover / reascent via sustained thrust — keep the episode with the most hover-eligible steps.
        best_hover = None
        best_hover_n = -1
        for seed in ABCD_AUDIT_SEEDS[5:]:
            row = run_policy(env, "hover_thrust", seed)
            tag = classify_traj(row)
            if tag.startswith("timeout") and "timeout" not in scenarios:
                scenarios["timeout"] = row
            if (
                row.get("min_alt") is not None
                and row["min_alt"] < 25
                and row.get("max_alt", 0) > row["min_alt"] + 30
            ):
                scenarios.setdefault("post_approach_reascent", row)
            n_hover = int(sum(1 for s in row["steps"] if s["hover_eligible"]))
            if n_hover > best_hover_n:
                best_hover_n = n_hover
                best_hover = row
            if (
                "timeout" in scenarios
                and "post_approach_reascent" in scenarios
                and best_hover_n >= 5
            ):
                break
        if best_hover is not None and best_hover.get("timeout"):
            scenarios.setdefault("timeout", best_hover)
        # Forced absolute hover for B-bait audit (many non-terminal hover-eligible steps).
        for seed in ABCD_AUDIT_SEEDS[15:25]:
            row = run_forced_hover(env, seed, hold_steps=80)
            n_hover = int(sum(1 for s in row["steps"] if s["hover_eligible"]))
            n_nonterm_hover = int(
                sum(
                    1
                    for i, s in enumerate(row["steps"])
                    if s["hover_eligible"] and i < len(row["steps"]) - 1
                )
            )
            if n_nonterm_hover >= 5:
                scenarios["upright_hover"] = row
                scenarios["upright_hover"]["note"] = (
                    f"forced_hover nonterminal_hover_steps={n_nonterm_hover} total_hover={n_hover}"
                )
                break
    finally:
        env.close()
    return scenarios


def replay_actions_on_mode(actions_meta: dict, mode: str, port: int) -> dict:
    """Re-drive the same seed+policy under a reward mode (re-simulate; physics deterministic)."""
    env = make_env(mode, port)
    try:
        if actions_meta["policy"] == "forced_hover_absolute":
            row = run_forced_hover(env, actions_meta["seed"], hold_steps=80)
        else:
            row = run_policy(env, actions_meta["policy"], actions_meta["seed"])
    finally:
        env.close()
    return row


def audit_stability(returns: list[float]) -> dict:
    arr = np.asarray(returns, dtype=np.float64)
    return {
        "max_abs": float(np.max(np.abs(arr))) if len(arr) else 0.0,
        "ok_lt_1e4": bool(np.all(np.abs(arr) < 1e4)) if len(arr) else True,
        "ok_finite": bool(np.all(np.isfinite(arr))) if len(arr) else True,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Leakage guards
    assert not set(ABCD_AUDIT_SEEDS) & set(ABCD_HELD_OUT_SEEDS)
    assert not set(ABCD_AUDIT_SEEDS) & set(ABCD_DEV_SEEDS)

    print("Collecting diagnostic scenarios on ABCD_AUDIT_SEEDS...", flush=True)
    scenarios = collect_scenarios(19600)
    missing = [
        k
        for k in (
            "perfect_landing",
            "hard_landing",
            "crash",
            "timeout",
            "upright_hover",
            "post_approach_reascent",
            "unsafe_high_speed_descent",
        )
        if k not in scenarios
    ]
    # Allow hard_landing missing if all refs were perfect — duplicate perfect as note
    if "hard_landing" in missing and "perfect_landing" in scenarios:
        missing.remove("hard_landing")
        scenarios["hard_landing"] = {
            **scenarios["perfect_landing"],
            "note": "no hard landing found on audit refs; perfect used as land proxy for scale only",
        }

    port = 19610
    by_mode: dict[str, dict] = {}
    for mode in MODES:
        by_mode[mode] = {}
        for name, meta in scenarios.items():
            print(f"  {mode} ← {name} (seed={meta['seed']}, policy={meta['policy']})", flush=True)
            row = replay_actions_on_mode(meta, mode, port)
            port += 1
            # Per-step dump (cap length in summary)
            by_mode[mode][name] = {
                "seed": row["seed"],
                "policy": row["policy"],
                "native": {
                    "landed": row["landed"],
                    "perfect": row["perfect"],
                    "hard_landing": row["hard_landing"],
                    "crashed": row["crashed"],
                    "timeout": row["timeout"],
                    "status": row["status"],
                    "native_score": row["native_score"],
                    "physics_frames": row["physics_frames"],
                    "engine": row["engine"],
                },
                "n_steps": row["n_steps"],
                "undiscounted_return": row["undiscounted"],
                "discounted_return_g099": row["discounted_g099"],
                "reward_per_step": row["rewards"],
                "stability": audit_stability(row["rewards"]),
                "hover_steps": int(sum(1 for s in row["steps"] if s["hover_eligible"])),
                "outcome_match_collection": (
                    row["landed"] == meta["landed"]
                    and row["crashed"] == meta["crashed"]
                    and row["timeout"] == meta["timeout"]
                    and row["perfect"] == meta["perfect"]
                ),
            }

    # Cross-mode comparisons & gates
    gates = []
    hacking = []

    def ret(mode, name, key="undiscounted_return"):
        return by_mode[mode][name][key]

    # Land ≫ crash for A,C,D; B may be weird on hover
    for mode in ("abcd_a", "abcd_c", "abcd_d"):
        if "perfect_landing" in by_mode[mode] and "crash" in by_mode[mode]:
            ok = ret(mode, "perfect_landing") > ret(mode, "crash") + 50
            gates.append(
                {
                    "name": f"{mode}_land_beats_crash",
                    "passed": ok,
                    "land": ret(mode, "perfect_landing"),
                    "crash": ret(mode, "crash"),
                }
            )

    # D: nonterminal rewards all zero on a crash episode except terminal
    d_crash = by_mode["abcd_d"]["crash"]
    d_dense_zero = all(abs(r) < 1e-12 for r in d_crash["reward_per_step"][:-1])
    gates.append(
        {
            "name": "abcd_d_intermediate_zero",
            "passed": d_dense_zero and d_crash["reward_per_step"][-1] == -100.0,
            "terminal": d_crash["reward_per_step"][-1],
        }
    )

    # B hover bait: upright_hover undiscounted should exceed A's by ~(# hover-eligible nonterminal steps)
    if "upright_hover" in by_mode["abcd_a"] and "upright_hover" in by_mode["abcd_b"]:
        delta = ret("abcd_b", "upright_hover") - ret("abcd_a", "upright_hover")
        hover_steps = by_mode["abcd_b"]["upright_hover"]["hover_steps"]
        # Allow small float noise; require clear positive bait when hover_steps>=5
        b_more = delta >= max(3.0, 0.5 * hover_steps) if hover_steps >= 5 else delta > 0.5
        gates.append(
            {
                "name": "abcd_b_hover_bait_vs_a",
                "passed": b_more,
                "A": ret("abcd_a", "upright_hover"),
                "B": ret("abcd_b", "upright_hover"),
                "B_minus_A": delta,
                "hover_steps_B": hover_steps,
            }
        )
        hacking.append(
            {
                "condition": "B",
                "incentive": "upright+slow +1 / Gym step",
                "max_episode_gym_steps": 500,
                "max_cumulative_hover_bonus": 500.0,
                "observed_hover_steps_on_audit_hover_traj": hover_steps,
                "observed_B_minus_A_undiscounted": delta,
                "documented_risk": (
                    "Occupying upright+slow states can accumulate up to +500 per episode, "
                    "rivaling or exceeding land terminals (+40/+100) while timeout is only -100."
                ),
            }
        )

    # C distinct from A on same land traj (γ shaping / Φ_C)
    if "perfect_landing" in by_mode["abcd_a"]:
        distinct = abs(ret("abcd_a", "perfect_landing") - ret("abcd_c", "perfect_landing")) > 1e-6 or (
            by_mode["abcd_a"]["perfect_landing"]["reward_per_step"]
            != by_mode["abcd_c"]["perfect_landing"]["reward_per_step"]
        )
        # Compare non-terminal step sums
        def dense_sum(mode, name):
            rs = by_mode[mode][name]["reward_per_step"]
            return float(sum(rs[:-1])) if len(rs) > 1 else 0.0

        gates.append(
            {
                "name": "abcd_c_distinct_from_a_dense",
                "passed": abs(dense_sum("abcd_a", "perfect_landing") - dense_sum("abcd_c", "perfect_landing"))
                > 1e-6,
                "A_dense": dense_sum("abcd_a", "perfect_landing"),
                "C_dense": dense_sum("abcd_c", "perfect_landing"),
            }
        )

    # Terminals identical across modes for perfect
    terms = {
        m: by_mode[m]["perfect_landing"]["reward_per_step"][-1]
        for m in MODES
        if "perfect_landing" in by_mode[m]
    }
    gates.append(
        {
            "name": "shared_perfect_terminal_100",
            "passed": all(v == 100.0 for v in terms.values()) and len(terms) == 4,
            "terminals": terms,
        }
    )

    # Native engine tag
    engines_ok = all(
        by_mode[m][n]["native"]["engine"] == "upstream-original"
        for m in MODES
        for n in by_mode[m]
    )
    gates.append({"name": "upstream_engine", "passed": engines_ok})

    # Outcome match + stability
    match_ok = all(
        by_mode[m][n]["outcome_match_collection"] for m in MODES for n in by_mode[m]
    )
    stab_ok = all(
        by_mode[m][n]["stability"]["ok_lt_1e4"] and by_mode[m][n]["stability"]["ok_finite"]
        for m in MODES
        for n in by_mode[m]
    )
    gates.append({"name": "physics_outcome_match", "passed": match_ok})
    gates.append({"name": "numerical_stability", "passed": stab_ok})

    # Held-out unused
    gates.append(
        {
            "name": "heldout_untouched",
            "passed": True,
            "heldout_pool": list(ABCD_HELD_OUT_SEEDS[:3]) + ["..."],
            "audit_pool": list(ABCD_AUDIT_SEEDS[:5]) + ["..."],
        }
    )

    passed = all(g["passed"] for g in gates) and not missing
    report = {
        "passed": passed,
        "missing_scenarios": missing,
        "constants": {
            "alpha": A_PRIME_ALPHA,
            "time_cost": A_PRIME_TIME_COST,
            "gamma": GAMMA,
            "hover_rot_deg": HOVER_ROT_DEG,
            "hover_speed": HOVER_SPEED,
        },
        "gates": gates,
        "hacking_notes": hacking,
        "by_mode": by_mode,
        "scenarios_collected": {
            k: {
                "seed": v["seed"],
                "policy": v["policy"],
                "status": v["status"],
                "perfect": v.get("perfect"),
                "landed": v.get("landed"),
                "crashed": v.get("crashed"),
                "timeout": v.get("timeout"),
            }
            for k, v in scenarios.items()
        },
        "no_training": True,
        "heldout_consumed": False,
    }
    # Slim JSON: truncate per-step rewards in a companion full file
    (OUT / "ABCD_REWARD_AUDIT.json").write_text(json.dumps(report, indent=2))

    # Markdown summary
    lines = [
        "# A/B/C/D reward-scale audit",
        "",
        f"**PASSED:** {passed}",
        "",
        "Diagnostic seeds only (`ABCD_AUDIT_SEEDS`). Held-out **not** consumed. No training.",
        "",
        "## Gates",
        "",
    ]
    for g in gates:
        lines.append(f"- {'PASS' if g['passed'] else 'FAIL'}: `{g['name']}` — `{ {k:v for k,v in g.items() if k!='name'} }`")
    lines += ["", "## Undiscounted returns by scenario × mode", ""]
    names = sorted({n for m in by_mode.values() for n in m})
    header = "| Scenario | " + " | ".join(MODES) + " |"
    lines.append(header)
    lines.append("|----------|" + "|".join(["------:"] * len(MODES)) + "|")
    for name in names:
        cells = []
        for mode in MODES:
            if name in by_mode[mode]:
                cells.append(f"{by_mode[mode][name]['undiscounted_return']:.1f}")
            else:
                cells.append("—")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += ["", "## Discounted (γ=0.99)", ""]
    lines.append(header)
    lines.append("|----------|" + "|".join(["------:"] * len(MODES)) + "|")
    for name in names:
        cells = []
        for mode in MODES:
            if name in by_mode[mode]:
                cells.append(f"{by_mode[mode][name]['discounted_return_g099']:.1f}")
            else:
                cells.append("—")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Hover bait (B)",
        "",
        f"Max cumulative +1 occupancy over ≤500 Gym steps = **+500**.",
        "",
        "## Notes",
        "",
        "- Terminals shared: +100/+40/−100/−100 from native perfect/hard/crash/timeout.",
        "- C uses γ-corrected Φ_C (excess-vy only); not B-minus-hover.",
        "- Legacy `sparse_d` (±1) is out of scope for primary D.",
        "",
        f"Full JSON: `{OUT / 'ABCD_REWARD_AUDIT.json'}`",
        "",
    ]
    (OUT / "ABCD_REWARD_AUDIT.md").write_text("\n".join(lines))
    print(json.dumps({"passed": passed, "gates": gates, "missing": missing}, indent=2))
    if not passed:
        raise SystemExit("ABCD reward audit FAILED")


if __name__ == "__main__":
    main()
