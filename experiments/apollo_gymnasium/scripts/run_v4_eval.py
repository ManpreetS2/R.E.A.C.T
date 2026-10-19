#!/usr/bin/env python3
"""V4 post-train: DEV checkpoint selection + one-shot held-out comparison + failure analysis."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import THRUST_LEVELS, ApolloLanderGym  # noqa: E402
from env.controllers import noop_action, random_action, reference_guidance_action  # noqa: E402
from env.seeds import DEV_EVAL_SEEDS, V4_HELD_OUT_SEEDS  # noqa: E402

RUN = "ppo_pilot_v4_timecost"
OUT = ROOT / "outputs" / RUN
MODELS = ROOT / "models" / RUN
V3_40K = (
    ROOT
    / "models"
    / "ppo_pilot_v3_contact_Aprime"
    / "checkpoints"
    / "ppo_apollo_40000_steps.zip"
)
EVIDENCE = OUT / "evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def make_env() -> ApolloLanderGym:
    return ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.02,
        timeout_as_terminated=True,
        headless=True,
        render_mode=None,
    )


def run_policy_episode(env, policy: str, model, seed: int, *, deterministic: bool, rng) -> dict:
    obs, info = env.reset(seed=seed)
    start = dict(info["start"])
    series = []
    while True:
        if policy == "noop":
            a = noop_action(obs)
        elif policy == "random":
            a = random_action(rng)
        elif policy == "reference":
            a = reference_guidance_action(info["raw"], env.cmd_angle)
        elif policy == "ppo":
            a, _ = model.predict(obs, deterministic=deterministic)
        else:
            raise ValueError(policy)
        obs, _, term, trunc, info = env.step(a)
        raw = info["raw"]
        series.append(
            {
                "t": info["physics_frames"],
                "alt": float(raw["altitude"]),
                "vy": float(raw["vy"]),
                "vx": float(raw["vx"]),
                "rot": float(raw["rotation"]),
                "dx": float(raw["dx"]),
                "thrust": float(raw.get("thrust", 0)),
            }
        )
        if term or trunc:
            break
    failure_mode = classify_failure(info, series)
    return {
        "seed": seed,
        "policy": policy,
        "deterministic": deterministic if policy == "ppo" else None,
        "status": info["status"],
        "landed": bool(info["landed"]),
        "perfect": bool(info["perfect"]),
        "hard_landing": bool(info["hard_landing"]),
        "crashed": bool(info["crashed"]),
        "timeout": bool(info["timeout"]),
        "physics_frames": info["physics_frames"],
        "fuel_remaining": info.get("fuel_remaining"),
        "native_score": info.get("native_score"),
        "start": start,
        "final_raw": {
            k: float(info["raw"][k])
            for k in ("altitude", "vx", "vy", "rotation", "dx", "thrust")
        },
        "min_alt": float(min(s["alt"] for s in series)),
        "max_alt": float(max(s["alt"] for s in series)),
        "failure_mode": failure_mode,
        "series_downsampled": series[:: max(1, len(series) // 40)],
    }


def classify_failure(info: dict, series: list[dict]) -> str | None:
    if info.get("landed"):
        return None
    if info.get("crashed"):
        # Distinguish attitude / velocity / drift if possible from final raw
        raw = info["raw"]
        if abs(float(raw.get("rotation", 0))) > 15:
            return "crash_attitude"
        if abs(float(raw.get("vy", 0))) > 0.2 or abs(float(raw.get("vx", 0))) > 0.2:
            return "crash_velocity"
        if abs(float(raw.get("dx", 0))) > 40:
            return "crash_offpad_drift"
        return "crash"
    if info.get("timeout"):
        min_alt = min(s["alt"] for s in series)
        alt_last = series[-1]["alt"]
        if min_alt < 20 and alt_last > 50:
            return "timeout_post_approach_reascent"
        if alt_last > 100 and abs(series[-1]["vy"]) < 0.2:
            return "timeout_hover"
        if alt_last > 100:
            return "timeout_high_altitude"
        return "timeout"
    return "unknown"


def summarize(rows: list[dict]) -> dict:
    n = len(rows)
    land = sum(r["landed"] for r in rows)
    perfect = sum(r["perfect"] for r in rows)
    hard = sum(r["hard_landing"] for r in rows)
    crash = sum(r["crashed"] for r in rows)
    timeout = sum(r["timeout"] for r in rows)
    lo, hi = wilson_ci(land, n)
    modes: dict[str, int] = {}
    for r in rows:
        m = r.get("failure_mode")
        if m:
            modes[m] = modes.get(m, 0) + 1
    return {
        "n": n,
        "land_count": land,
        "perfect_count": perfect,
        "hard_landing_count": hard,
        "crash_count": crash,
        "timeout_count": timeout,
        "land_rate": land / n,
        "perfect_rate": perfect / n,
        "hard_landing_rate": hard / n,
        "crash_rate": crash / n,
        "timeout_rate": timeout / n,
        "land_rate_wilson95": [lo, hi],
        "mean_physics_frames": float(np.mean([r["physics_frames"] for r in rows])),
        "mean_fuel_remaining": float(
            np.mean([float(r["fuel_remaining"] or 0) for r in rows])
        ),
        "mean_native_score": float(
            np.mean([float(r["native_score"] or 0) for r in rows])
        ),
        "failure_modes": modes,
    }


def eval_model(path: Path, seeds: list[int], label: str, *, deterministic: bool = True) -> dict:
    model = PPO.load(str(path)) if path else None
    env = make_env()
    rng = np.random.default_rng(0)
    rows = []
    try:
        for seed in seeds:
            for attempt in range(3):
                try:
                    if attempt:
                        env.close()
                        env = make_env()
                    rows.append(
                        run_policy_episode(
                            env,
                            "ppo",
                            model,
                            seed,
                            deterministic=deterministic,
                            rng=rng,
                        )
                    )
                    break
                except Exception as exc:  # noqa: BLE001
                    if attempt == 2:
                        raise
                    print(f"retry {label} seed={seed}: {exc}", flush=True)
    finally:
        env.close()
    summary = summarize(rows)
    summary["label"] = label
    summary["model"] = str(path)
    summary["deterministic"] = deterministic
    summary["episodes"] = rows
    return summary


def eval_baseline(policy: str, seeds: list[int]) -> dict:
    env = make_env()
    rng = np.random.default_rng(123)
    rows = []
    try:
        for seed in seeds:
            rows.append(
                run_policy_episode(env, policy, None, seed, deterministic=True, rng=rng)
            )
    finally:
        env.close()
    summary = summarize(rows)
    summary["label"] = policy
    summary["episodes"] = rows
    return summary


def _ckpt_step(path: Path) -> int:
    for p in path.stem.split("_"):
        if p.isdigit():
            return int(p)
    return 10**9


def select_best_dev() -> dict:
    seeds = list(DEV_EVAL_SEEDS)
    paths = [MODELS / "step0_random_init.zip"]
    paths += sorted((MODELS / "checkpoints").glob("ppo_apollo_*_steps.zip"), key=_ckpt_step)
    paths.append(MODELS / "final_model.zip")
    results = []
    for p in paths:
        if not p.exists():
            continue
        label = p.stem
        print(f"DEV eval {label}...", flush=True)
        summary = eval_model(p, seeds, label, deterministic=True)
        slim = {k: v for k, v in summary.items() if k != "episodes"}
        results.append(slim)
        (OUT / f"dev_{label}.json").write_text(json.dumps(summary, indent=2))

    def key(r):
        return (r["land_rate"], -r["timeout_rate"], -r["mean_physics_frames"])

    best = max(results, key=key)
    # Resolve path
    if best["label"] == "step0_random_init":
        best_path = MODELS / "step0_random_init.zip"
    elif best["label"] == "final_model":
        best_path = MODELS / "final_model.zip"
    else:
        best_path = MODELS / "checkpoints" / f"{best['label']}.zip"
    sel = {
        "selection_rule": "max land_rate, then min timeout_rate, then min mean_physics_frames",
        "seed_pool": "DEV_EVAL_SEEDS",
        "checkpoints": results,
        "selected": best,
        "selected_path": str(best_path),
        "selected_sha256": sha256(best_path),
        "incumbent_v3_40k_dev_land_rate": 0.60,
        "beats_v3_40k_on_dev": best["land_rate"] > 0.60,
    }
    # Freeze selected copy
    freeze_dir = MODELS / "selected"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    dest = freeze_dir / "selected_model.zip"
    shutil.copy2(best_path, dest)
    (freeze_dir / "selection.json").write_text(json.dumps(sel, indent=2))
    (OUT / "dev_selection.json").write_text(json.dumps(sel, indent=2))
    return sel, best_path


def heldout_comparison(v4_path: Path) -> dict:
    seeds = list(V4_HELD_OUT_SEEDS)
    print("=== one-shot V4 held-out comparison ===", flush=True)
    results = {}
    for name, path, det in [
        ("v4_selected_det", v4_path, True),
        ("v4_selected_stoch", v4_path, False),
        ("v3_40k_det", V3_40K, True),
        ("v4_step0_det", MODELS / "step0_random_init.zip", True),
    ]:
        print(f"  eval {name}...", flush=True)
        s = eval_model(path, seeds, name, deterministic=det)
        (OUT / f"heldout_{name}.json").write_text(json.dumps(s, indent=2))
        results[name] = {k: v for k, v in s.items() if k != "episodes"}

    for name in ("noop", "random", "reference"):
        print(f"  baseline {name}...", flush=True)
        s = eval_baseline(name, seeds)
        (OUT / f"heldout_{name}.json").write_text(json.dumps(s, indent=2))
        results[name] = {k: v for k, v in s.items() if k != "episodes"}

    v4 = results["v4_selected_det"]
    v3 = results["v3_40k_det"]
    comparison = {
        "seed_pool": "V4_HELD_OUT_SEEDS",
        "seeds": seeds,
        "by_policy": results,
        "v4_vs_v3_40k": {
            "v4_land_rate": v4["land_rate"],
            "v3_land_rate": v3["land_rate"],
            "v4_land_wilson95": v4["land_rate_wilson95"],
            "v3_land_wilson95": v3["land_rate_wilson95"],
            "delta_land_rate": v4["land_rate"] - v3["land_rate"],
            "v4_improved": v4["land_rate"] > v3["land_rate"],
            "v4_timeout_rate": v4["timeout_rate"],
            "v3_timeout_rate": v3["timeout_rate"],
        },
        "warning": "ONE-SHOT held-out. Not used for selection or retraining.",
    }
    (OUT / "heldout_comparison.json").write_text(json.dumps(comparison, indent=2))
    return comparison


def record_video(model_path: Path, seed: int, tag: str) -> Path:
    import base64

    import imageio_ffmpeg

    out = EVIDENCE / tag
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    model = PPO.load(str(model_path))
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.02,
        timeout_as_terminated=True,
        headless=True,
        render_mode="rgb_array",
    )
    meta = {}
    try:
        obs, info = env.reset(seed=seed)
        idx = 0
        while True:
            png_b64 = env._page.evaluate("() => window.ApolloOriginal.snapshotPNG()")
            raw = base64.b64decode(png_b64.split(",", 1)[1])
            (frames / f"frame_{idx:05d}.png").write_bytes(raw)
            idx += 1
            a, _ = model.predict(obs, deterministic=True)
            obs, _, term, trunc, info = env.step(a)
            if term or trunc:
                break
        for _ in range(45):
            png_b64 = env._page.evaluate("() => window.ApolloOriginal.snapshotPNG()")
            raw = base64.b64decode(png_b64.split(",", 1)[1])
            (frames / f"frame_{idx:05d}.png").write_bytes(raw)
            idx += 1
        meta = {
            "seed": seed,
            "status": info["status"],
            "landed": bool(info["landed"]),
            "perfect": bool(info["perfect"]),
            "physics_frames": info["physics_frames"],
            "native_score": info.get("native_score"),
            "model_sha256": sha256(model_path),
        }
    finally:
        env.close()
    mp4 = out / "native.mp4"
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run(
        [
            ff,
            "-y",
            "-framerate",
            "30",
            "-i",
            str(frames / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(mp4),
        ],
        check=True,
        capture_output=True,
    )
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return mp4


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    train = json.loads((OUT / "train_summary.json").read_text())
    assert train["actual_physics_frames"] <= 200_000, train["actual_physics_frames"]

    sel, best_path = select_best_dev()
    comparison = heldout_comparison(best_path)

    # Videos: one success + one failure from held-out V4 det if available
    held = json.loads((OUT / "heldout_v4_selected_det.json").read_text())
    success = next((e for e in held["episodes"] if e["landed"]), None)
    failure = next((e for e in held["episodes"] if not e["landed"]), None)
    videos = {}
    if success:
        print(f"Recording success seed={success['seed']}...", flush=True)
        videos["success"] = str(record_video(best_path, success["seed"], f"success_{success['seed']}"))
    if failure:
        print(f"Recording failure seed={failure['seed']}...", flush=True)
        videos["failure"] = str(record_video(best_path, failure["seed"], f"failure_{failure['seed']}"))

    report = {
        "run": RUN,
        "train_summary": train,
        "dev_selection": {k: v for k, v in sel.items() if k != "checkpoints"}
        | {"n_checkpoints": len(sel["checkpoints"]), "selected": sel["selected"]},
        "heldout_comparison": comparison,
        "videos": videos,
        "improved_over_v3_40k_heldout": comparison["v4_vs_v3_40k"]["v4_improved"],
        "improved_over_v3_40k_dev": sel["beats_v3_40k_on_dev"],
    }
    (OUT / "V4_RESULTS.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
