#!/usr/bin/env python3
"""Offline V5 failure autopsy — NO PPO training.

Compares undiscounted and PPO-discounted (γ=0.99) returns for:
  - early crashes (V5 final / step0 style)
  - post-approach re-ascent timeouts (V5 mid-ckpt + V3-40k)
  - reference landings

Also separates commitment penalty economics from the 11th obs feature
by replaying the same actions under A′ (10-D, no commit) vs V5 reward.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import (  # noqa: E402
    COMMIT_BETA,
    COMMIT_D_APP,
    COMMIT_H_APP,
    COMMIT_R_SOFT,
    COMMIT_V_SOFT,
    ApolloLanderGym,
)
from env.controllers import reference_guidance_action  # noqa: E402

OUT = ROOT / "outputs" / "ppo_pilot_v5_commitment" / "failure_autopsy"
GAMMA = 0.99  # SB3 PPO default used in V5

V5_FINAL = ROOT / "models" / "ppo_pilot_v5_commitment" / "final_model.zip"
V5_STEP0 = ROOT / "models" / "ppo_pilot_v5_commitment" / "step0_random_init.zip"
V5_MID = (
    ROOT
    / "models"
    / "ppo_pilot_v5_commitment"
    / "checkpoints"
    / "ppo_apollo_25000_steps.zip"
)
V3_40K = (
    ROOT
    / "models"
    / "ppo_pilot_v3_contact_Aprime"
    / "checkpoints"
    / "ppo_apollo_40000_steps.zip"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_env(*, commitment: bool, port: int) -> ApolloLanderGym:
    if commitment:
        return ApolloLanderGym(
            action_repeat=4,
            max_physics_frames=2000,
            start_mode="research",
            start_template="sh_contact",
            reward_mode="progress_a_prime_v5",
            potential_scale=10.0,
            time_cost=0.005,
            commitment_shaping=True,
            timeout_as_terminated=True,
            headless=True,
            port=port,
        )
    return ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        commitment_shaping=False,
        timeout_as_terminated=True,
        headless=True,
        port=port,
    )


def discounted_return(rewards: list[float], gamma: float) -> float:
    g = 0.0
    for r in reversed(rewards):
        g = float(r) + gamma * g
    return g


def classify(info: dict, series: list[dict]) -> str:
    if info.get("landed"):
        return "land"
    if info.get("crashed"):
        return "crash"
    if info.get("timeout"):
        min_alt = min(s["alt"] for s in series)
        if min_alt < 20 and series[-1]["alt"] > 50:
            return "timeout_post_approach_reascent"
        return "timeout"
    return "other"


def collect_actions_ppo(model_path: Path, seed: int, *, commitment: bool, port: int) -> dict:
    model = PPO.load(str(model_path))
    env = make_env(commitment=commitment, port=port)
    try:
        obs, info = env.reset(seed=seed)
        actions = []
        series = []
        while True:
            a, _ = model.predict(obs, deterministic=True)
            a = np.asarray(a, dtype=np.int64)
            actions.append(a.copy())
            obs, _, term, trunc, info = env.step(a)
            raw = info["raw"]
            series.append(
                {
                    "alt": float(raw["altitude"]),
                    "vy": float(raw["vy"]),
                    "rot": float(raw["rotation"]),
                    "dx": float(raw["dx"]),
                }
            )
            if term or trunc:
                break
        return {
            "seed": seed,
            "actions": actions,
            "outcome": classify(info, series),
            "landed": bool(info["landed"]),
            "crashed": bool(info["crashed"]),
            "timeout": bool(info["timeout"]),
            "frames": int(info["physics_frames"]),
            "min_alt": float(min(s["alt"] for s in series)),
            "max_alt": float(max(s["alt"] for s in series)),
            "model": str(model_path),
            "model_sha256": sha256(model_path),
        }
    finally:
        env.close()


def collect_actions_reference(seed: int, port: int) -> dict:
    env = make_env(commitment=False, port=port)
    try:
        obs, info = env.reset(seed=seed)
        actions = []
        series = []
        while True:
            a = reference_guidance_action(info["raw"], env.cmd_angle)
            actions.append(np.asarray(a, dtype=np.int64).copy())
            obs, _, term, trunc, info = env.step(a)
            raw = info["raw"]
            series.append(
                {
                    "alt": float(raw["altitude"]),
                    "vy": float(raw["vy"]),
                    "rot": float(raw["rotation"]),
                    "dx": float(raw["dx"]),
                }
            )
            if term or trunc:
                break
        return {
            "seed": seed,
            "actions": actions,
            "outcome": classify(info, series),
            "landed": bool(info["landed"]),
            "crashed": bool(info["crashed"]),
            "timeout": bool(info["timeout"]),
            "frames": int(info["physics_frames"]),
            "min_alt": float(min(s["alt"] for s in series)),
            "max_alt": float(max(s["alt"] for s in series)),
            "model": "reference",
            "model_sha256": None,
        }
    finally:
        env.close()


def replay_rewards(actions: list[np.ndarray], seed: int, *, commitment: bool, port: int) -> dict:
    env = make_env(commitment=commitment, port=port)
    try:
        obs, info = env.reset(seed=seed)
        rewards = []
        commits = []
        approached = bool(info.get("approached"))
        for a in actions:
            obs, r, term, trunc, info = env.step(a)
            raw = info["raw"]
            approached = bool(info.get("approached"))
            # Reconstruct commit (0 if commitment off)
            commit = 0.0
            if commitment and approached:
                vy = float(raw["vy"])
                rot = float(raw["rotation"])
                if vy < COMMIT_V_SOFT and abs(rot) < COMMIT_R_SOFT:
                    ascent = max(0.0, -vy)
                    if ascent > 0:
                        commit = -COMMIT_BETA * ascent
            rewards.append(float(r))
            commits.append(commit)
            if term or trunc:
                break
        return {
            "n_steps": len(rewards),
            "undiscounted_return": float(sum(rewards)),
            "discounted_return_gamma_0_99": discounted_return(rewards, GAMMA),
            "sum_commit": float(sum(commits)),
            "n_commit_penalty_steps": int(sum(1 for c in commits if c < 0)),
            "terminal_reward": rewards[-1] if rewards else None,
            "mean_step_reward_excl_terminal": float(np.mean(rewards[:-1]))
            if len(rewards) > 1
            else None,
            "landed": bool(info.get("landed")),
            "crashed": bool(info.get("crashed")),
            "timeout": bool(info.get("timeout")),
            "status": info.get("status"),
            "approached_final": approached,
        }
    finally:
        env.close()


def summarize_group(rows: list[dict], key: str) -> dict:
    vals = [r[key] for r in rows if r.get(key) is not None]
    if not vals:
        return {"n": 0}
    return {
        "n": len(vals),
        "mean": float(np.mean(vals)),
        "median": float(np.median(vals)),
        "min": float(np.min(vals)),
        "max": float(np.max(vals)),
        "std": float(np.std(vals)),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Seeds: crashes from V5 held-out; reascent from DEV mid-train known modes; lands from ref/V3
    crash_seeds = [500000, 500001, 500002, 500003]
    reascent_seeds = [200000, 200002, 200004, 200006]  # V3 autopsy timeouts; also mid-V5
    land_seeds = [200001, 200003, 200005, 500006]  # mix; ref may land

    port = 19300
    episodes = []

    # 1) V5 final crashes (trained, late collapse)
    for seed in crash_seeds:
        print(f"V5 final crash seed={seed}", flush=True)
        traj = collect_actions_ppo(V5_FINAL, seed, commitment=True, port=port)
        port += 1
        v5 = replay_rewards(traj["actions"], seed, commitment=True, port=port)
        port += 1
        a_prime = replay_rewards(traj["actions"], seed, commitment=False, port=port)
        port += 1
        episodes.append(
            {
                "group": "v5_final_crash",
                "seed": seed,
                "behavior": {k: v for k, v in traj.items() if k != "actions"},
                "n_actions": len(traj["actions"]),
                "reward_v5": v5,
                "reward_a_prime_same_actions": a_prime,
                "commit_delta_undiscounted": v5["undiscounted_return"]
                - a_prime["undiscounted_return"],
                "commit_delta_discounted": v5["discounted_return_gamma_0_99"]
                - a_prime["discounted_return_gamma_0_99"],
            }
        )

    # 2) V5 mid reascent timeouts
    for seed in reascent_seeds:
        print(f"V5 mid reascent seed={seed}", flush=True)
        traj = collect_actions_ppo(V5_MID, seed, commitment=True, port=port)
        port += 1
        v5 = replay_rewards(traj["actions"], seed, commitment=True, port=port)
        port += 1
        a_prime = replay_rewards(traj["actions"], seed, commitment=False, port=port)
        port += 1
        episodes.append(
            {
                "group": "v5_mid_reascent",
                "seed": seed,
                "behavior": {
                    k: v for k, v in traj.items() if k != "actions"
                },
                "n_actions": len(traj["actions"]),
                "reward_v5": v5,
                "reward_a_prime_same_actions": a_prime,
                "commit_delta_undiscounted": v5["undiscounted_return"]
                - a_prime["undiscounted_return"],
                "commit_delta_discounted": v5["discounted_return_gamma_0_99"]
                - a_prime["discounted_return_gamma_0_99"],
            }
        )
        # keep actions only in heavy dump file
        episodes[-1]["_actions_len"] = len(traj["actions"])

    # 3) V3-40k reascent (10-D policy) — replay under both rewards
    for seed in reascent_seeds:
        print(f"V3-40k reascent seed={seed}", flush=True)
        traj = collect_actions_ppo(V3_40K, seed, commitment=False, port=port)
        port += 1
        # Pad action replay into V5 env: V3 actions are valid MultiDiscrete; obs unused for replay
        v5 = replay_rewards(traj["actions"], seed, commitment=True, port=port)
        port += 1
        a_prime = replay_rewards(traj["actions"], seed, commitment=False, port=port)
        port += 1
        episodes.append(
            {
                "group": "v3_40k_reascent_actions",
                "seed": seed,
                "behavior": {k: v for k, v in traj.items() if k != "actions"},
                "n_actions": len(traj["actions"]),
                "reward_v5": v5,
                "reward_a_prime_same_actions": a_prime,
                "commit_delta_undiscounted": v5["undiscounted_return"]
                - a_prime["undiscounted_return"],
                "commit_delta_discounted": v5["discounted_return_gamma_0_99"]
                - a_prime["discounted_return_gamma_0_99"],
            }
        )

    # 4) Reference landings
    for seed in land_seeds:
        print(f"reference seed={seed}", flush=True)
        traj = collect_actions_reference(seed, port=port)
        port += 1
        if not traj["landed"]:
            episodes.append(
                {
                    "group": "reference_nonland",
                    "seed": seed,
                    "behavior": {k: v for k, v in traj.items() if k != "actions"},
                    "skipped_reward": True,
                }
            )
            continue
        v5 = replay_rewards(traj["actions"], seed, commitment=True, port=port)
        port += 1
        a_prime = replay_rewards(traj["actions"], seed, commitment=False, port=port)
        port += 1
        episodes.append(
            {
                "group": "reference_land",
                "seed": seed,
                "behavior": {k: v for k, v in traj.items() if k != "actions"},
                "n_actions": len(traj["actions"]),
                "reward_v5": v5,
                "reward_a_prime_same_actions": a_prime,
                "commit_delta_undiscounted": v5["undiscounted_return"]
                - a_prime["undiscounted_return"],
                "commit_delta_discounted": v5["discounted_return_gamma_0_99"]
                - a_prime["discounted_return_gamma_0_99"],
            }
        )

    # 5) Obs-feature isolation note: V5 policies require 11-D; cannot load into 10-D.
    # Compare step0 vs final under V5 env only (same reward+obs), and A′ return on
    # identical action traces (reward-only ablation above).
    obs_note = {
        "v5_obs_dim": 11,
        "v3_obs_dim": 10,
        "cannot_load_v5_policy_in_10d": True,
        "cannot_load_v3_policy_in_11d": True,
        "ablation_method": (
            "Same action traces replayed under commitment ON vs OFF isolates the "
            "reward penalty from the 11th observation (actions were generated under "
            "their native obs; reward comparison is action-conditional)."
        ),
        "v5_final_sha256": sha256(V5_FINAL),
        "v5_step0_sha256": sha256(V5_STEP0),
        "v5_mid_25k_sha256": sha256(V5_MID),
        "v3_40k_sha256": sha256(V3_40K),
        "selected_equals_step0": sha256(V5_STEP0)
        == sha256(
            ROOT
            / "models"
            / "ppo_pilot_v5_commitment"
            / "selected"
            / "selected_model.zip"
        ),
    }

    def group_rows(name: str) -> list[dict]:
        return [e for e in episodes if e.get("group") == name and "reward_v5" in e]

    economics = {}
    for name in (
        "v5_final_crash",
        "v5_mid_reascent",
        "v3_40k_reascent_actions",
        "reference_land",
    ):
        rows = group_rows(name)
        economics[name] = {
            "undiscounted_v5": summarize_group(
                [r["reward_v5"] for r in rows], "undiscounted_return"
            ),
            "discounted_v5": summarize_group(
                [r["reward_v5"] for r in rows], "discounted_return_gamma_0_99"
            ),
            "undiscounted_a_prime": summarize_group(
                [r["reward_a_prime_same_actions"] for r in rows], "undiscounted_return"
            ),
            "discounted_a_prime": summarize_group(
                [r["reward_a_prime_same_actions"] for r in rows],
                "discounted_return_gamma_0_99",
            ),
            "sum_commit": summarize_group([r["reward_v5"] for r in rows], "sum_commit"),
            "commit_delta_undiscounted": summarize_group(rows, "commit_delta_undiscounted"),
            "commit_delta_discounted": summarize_group(rows, "commit_delta_discounted"),
            "n_episodes": len(rows),
            "outcomes": [r["behavior"]["outcome"] for r in rows],
        }

    # Key scientific question: does -261 commit make crash better than timeout under V5?
    crash_u = economics["v5_final_crash"]["undiscounted_v5"].get("mean")
    reasc_u = economics["v5_mid_reascent"]["undiscounted_v5"].get("mean")
    reasc_v3_u = economics["v3_40k_reascent_actions"]["undiscounted_v5"].get("mean")
    land_u = economics["reference_land"]["undiscounted_v5"].get("mean")
    crash_d = economics["v5_final_crash"]["discounted_v5"].get("mean")
    reasc_d = economics["v5_mid_reascent"]["discounted_v5"].get("mean")
    land_d = economics["reference_land"]["discounted_v5"].get("mean")

    preference = {
        "question": "Does accumulating ~-261 commitment make early crash preferable to reascent timeout?",
        "mean_undiscounted_v5_crash": crash_u,
        "mean_undiscounted_v5_mid_reascent": reasc_u,
        "mean_undiscounted_v5_on_v3_reascent_actions": reasc_v3_u,
        "mean_undiscounted_v5_reference_land": land_u,
        "crash_beats_mid_reascent_undiscounted": (
            crash_u is not None and reasc_u is not None and crash_u > reasc_u
        ),
        "crash_beats_v3_reascent_actions_undiscounted": (
            crash_u is not None and reasc_v3_u is not None and crash_u > reasc_v3_u
        ),
        "land_beats_crash_undiscounted": (
            land_u is not None and crash_u is not None and land_u > crash_u
        ),
        "mean_discounted_v5_crash": crash_d,
        "mean_discounted_v5_mid_reascent": reasc_d,
        "mean_discounted_v5_reference_land": land_d,
        "crash_beats_mid_reascent_discounted": (
            crash_d is not None and reasc_d is not None and crash_d > reasc_d
        ),
        "interpretation": None,
    }
    if preference["crash_beats_mid_reascent_undiscounted"] and preference[
        "crash_beats_v3_reascent_actions_undiscounted"
    ]:
        if preference["crash_beats_mid_reascent_discounted"]:
            preference["interpretation"] = (
                "YES (undiscounted and discounted) — early crash returns exceed reascent "
                "timeouts under V5. Commitment on long ascents can make crashing "
                "economically preferable to lingering; land still dominates crash."
            )
        else:
            preference["interpretation"] = (
                "MIXED — UNDISCOUNTED V5 returns: early crash ≫ reascent timeout "
                "(commitment ≈ −261 on V3-style ascents makes long aborts very costly). "
                "PPO-DISCOUNTED (γ=0.99): distant timeout/commit is diluted, so mid-reascent "
                "discounted return can EXCEED crash. Late crash collapse is therefore not "
                "fully explained by γ-return preferring crash; the 11-D obs change and "
                "optimization dynamics remain confounded with the penalty. Land still best."
            )
    elif preference["crash_beats_mid_reascent_undiscounted"]:
        preference["interpretation"] = (
            "PARTIAL — crash beats V5-mid reascent undiscounted; check V3 action replays."
        )
    else:
        preference["interpretation"] = (
            "NO clear crash>reascent preference under sampled trajectories; "
            "failure may be exploration/representation rather than pure return ordering."
        )

    # Slim episodes for JSON (drop huge action lists already stripped)
    slim = []
    for e in episodes:
        slim.append({k: v for k, v in e.items() if not k.startswith("_")})

    report = {
        "gamma": GAMMA,
        "commitment_constants": {
            "H_app": COMMIT_H_APP,
            "D_app": COMMIT_D_APP,
            "V_soft": COMMIT_V_SOFT,
            "R_soft": COMMIT_R_SOFT,
            "beta": COMMIT_BETA,
        },
        "obs_feature_vs_reward": obs_note,
        "economics_by_group": economics,
        "crash_vs_reascent_preference": preference,
        "episodes": slim,
        "no_training": True,
    }
    (OUT / "failure_autopsy.json").write_text(json.dumps(report, indent=2))

    md = [
        "# V5 failure autopsy (offline; no training)",
        "",
        f"**γ (PPO)** = {GAMMA}",
        "",
        "## Crash vs reascent return preference",
        "",
        preference["interpretation"] or "",
        "",
        f"| Group | n | Mean undiscounted V5 | Mean discounted V5 | Mean Σ commit |",
        f"|-------|--:|---------------------:|-------------------:|--------------:|",
    ]
    for name, label in [
        ("v5_final_crash", "V5 final crashes"),
        ("v5_mid_reascent", "V5 mid reascent"),
        ("v3_40k_reascent_actions", "V3-40k reascent acts @ V5 R"),
        ("reference_land", "Reference lands"),
    ]:
        e = economics[name]
        md.append(
            f"| {label} | {e['n_episodes']} | "
            f"{e['undiscounted_v5'].get('mean', float('nan')):.1f} | "
            f"{e['discounted_v5'].get('mean', float('nan')):.1f} | "
            f"{e['sum_commit'].get('mean', float('nan')):.1f} |"
        )
    md += [
        "",
        "## Reward vs 11th observation",
        "",
        obs_note["ablation_method"],
        "",
        "- V5 policies are 11-D and cannot be evaluated in a 10-D env.",
        "- V3-40k is 10-D and cannot be loaded into 11-D.",
        "- Action-conditional replay under commit ON/OFF isolates the **penalty**.",
        f"- Selected model SHA equals step0: **{obs_note['selected_equals_step0']}**",
        "",
        f"Full JSON: `{OUT / 'failure_autopsy.json'}`",
        "",
    ]
    (OUT / "FAILURE_AUTOPSY.md").write_text("\n".join(md))
    print(json.dumps(preference, indent=2))
    print("Wrote", OUT / "FAILURE_AUTOPSY.md")


if __name__ == "__main__":
    main()
