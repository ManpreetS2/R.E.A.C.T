#!/usr/bin/env python3
"""V3 preserve/audit: freeze hashes, verify landing replay, checkpoint DEV sweep, timeout autopsy.

Does NOT train. Does NOT touch held-out for checkpoint selection (only post-hoc step-0).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import THRUST_LEVELS, STEER_DELTAS, ApolloLanderGym  # noqa: E402
from env.controllers import noop_action  # noqa: E402
from env.seeds import DEV_EVAL_SEEDS, HELD_OUT_SEEDS  # noqa: E402

OUT = ROOT / "outputs" / "ppo_pilot_v3_contact_Aprime" / "v4_audit"
MODELS = ROOT / "models" / "ppo_pilot_v3_contact_Aprime"
EVIDENCE = ROOT / "outputs" / "ppo_pilot_v3_contact_Aprime" / "landing_evidence"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze_manifest() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    files = {
        "final_model": MODELS / "final_model.zip",
        "step0": MODELS / "step0_random_init.zip",
        "train_summary": ROOT / "outputs/ppo_pilot_v3_contact_Aprime/train_summary.json",
        "run_config": ROOT / "outputs/ppo_pilot_v3_contact_Aprime/run_config.json",
        "eval_heldout": ROOT / "outputs/ppo_pilot_v3_contact_Aprime/eval_heldout_final.json",
        "eval_dev_final": ROOT / "outputs/ppo_pilot_v3_contact_Aprime/eval_dev_final.json",
        "landing_meta": EVIDENCE / "landing_meta.json",
        "v3_results": ROOT / "outputs/ppo_pilot_v3_contact_Aprime/V3_RESULTS.md",
    }
    manifest = {"artifacts": {}, "checkpoints": {}}
    for name, path in files.items():
        if path.exists():
            manifest["artifacts"][name] = {
                "path": str(path.relative_to(ROOT.parent.parent) if False else path),
                "sha256": sha256(path),
                "bytes": path.stat().st_size,
            }
    ckpt_dir = MODELS / "checkpoints"
    for z in sorted(ckpt_dir.glob("*.zip")):
        manifest["checkpoints"][z.name] = {"sha256": sha256(z), "bytes": z.stat().st_size}
    (OUT / "v3_freeze_manifest.json").write_text(json.dumps(manifest, indent=2))
    return manifest


def verify_landing_replay() -> dict:
    meta = json.loads((EVIDENCE / "landing_meta.json").read_text())
    actions = meta["actions"]
    seed = int(meta["seed"])
    start = meta["start"]

    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        timeout_as_terminated=True,
        headless=True,
    )
    try:
        obs, info = env.reset(seed=seed)
        # Confirm start matches frozen meta
        start_match = all(
            abs(float(info["start"][k]) - float(start[k])) < 1e-6
            for k in ("x", "y", "vx", "vy", "rotation", "fuel", "scale")
        )
        traj = []
        for a in actions:
            obs, r, term, trunc, info = env.step(np.array(a, dtype=np.int64))
            traj.append(
                {
                    "action": a,
                    "thrust": float(THRUST_LEVELS[int(a[0])]),
                    "steer": float(STEER_DELTAS[int(a[1])]),
                    "raw": {
                        k: float(info["raw"][k])
                        for k in ("x", "y", "vx", "vy", "rotation", "altitude", "fuel")
                    },
                    "status": info["status"],
                    "physics_frames": info["physics_frames"],
                }
            )
            if term or trunc:
                break
        result = {
            "start_match": start_match,
            "status": info["status"],
            "landed": bool(info["landed"]),
            "perfect": bool(info["perfect"]),
            "native_score": info.get("native_score"),
            "physics_frames": info["physics_frames"],
            "expected_status": meta["status"],
            "expected_perfect": meta["perfect"],
            "expected_frames": meta["physics_frames"],
            "replay_matches_meta": (
                bool(info["landed"])
                and bool(info["perfect"]) == bool(meta["perfect"])
                and info["status"] == meta["status"]
            ),
            "n_actions_applied": len(traj),
            "final_raw": traj[-1]["raw"] if traj else None,
        }
        # No-op on same start must fail
        obs, info = env.reset(seed=seed)
        while True:
            obs, _, term, trunc, info = env.step(noop_action())
            if term or trunc:
                break
        result["noop_on_same_start"] = {
            "landed": bool(info["landed"]),
            "status": info["status"],
        }
        result["passed"] = bool(
            result["start_match"]
            and result["replay_matches_meta"]
            and not result["noop_on_same_start"]["landed"]
        )
        (OUT / "landing_replay_verification.json").write_text(json.dumps(result, indent=2))
        (OUT / "landing_replay_trace.json").write_text(json.dumps(traj, indent=2))
    finally:
        env.close()
    return result


def ensure_mp4() -> dict:
    mp4 = EVIDENCE / "landing_native.mp4"
    frames = EVIDENCE / "frames"
    info = {"mp4_exists": mp4.exists(), "path": str(mp4)}
    if mp4.exists():
        info["sha256"] = sha256(mp4)
        info["bytes"] = mp4.stat().st_size
        # Copy to audit folder for accessibility
        dest = OUT / "landing_native_accessible.mp4"
        shutil.copy2(mp4, dest)
        info["audit_copy"] = str(dest)
        return info
    if frames.exists() and any(frames.glob("*.png")):
        import imageio_ffmpeg

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
        info["regenerated"] = True
        info["mp4_exists"] = True
        info["sha256"] = sha256(mp4)
        shutil.copy2(mp4, OUT / "landing_native_accessible.mp4")
    return info


def eval_model(model_path: Path, seeds: list[int], label: str) -> dict:
    model = PPO.load(str(model_path))
    rows = []
    # Fresh env per model — shared Playwright page can corrupt after long sweeps.
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        timeout_as_terminated=True,
        headless=True,
    )
    try:
        for seed in seeds:
            for attempt in range(3):
                try:
                    if attempt > 0:
                        env.close()
                        env = ApolloLanderGym(
                            action_repeat=4,
                            max_physics_frames=2000,
                            start_mode="research",
                            start_template="sh_contact",
                            reward_mode="progress_a_prime",
                            timeout_as_terminated=True,
                            headless=True,
                        )
                    obs, info = env.reset(seed=seed)
                    start = dict(info["start"])
                    while True:
                        a, _ = model.predict(obs, deterministic=True)
                        obs, _, term, trunc, info = env.step(a)
                        if term or trunc:
                            rows.append(
                                {
                                    "seed": seed,
                                    "start": start,
                                    "status": info["status"],
                                    "landed": bool(info["landed"]),
                                    "perfect": bool(info["perfect"]),
                                    "hard_landing": bool(info["hard_landing"]),
                                    "crashed": bool(info["crashed"]),
                                    "timeout": bool(info["timeout"]),
                                    "physics_frames": info["physics_frames"],
                                    "fuel_remaining": info.get("fuel_remaining"),
                                    "native_score": info.get("native_score"),
                                    "final_raw": {
                                        k: float(info["raw"][k])
                                        for k in (
                                            "altitude",
                                            "vx",
                                            "vy",
                                            "rotation",
                                            "dx",
                                            "thrust",
                                        )
                                    },
                                }
                            )
                            break
                    break
                except Exception as exc:  # noqa: BLE001 — Playwright thruster-sound flake
                    if attempt == 2:
                        raise
                    print(f"  retry seed={seed} after {type(exc).__name__}: {exc}", flush=True)
    finally:
        env.close()
    n = len(rows)
    summary = {
        "label": label,
        "model": str(model_path),
        "n": n,
        "land_rate": sum(r["landed"] for r in rows) / n,
        "perfect_rate": sum(r["perfect"] for r in rows) / n,
        "hard_landing_rate": sum(r["hard_landing"] for r in rows) / n,
        "crash_rate": sum(r["crashed"] for r in rows) / n,
        "timeout_rate": sum(r["timeout"] for r in rows) / n,
        "mean_physics_frames": float(np.mean([r["physics_frames"] for r in rows])),
        "episodes": rows,
    }
    return summary


def _ckpt_step(path: Path) -> int:
    # ppo_apollo_40000_steps.zip → 40000; others → large sentinel for ordering
    stem = path.stem
    parts = stem.split("_")
    for p in parts:
        if p.isdigit():
            return int(p)
    return 10**9


def checkpoint_dev_sweep(*, resume: bool = True) -> dict:
    seeds = list(DEV_EVAL_SEEDS)
    results = []
    paths = [MODELS / "step0_random_init.zip"]
    paths += sorted(
        (MODELS / "checkpoints").glob("ppo_apollo_*_steps.zip"), key=_ckpt_step
    )
    paths.append(MODELS / "final_model.zip")
    for p in paths:
        label = p.stem
        out_path = OUT / f"dev_{label}.json"
        if resume and out_path.exists():
            summary = json.loads(out_path.read_text())
            print(f"DEV eval {label}... (cached)", flush=True)
        else:
            print(f"DEV eval {label}...", flush=True)
            summary = eval_model(p, seeds, label)
            out_path.write_text(json.dumps(summary, indent=2))
        slim = {k: v for k, v in summary.items() if k != "episodes"}
        results.append(slim)
    best = max(results, key=lambda r: (r["land_rate"], -r["timeout_rate"]))
    final = next(r for r in results if r["label"] == "final_model")
    report = {
        "seed_pool": "DEV_EVAL_SEEDS",
        "n_seeds": len(seeds),
        "checkpoints": results,
        "best_by_land_rate": best,
        "final_land_rate": final["land_rate"],
        "best_beats_final": best["land_rate"] > final["land_rate"],
    }
    (OUT / "checkpoint_dev_sweep.json").write_text(json.dumps(report, indent=2))
    return report


def step0_heldout_posthoc() -> dict:
    """Post-hoc only — labeled; no tuning on these starts."""
    print("Post-hoc step-0 on V3 held-out (labeled)...", flush=True)
    summary = eval_model(
        MODELS / "step0_random_init.zip",
        list(HELD_OUT_SEEDS),
        "step0_heldout_POSTHOC",
    )
    summary["warning"] = (
        "POST-HOC comparison only. Held-out already inspected for V3 final. "
        "Do not use for model selection or hyperparameter tuning."
    )
    (OUT / "step0_heldout_posthoc.json").write_text(json.dumps(summary, indent=2))
    return {k: v for k, v in summary.items() if k != "episodes"}


def timeout_autopsy(model_path: Path) -> dict:
    """Compare land vs timeout trajectories on DEV with final (or best) model."""
    model = PPO.load(str(model_path))
    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=2000,
        start_mode="research",
        start_template="sh_contact",
        reward_mode="progress_a_prime",
        timeout_as_terminated=True,
        headless=True,
    )
    lands, timeouts = [], []
    try:
        for seed in DEV_EVAL_SEEDS:
            obs, info = env.reset(seed=seed)
            series = []
            while True:
                a, _ = model.predict(obs, deterministic=True)
                obs, _, term, trunc, info = env.step(a)
                series.append(
                    {
                        "t": info["physics_frames"],
                        "alt": float(info["raw"]["altitude"]),
                        "vy": float(info["raw"]["vy"]),
                        "vx": float(info["raw"]["vx"]),
                        "rot": float(info["raw"]["rotation"]),
                        "dx": float(info["raw"]["dx"]),
                        "thrust": float(info["raw"].get("thrust", 0)),
                        "action_thrust_i": int(a[0]),
                        "action_steer_i": int(a[1]),
                    }
                )
                if term or trunc:
                    break
            entry = {
                "seed": seed,
                "status": info["status"],
                "frames": info["physics_frames"],
                "series": series,
                "final": series[-1],
                "mean_thrust_cmd": float(np.mean([THRUST_LEVELS[s["action_thrust_i"]] for s in series])),
                "frac_zero_thrust": float(
                    np.mean([1.0 if s["action_thrust_i"] == 0 else 0.0 for s in series])
                ),
                "frac_full_thrust": float(
                    np.mean([1.0 if s["action_thrust_i"] == 4 else 0.0 for s in series])
                ),
                "mean_abs_rot": float(np.mean([abs(s["rot"]) for s in series])),
                "mean_abs_dx": float(np.mean([abs(s["dx"]) for s in series])),
                "min_alt": float(min(s["alt"] for s in series)),
                "alt_first_quartile": float(series[len(series) // 4]["alt"]),
                "alt_last": float(series[-1]["alt"]),
                "vy_last": float(series[-1]["vy"]),
                "rot_last": float(series[-1]["rot"]),
            }
            if info["landed"]:
                lands.append(entry)
            elif info["timeout"]:
                timeouts.append(entry)
    finally:
        env.close()

    def agg(rows, keys):
        if not rows:
            return {}
        return {k: float(np.mean([r[k] for r in rows])) for k in keys}

    keys = [
        "frames",
        "mean_thrust_cmd",
        "frac_zero_thrust",
        "frac_full_thrust",
        "mean_abs_rot",
        "mean_abs_dx",
        "min_alt",
        "alt_last",
        "vy_last",
        "rot_last",
    ]
    report = {
        "model": str(model_path),
        "n_land": len(lands),
        "n_timeout": len(timeouts),
        "land_means": agg(lands, keys),
        "timeout_means": agg(timeouts, keys),
        "diagnosis": None,
        "timeout_seeds": [t["seed"] for t in timeouts],
        "land_seeds": [t["seed"] for t in lands],
    }
    # Rule-based root cause
    tm, lm = report["timeout_means"], report["land_means"]
    notes = []
    if tm and lm:
        if tm.get("alt_last", 0) > 30 and tm.get("frac_full_thrust", 0) > 0.5:
            notes.append(
                "TIMEOUTS end at high altitude with high full-thrust fraction → prolonged hover / thrust lock"
            )
        if tm.get("mean_abs_rot", 0) > 5 and lm.get("mean_abs_rot", 1) < tm.get("mean_abs_rot", 0):
            notes.append("TIMEOUTS have higher mean |rotation| than landings → attitude not settled")
        if tm.get("frames", 0) >= 1900:
            notes.append("TIMEOUTS hit frame budget (~2000) → delaying terminal rather than committing")
        if tm.get("min_alt", 999) > 20:
            notes.append("TIMEOUTS never get close to surface (min_alt high) → not a near-miss touchdown")
        if abs(tm.get("vy_last", 0)) < 0.05 and tm.get("alt_last", 0) > 50:
            notes.append("TIMEOUTS nearly hover (low |vy|, high alt) at end")
    report["diagnosis"] = notes or ["insufficient contrast; inspect raw series"]
    # Keep one example timeout series (downsampled)
    if timeouts:
        ex = timeouts[0]
        step = max(1, len(ex["series"]) // 40)
        report["example_timeout"] = {
            "seed": ex["seed"],
            "final": ex["final"],
            "series_downsampled": ex["series"][::step],
        }
    if lands:
        ex = lands[0]
        step = max(1, len(ex["series"]) // 40)
        report["example_land"] = {
            "seed": ex["seed"],
            "final": ex["final"],
            "series_downsampled": ex["series"][::step],
        }
    (OUT / "timeout_autopsy.json").write_text(json.dumps(report, indent=2))
    return report


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print("=== freeze ===", flush=True)
    manifest = freeze_manifest()
    print("=== landing replay ===", flush=True)
    replay = verify_landing_replay()
    print("=== mp4 ===", flush=True)
    mp4 = ensure_mp4()
    print("=== step0 held-out posthoc ===", flush=True)
    step0_ho = step0_heldout_posthoc()
    print("=== checkpoint DEV sweep ===", flush=True)
    sweep = checkpoint_dev_sweep()
    best_name = sweep["best_by_land_rate"]["label"]
    best_path = MODELS / "final_model.zip"
    if best_name == "step0_random_init":
        best_path = MODELS / "step0_random_init.zip"
    elif best_name != "final_model":
        cand = MODELS / "checkpoints" / f"{best_name}.zip"
        if cand.exists():
            best_path = cand
        elif (MODELS / f"{best_name}.zip").exists():
            best_path = MODELS / f"{best_name}.zip"
    print(f"=== timeout autopsy on {best_path.name} ===", flush=True)
    autopsy = timeout_autopsy(best_path)

    summary = {
        "freeze_ok": bool(manifest["artifacts"]),
        "landing_replay": {k: replay[k] for k in replay if k != "final_raw"},
        "mp4": mp4,
        "step0_heldout_posthoc": step0_ho,
        "best_dev_checkpoint": sweep["best_by_land_rate"],
        "final_dev_land_rate": sweep["final_land_rate"],
        "best_beats_final": sweep["best_beats_final"],
        "timeout_diagnosis": autopsy["diagnosis"],
        "timeout_means": autopsy.get("timeout_means"),
        "land_means": autopsy.get("land_means"),
    }
    (OUT / "audit_summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    if not replay.get("passed"):
        raise SystemExit("landing replay verification failed")


if __name__ == "__main__":
    main()
