#!/usr/bin/env python3
"""Decompose training-reward components on expert vs PPO trajectories (no training)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import STEER_DELTAS, THRUST_LEVELS, ApolloLanderGym, _potential  # noqa: E402
from env.controllers import noop_action, reference_continuous_command, reference_guidance_action  # noqa: E402
from env.starts import resolve_start  # noqa: E402

OUT = ROOT / "outputs" / "root_cause"


def component_deltas(prev_obs: np.ndarray, obs: np.ndarray) -> dict[str, float]:
    """Potential-term contributions matching _potential (normalized features)."""
    return {
        "dx": -1.0 * (abs(float(obs[0])) - abs(float(prev_obs[0]))),
        "alt": -1.2 * (max(float(obs[1]), 0.0) - max(float(prev_obs[1]), 0.0)),
        "vx": -0.8 * (abs(float(obs[2])) - abs(float(prev_obs[2]))),
        "vy": -1.0 * (max(float(obs[3]), 0.0) - max(float(prev_obs[3]), 0.0)),
        "ang": -1.5 * (abs(float(obs[4])) - abs(float(prev_obs[4]))),
    }


def run_episode(env, policy: str, model, seed: int) -> dict:
    obs, info = env.reset(seed=seed)
    prev_obs = obs.copy()
    prev_phi = _potential(obs)
    rows = []
    step_i = 0
    while True:
        if policy == "noop":
            action = noop_action(obs)
            obs, reward, term, trunc, info = env.step(action)
        elif policy == "reference_continuous":
            cmd = reference_continuous_command(info["raw"])
            obs, reward, term, trunc, info = env.step_absolute(
                cmd["thrust"], cmd["rotation"], repeats=1
            )
        elif policy == "reference_multidiscrete":
            action = reference_guidance_action(info["raw"], env.cmd_angle)
            obs, reward, term, trunc, info = env.step(action)
        elif policy == "ppo":
            action, _ = model.predict(obs, deterministic=True)
            obs, reward, term, trunc, info = env.step(action)
        else:
            raise ValueError(policy)

        phi = _potential(obs)
        comps = component_deltas(prev_obs, obs)
        delta_phi = float(phi - prev_phi)
        time_pen = -0.05
        # Reconstruct: nonterminal reward ≈ delta_phi + time_pen; terminal replaces dense
        is_terminal_step = bool(term or trunc)
        rows.append(
            {
                "t": step_i,
                "physics_frames": int(info["physics_frames"]),
                "reward": float(reward),
                "delta_phi": delta_phi,
                "time_pen": time_pen,
                "comps": comps,
                "terminated": bool(term),
                "truncated": bool(trunc),
                "status": info.get("status"),
                "native_score": info.get("native_score"),
                "landed": bool(info.get("landed")),
                "crashed": bool(info.get("crashed")),
                "raw_alt": float(info["raw"].get("altitude", 0)),
                "raw_vy": float(info["raw"].get("vy", 0)),
                "raw_rot": float(info["raw"].get("rotation", 0)),
                "is_terminal_step": is_terminal_step,
            }
        )
        prev_obs = obs.copy()
        prev_phi = phi
        step_i += 1
        if term or trunc:
            break

    dense = [r for r in rows if not r["is_terminal_step"]]
    terminal = rows[-1] if rows else None
    summary = {
        "policy": policy,
        "seed": seed,
        "n_gym_steps": len(rows),
        "physics_frames": rows[-1]["physics_frames"] if rows else 0,
        "status": terminal["status"] if terminal else None,
        "landed": terminal["landed"] if terminal else False,
        "crashed": terminal["crashed"] if terminal else False,
        "native_score": terminal["native_score"] if terminal else None,
        "sum_reward": float(sum(r["reward"] for r in rows)),
        "sum_delta_phi": float(sum(r["delta_phi"] for r in dense)),
        "sum_time_pen": float(sum(r["time_pen"] for r in dense)),
        "sum_comps": {
            k: float(sum(r["comps"][k] for r in dense)) for k in ("dx", "alt", "vx", "vy", "ang")
        },
        "terminal_reward": float(terminal["reward"]) if terminal else 0.0,
        "mean_abs_dense_reward": float(np.mean([abs(r["reward"]) for r in dense]))
        if dense
        else 0.0,
        "mean_abs_delta_phi": float(np.mean([abs(r["delta_phi"]) for r in dense])) if dense else 0.0,
        "dense_vs_terminal_ratio": None,
        "steps": rows,
    }
    if abs(summary["terminal_reward"]) > 1e-9:
        summary["dense_vs_terminal_ratio"] = float(
            (summary["sum_delta_phi"] + summary["sum_time_pen"]) / abs(summary["terminal_reward"])
        )
    return summary


def plot_audit(summaries: list[dict], path: Path) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    labels = [s["policy"] for s in summaries]
    # Cumulative reward composition
    ax = axes[0, 0]
    x = np.arange(len(summaries))
    dense = [s["sum_delta_phi"] + s["sum_time_pen"] for s in summaries]
    term = [s["terminal_reward"] for s in summaries]
    ax.bar(x - 0.15, dense, 0.3, label="dense (ΔΦ + time)")
    ax.bar(x + 0.15, term, 0.3, label="terminal")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_ylabel("return components")
    ax.set_title("Dense vs terminal magnitude")
    ax.legend()
    ax.axhline(0, color="k", lw=0.5)

    ax = axes[0, 1]
    width = 0.15
    keys = ["dx", "alt", "vx", "vy", "ang"]
    for i, k in enumerate(keys):
        ax.bar(x + (i - 2) * width, [s["sum_comps"][k] for s in summaries], width, label=k)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_title("Σ potential-term Δ over nonterminal steps")
    ax.legend(fontsize=8)
    ax.axhline(0, color="k", lw=0.5)

    ax = axes[1, 0]
    for s in summaries:
        dense_rows = [r for r in s["steps"] if not r["is_terminal_step"]]
        if not dense_rows:
            continue
        ax.plot(
            [r["t"] for r in dense_rows],
            np.cumsum([r["reward"] for r in dense_rows]),
            label=s["policy"],
            alpha=0.85,
        )
    ax.set_xlabel("gym step")
    ax.set_ylabel("cumulative dense reward")
    ax.set_title("Credit assignment path (pre-terminal)")
    ax.legend(fontsize=8)

    ax = axes[1, 1]
    # Scale comparison: mean |ΔΦ| vs |time| vs |terminal|/T
    means_phi = [s["mean_abs_delta_phi"] for s in summaries]
    means_time = [0.05] * len(summaries)
    term_per_step = [
        abs(s["terminal_reward"]) / max(s["n_gym_steps"], 1) for s in summaries
    ]
    ax.bar(x - 0.2, means_phi, 0.2, label="mean |ΔΦ|")
    ax.bar(x, means_time, 0.2, label="|time pen|")
    ax.bar(x + 0.2, term_per_step, 0.2, label="|terminal|/T")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=15, ha="right")
    ax.set_title("Per-step scale comparison")
    ax.legend(fontsize=8)

    fig.suptitle("ApolloLander reward audit (progress_a scales)")
    fig.tight_layout()
    fig.savefig(path, dpi=140)
    print(f"Wrote {path}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    start = resolve_start("pilot_near")
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=8000,
        start_mode="research",
        start_override=start,
        reward_mode="progress_a",
        headless=True,
    )
    model_path = ROOT / "models" / "ppo_pilot_v2" / "final_model.zip"
    model = PPO.load(str(model_path)) if model_path.exists() else None

    policies = ["noop", "reference_continuous", "reference_multidiscrete"]
    if model is not None:
        policies.append("ppo")

    summaries = []
    try:
        for policy in policies:
            print(f"auditing {policy}...", flush=True)
            summaries.append(run_episode(env, policy, model, seed=50_000))
    finally:
        env.close()

    # Drop per-step arrays from the JSON summary copy (keep full in npz-like json.gz optional)
    slim = []
    for s in summaries:
        sc = {k: v for k, v in s.items() if k != "steps"}
        slim.append(sc)
        print(
            json.dumps(
                {
                    "policy": sc["policy"],
                    "status": sc["status"],
                    "n_gym_steps": sc["n_gym_steps"],
                    "physics_frames": sc["physics_frames"],
                    "sum_reward": sc["sum_reward"],
                    "sum_delta_phi": sc["sum_delta_phi"],
                    "sum_time_pen": sc["sum_time_pen"],
                    "terminal_reward": sc["terminal_reward"],
                    "dense_vs_terminal_ratio": sc["dense_vs_terminal_ratio"],
                    "sum_comps": sc["sum_comps"],
                },
                indent=2,
            ),
            flush=True,
        )

    (OUT / "reward_audit_summary.json").write_text(json.dumps(slim, indent=2))
    # Keep one full expert trajectory for inspection
    full = next(s for s in summaries if s["policy"] == "reference_continuous")
    (OUT / "reward_audit_expert_steps.json").write_text(
        json.dumps(full["steps"][:: max(1, len(full["steps"]) // 200)], indent=2)
    )
    plot_audit(summaries, OUT / "reward_scale_plots.png")

    # SB3 timeout note
    note = {
        "gymnasium": {
            "land_crash": "terminated=True (bootstrap target 0 in SB3)",
            "timeout": "truncated=True (SB3 bootstraps V(s') — timeout is NOT a hard terminal for value)",
        },
        "implication": (
            "Pilot put −100 on truncated timeouts. SB3 still bootstraps the critic on truncated "
            "transitions, so the timeout penalty is a reward spike without zeroing continuation value. "
            "Prefer treating failure timeouts as terminated=True for learning, or use a TimeLimit "
            "wrapper consistently with done flags documented for PPO."
        ),
    }
    (OUT / "sb3_timeout_note.json").write_text(json.dumps(note, indent=2))


if __name__ == "__main__":
    main()
