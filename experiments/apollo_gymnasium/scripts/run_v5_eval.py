#!/usr/bin/env python3
"""V5 post-train: DEV selection + one-shot held-out vs V3-40k + re-ascent audit."""

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

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import noop_action, random_action, reference_guidance_action  # noqa: E402
from env.seeds import DEV_EVAL_SEEDS, V5_HELD_OUT_SEEDS  # noqa: E402

RUN = "ppo_pilot_v5_commitment"
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


def make_env(*, commitment: bool, port: int = 18900) -> ApolloLanderGym:
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


def classify_failure(info: dict, series: list[dict]) -> str | None:
    if info.get("landed"):
        return None
    if info.get("crashed"):
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
        "reascent_count": modes.get("timeout_post_approach_reascent", 0),
        "reascent_rate": modes.get("timeout_post_approach_reascent", 0) / max(n, 1),
    }


def eval_model(
    path: Path,
    seeds: list[int],
    label: str,
    *,
    deterministic: bool = True,
    commitment: bool,
    port: int,
) -> dict:
    model = PPO.load(str(path)) if path else None
    env = make_env(commitment=commitment, port=port)
    rng = np.random.default_rng(0)
    rows = []
    try:
        for seed in seeds:
            for attempt in range(3):
                try:
                    if attempt:
                        env.close()
                        env = make_env(commitment=commitment, port=port)
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
    summary["commitment_env"] = commitment
    summary["episodes"] = rows
    return summary


def eval_baseline(policy: str, seeds: list[int], port: int) -> dict:
    # Baselines use 10-D A′ env (commitment irrelevant for native metrics).
    env = make_env(commitment=False, port=port)
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


def select_best_dev() -> tuple[dict, Path]:
    seeds = list(DEV_EVAL_SEEDS)
    paths = [MODELS / "step0_random_init.zip"]
    paths += sorted((MODELS / "checkpoints").glob("ppo_apollo_*_steps.zip"), key=_ckpt_step)
    paths.append(MODELS / "final_model.zip")
    results = []
    port = 18910
    for p in paths:
        if not p.exists():
            continue
        label = p.stem
        print(f"DEV eval {label}...", flush=True)
        summary = eval_model(
            p, seeds, label, deterministic=True, commitment=True, port=port
        )
        port += 1
        slim = {k: v for k, v in summary.items() if k != "episodes"}
        results.append(slim)
        (OUT / f"dev_{label}.json").write_text(json.dumps(summary, indent=2))

    def key(r):
        return (r["land_rate"], -r["timeout_rate"], -r["mean_physics_frames"])

    best = max(results, key=key)
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
    freeze_dir = MODELS / "selected"
    freeze_dir.mkdir(parents=True, exist_ok=True)
    dest = freeze_dir / "selected_model.zip"
    shutil.copy2(best_path, dest)
    (freeze_dir / "selection.json").write_text(json.dumps(sel, indent=2))
    (OUT / "dev_selection.json").write_text(json.dumps(sel, indent=2))
    return sel, best_path


def paired_landing_diff(v5_eps: list[dict], v3_eps: list[dict]) -> dict:
    by5 = {e["seed"]: e for e in v5_eps}
    by3 = {e["seed"]: e for e in v3_eps}
    seeds = sorted(set(by5) & set(by3))
    both_land = sum(1 for s in seeds if by5[s]["landed"] and by3[s]["landed"])
    v5_only = sum(1 for s in seeds if by5[s]["landed"] and not by3[s]["landed"])
    v3_only = sum(1 for s in seeds if by3[s]["landed"] and not by5[s]["landed"])
    neither = sum(1 for s in seeds if not by5[s]["landed"] and not by3[s]["landed"])
    return {
        "n_paired": len(seeds),
        "both_land": both_land,
        "v5_only_land": v5_only,
        "v3_only_land": v3_only,
        "neither_land": neither,
        "net_v5_minus_v3": v5_only - v3_only,
    }


def heldout_comparison(v5_path: Path) -> dict:
    seeds = list(V5_HELD_OUT_SEEDS)
    print("=== one-shot V5 held-out comparison (500000–500019) ===", flush=True)
    results = {}
    full = {}
    specs = [
        ("v5_selected_det", v5_path, True, True, 19000),
        ("v5_selected_stoch", v5_path, False, True, 19001),
        ("v3_40k_det", V3_40K, True, False, 19002),
        ("v5_step0_det", MODELS / "step0_random_init.zip", True, True, 19003),
    ]
    for name, path, det, commitment, port in specs:
        print(f"  eval {name}...", flush=True)
        s = eval_model(
            path, seeds, name, deterministic=det, commitment=commitment, port=port
        )
        (OUT / f"heldout_{name}.json").write_text(json.dumps(s, indent=2))
        results[name] = {k: v for k, v in s.items() if k != "episodes"}
        full[name] = s

    for i, name in enumerate(("noop", "random", "reference")):
        print(f"  baseline {name}...", flush=True)
        s = eval_baseline(name, seeds, port=19100 + i)
        (OUT / f"heldout_{name}.json").write_text(json.dumps(s, indent=2))
        results[name] = {k: v for k, v in s.items() if k != "episodes"}
        full[name] = s

    v5 = results["v5_selected_det"]
    v3 = results["v3_40k_det"]
    paired = paired_landing_diff(
        full["v5_selected_det"]["episodes"], full["v3_40k_det"]["episodes"]
    )
    reascent = {
        "v5_reascent_rate": v5.get("reascent_rate"),
        "v3_reascent_rate": v3.get("reascent_rate"),
        "v5_reascent_count": v5.get("reascent_count"),
        "v3_reascent_count": v3.get("reascent_count"),
        "reduced_reascent": v5.get("reascent_rate", 1) < v3.get("reascent_rate", 0),
    }
    comparison = {
        "seed_pool": "V5_HELD_OUT_SEEDS",
        "seeds": seeds,
        "by_policy": results,
        "paired_landing_diff_v5_vs_v3": paired,
        "reascent_comparison": reascent,
        "v5_vs_v3_40k": {
            "v5_land_rate": v5["land_rate"],
            "v3_land_rate": v3["land_rate"],
            "v5_land_wilson95": v5["land_rate_wilson95"],
            "v3_land_wilson95": v3["land_rate_wilson95"],
            "delta_land_rate": v5["land_rate"] - v3["land_rate"],
            "v5_improved": v5["land_rate"] > v3["land_rate"],
            "v5_timeout_rate": v5["timeout_rate"],
            "v3_timeout_rate": v3["timeout_rate"],
            "v5_perfect_rate": v5["perfect_rate"],
            "v3_perfect_rate": v3["perfect_rate"],
            "v5_hard_landing_rate": v5["hard_landing_rate"],
            "v3_hard_landing_rate": v3["hard_landing_rate"],
            "v5_mean_frames": v5["mean_physics_frames"],
            "v3_mean_frames": v3["mean_physics_frames"],
            "v5_mean_fuel": v5["mean_fuel_remaining"],
            "v3_mean_fuel": v3["mean_fuel_remaining"],
        },
        "warning": "ONE-SHOT held-out. Not used for selection or retraining.",
    }
    (OUT / "heldout_comparison.json").write_text(json.dumps(comparison, indent=2))
    return comparison, full


def record_video(model_path: Path, seed: int, tag: str, *, commitment: bool) -> Path:
    import base64

    import imageio_ffmpeg

    out = EVIDENCE / tag
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    model = PPO.load(str(model_path))
    env = make_env(commitment=commitment, port=19200)
    env.render_mode = "rgb_array"
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
            "commitment_env": commitment,
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


def write_results_md(report: dict) -> None:
    sel = report["dev_selection"]["selected"]
    cmp_ = report["heldout_comparison"]["v5_vs_v3_40k"]
    re = report["heldout_comparison"]["reascent_comparison"]
    paired = report["heldout_comparison"]["paired_landing_diff_v5_vs_v3"]
    improved = report["improved_over_v3_40k_heldout"]
    lines = [
        "# V5 results — `ppo_pilot_v5_commitment`",
        "",
        f"**Preflight:** PASSED (`outputs/preflight_v5/preflight_report.json`)",
        f"**Physics budget:** {report['train_summary']['actual_physics_frames']} "
        f"(cap 200000)",
        "**Sole change vs V3 A′:** late-approach commitment shaping "
        "(β=1, H=25, D=60, V_soft=0.15, R_soft=15°) + approached obs bit",
        "",
        "V4 time-cost negative result preserved. V3-40k incumbent untouched.",
        "",
        "---",
        "",
        "## Selected checkpoint (DEV 200000–200019 only)",
        "",
        f"| Selected | `{sel['label']}` |",
        f"| DEV land | **{sel['land_count']}/20 = {sel['land_rate']*100:.0f}%** |",
        f"| DEV timeout | {sel['timeout_count']}/20 |",
        f"| DEV reascent | {sel.get('reascent_count', '?')} |",
        f"| Beats V3-40k DEV (60%)? | **{'Yes' if report['improved_over_v3_40k_dev'] else 'No'}** |",
        "",
        "## One-shot held-out (500000–500019, n=20)",
        "",
        "| Policy | Land | Perfect | Hard | Crash | Timeout | Reascent | Mean frames | Mean fuel |",
        "|--------|-----:|--------:|-----:|------:|--------:|---------:|------------:|----------:|",
    ]
    for key, label in [
        ("v5_selected_det", "V5 selected det"),
        ("v5_selected_stoch", "V5 selected stoch"),
        ("v3_40k_det", "V3-40k det (incumbent)"),
        ("v5_step0_det", "V5 step-0"),
        ("noop", "No-op"),
        ("random", "Random"),
        ("reference", "Legal reference"),
    ]:
        p = report["heldout_comparison"]["by_policy"][key]
        lines.append(
            f"| {label} | {p['land_count']}/20 ({p['land_rate']*100:.0f}%) | "
            f"{p['perfect_count']} | {p['hard_landing_count']} | {p['crash_count']} | "
            f"{p['timeout_count']} | {p.get('reascent_count', 0)} | "
            f"{p['mean_physics_frames']:.0f} | {p['mean_fuel_remaining']:.0f} |"
        )
    lines += [
        "",
        f"**Δ land rate (V5 − V3-40k) = {cmp_['delta_land_rate']*100:+.0f} pp. "
        f"{'V5 improved.' if improved else 'V5 did not improve.'}**",
        "",
        f"Paired seeds: both={paired['both_land']}, V5-only={paired['v5_only_land']}, "
        f"V3-only={paired['v3_only_land']}, neither={paired['neither_land']} "
        f"(net {paired['net_v5_minus_v3']:+d}).",
        "",
        f"Re-ascent: V5 {re['v5_reascent_count']}/20 vs V3 {re['v3_reascent_count']}/20 "
        f"(reduced={re['reduced_reascent']}).",
        "",
        "## Champion",
        "",
        (
            "**V5 becomes champion** — held-out native land rate exceeds V3-40k."
            if improved
            else "**Preserve V3-40k as champion.** Commitment shaping did not improve "
            "reliable landing on the held-out pool."
        ),
        "",
        "## Claims we are **not** making",
        "",
        "- Not ready for A/B/C/D",
        "- Not merging PR #11 on this result alone",
        "- Not that original_fixed / full-game start is solved",
        "",
    ]
    (OUT / "V5_RESULTS.md").write_text("\n".join(lines))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    train = json.loads((OUT / "train_summary.json").read_text())
    assert train["actual_physics_frames"] <= 200_000, train["actual_physics_frames"]

    sel, best_path = select_best_dev()
    comparison, full = heldout_comparison(best_path)

    held = full["v5_selected_det"]
    success = next((e for e in held["episodes"] if e["landed"]), None)
    failure = next((e for e in held["episodes"] if not e["landed"]), None)
    videos = {}
    if success:
        print(f"Recording success seed={success['seed']}...", flush=True)
        videos["success"] = str(
            record_video(
                best_path, success["seed"], f"success_{success['seed']}", commitment=True
            )
        )
    if failure:
        print(f"Recording failure seed={failure['seed']}...", flush=True)
        videos["failure"] = str(
            record_video(
                best_path, failure["seed"], f"failure_{failure['seed']}", commitment=True
            )
        )

    report = {
        "run": RUN,
        "train_summary": train,
        "dev_selection": {k: v for k, v in sel.items() if k != "checkpoints"}
        | {"n_checkpoints": len(sel["checkpoints"]), "selected": sel["selected"]},
        "heldout_comparison": comparison,
        "videos": videos,
        "improved_over_v3_40k_heldout": comparison["v5_vs_v3_40k"]["v5_improved"],
        "improved_over_v3_40k_dev": sel["beats_v3_40k_on_dev"],
        "champion": (
            "v5_selected"
            if comparison["v5_vs_v3_40k"]["v5_improved"]
            else "v3_40k_incumbent"
        ),
    }
    (OUT / "V5_RESULTS.json").write_text(json.dumps(report, indent=2))
    write_results_md(report)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
