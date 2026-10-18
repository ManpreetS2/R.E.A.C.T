#!/usr/bin/env python3
"""Learning-from-experience evidence: chronological failure-mode trends.

Plots crash/timeout/landing rates over training episodes and reports whether
failure modes decline (steps, terminal vy/dist when available). Honest if not.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ART = Path("/opt/cursor/artifacts/rl_overnight")


def load_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def fget(row: dict, key: str, default: float = float("nan")) -> float:
    raw = row.get(key, "")
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def rolling_rate(flags: np.ndarray, w: int = 50) -> np.ndarray:
    if len(flags) == 0:
        return flags
    w = min(w, len(flags))
    kern = np.ones(w) / w
    return np.convolve(flags.astype(np.float64), kern, mode="same")


def analyze_run(run_dir: Path) -> dict:
    csv_path = run_dir / "logs" / "learning_curve.csv"
    rows = load_rows(csv_path)
    if not rows:
        return {"run": run_dir.name, "episodes": 0}

    ep = np.arange(len(rows))
    land = np.asarray([int(float(r["landing_success"])) for r in rows])
    crash = np.asarray([int(float(r["crash"])) for r in rows])
    timeout = np.asarray([int(float(r["timeout"])) for r in rows])
    steps = np.asarray([fget(r, "steps") for r in rows])
    ret = np.asarray([fget(r, "episodic_return") for r in rows])
    frames = np.asarray([fget(r, "global_step") for r in rows])
    vy = np.asarray([fget(r, "terminal_vy") for r in rows])
    dist = np.asarray([fget(r, "terminal_dist_to_pad") for r in rows])

    n = len(rows)
    early, late = rows[: max(1, n // 5)], rows[-max(1, n // 5) :]

    def summary(chunk: list[dict]) -> dict:
        c = len(chunk)
        return {
            "n": c,
            "land_rate": sum(int(float(r["landing_success"])) for r in chunk) / c,
            "crash_rate": sum(int(float(r["crash"])) for r in chunk) / c,
            "timeout_rate": sum(int(float(r["timeout"])) for r in chunk) / c,
            "mean_steps": float(np.mean([fget(r, "steps") for r in chunk])),
            "mean_return": float(np.mean([fget(r, "episodic_return") for r in chunk])),
            "mean_terminal_vy": float(np.nanmean([fget(r, "terminal_vy") for r in chunk])),
            "mean_terminal_dist": float(np.nanmean([fget(r, "terminal_dist_to_pad") for r in chunk])),
        }

    early_s, late_s = summary(early), summary(late)
    first_land_idx = next((i for i, v in enumerate(land) if v == 1), None)
    first_land_frames = float(frames[first_land_idx]) if first_land_idx is not None else None

    # Did failure modes improve? Landing up, or crash severity proxies down.
    land_improved = late_s["land_rate"] > early_s["land_rate"] + 0.01
    crash_declined = late_s["crash_rate"] < early_s["crash_rate"] - 0.05
    # Longer flights before crash can mean delay, not skill — report both ways.
    steps_increased = late_s["mean_steps"] > early_s["mean_steps"] * 1.1
    vy_improved = (
        not np.isnan(early_s["mean_terminal_vy"])
        and not np.isnan(late_s["mean_terminal_vy"])
        and abs(late_s["mean_terminal_vy"]) < abs(early_s["mean_terminal_vy"]) * 0.9
    )
    dist_improved = (
        not np.isnan(early_s["mean_terminal_dist"])
        and not np.isnan(late_s["mean_terminal_dist"])
        and late_s["mean_terminal_dist"] < early_s["mean_terminal_dist"] * 0.9
    )

    verdict_parts = []
    if land_improved:
        verdict_parts.append("landing rate rose")
    else:
        verdict_parts.append("landing rate did NOT rise")
    if crash_declined:
        verdict_parts.append("crash rate declined")
    elif late_s["timeout_rate"] > early_s["timeout_rate"] + 0.1:
        verdict_parts.append("timeouts increased (possible hover)")
    else:
        verdict_parts.append("crash/timeout mix did not clearly improve")
    if steps_increased:
        verdict_parts.append(
            f"mean episode length rose ({early_s['mean_steps']:.0f}→{late_s['mean_steps']:.0f}) "
            "— survival longer, not proof of landing skill"
        )
    if vy_improved or dist_improved:
        verdict_parts.append("terminal vy and/or pad distance improved")
    elif not np.isnan(late_s["mean_terminal_vy"]):
        verdict_parts.append("terminal contact metrics did NOT improve")

    report = {
        "run": run_dir.name,
        "episodes": n,
        "physics_frames_span": [float(frames[0]), float(frames[-1])],
        "first_landing_episode": first_land_idx,
        "first_landing_frames": first_land_frames,
        "early": early_s,
        "late": late_s,
        "learning_from_experience_verdict": "; ".join(verdict_parts),
        "failure_modes_declined": bool(land_improved or (vy_improved and dist_improved)),
    }

    # Plots
    out_dir = run_dir / "plots"
    out_dir.mkdir(exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(3, 1, figsize=(9, 8), sharex=True)
    axes[0].plot(ep, rolling_rate(land), label="land roll50")
    axes[0].plot(ep, rolling_rate(crash), label="crash roll50")
    axes[0].plot(ep, rolling_rate(timeout), label="timeout roll50")
    axes[0].set_ylim(-0.05, 1.05)
    axes[0].set_ylabel("rate")
    axes[0].legend(loc="best")
    axes[0].set_title(f"{run_dir.name}: chronological outcome rates")

    axes[1].scatter(ep, steps, s=3, alpha=0.25)
    axes[1].plot(ep, rolling_rate(steps, 50), color="C1")
    axes[1].set_ylabel("episode steps")

    if np.isfinite(vy).any():
        crash_mask = crash.astype(bool)
        axes[2].scatter(ep[crash_mask], np.abs(vy[crash_mask]), s=6, alpha=0.4, label="|vy| at crash")
        if np.isfinite(dist).any():
            axes[2].scatter(ep[crash_mask], dist[crash_mask], s=6, alpha=0.4, label="dist-to-pad at end")
        axes[2].legend(loc="best")
    else:
        axes[2].text(0.5, 0.5, "terminal vy/dist not logged in early phase", ha="center", transform=axes[2].transAxes)
    axes[2].set_xlabel("training episode (chronological)")
    axes[2].set_ylabel("contact metrics")
    fig.tight_layout()
    for dest in (out_dir / "learning_from_experience.png", ART / f"{run_dir.name}_learning_from_experience.png"):
        fig.savefig(dest, dpi=120, bbox_inches="tight")
    plt.close(fig)

    (run_dir / "logs" / "learning_from_experience.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def compare_causality(real_dir: Path, ctrl_dir: Path) -> dict:
    """Compare real-reward vs constant-zero control on behavioral trends."""
    real = analyze_run(real_dir) if (real_dir / "logs" / "learning_curve.csv").exists() else {}
    ctrl = analyze_run(ctrl_dir) if (ctrl_dir / "logs" / "learning_curve.csv").exists() else {}
    out = {
        "real_run": real_dir.name,
        "control_run": ctrl_dir.name,
        "control_label": "constant_zero reward (physics unchanged)",
        "real": real,
        "control": ctrl,
    }
    if real and ctrl and real.get("early") and ctrl.get("early"):
        out["comparison"] = {
            "real_steps_delta": real["late"]["mean_steps"] - real["early"]["mean_steps"],
            "ctrl_steps_delta": ctrl["late"]["mean_steps"] - ctrl["early"]["mean_steps"],
            "real_crash_delta": real["late"]["crash_rate"] - real["early"]["crash_rate"],
            "ctrl_crash_delta": ctrl["late"]["crash_rate"] - ctrl["early"]["crash_rate"],
            "interpretation": (
                "If real-reward run shows larger structured behavioral change "
                "(e.g. longer flights / mode shift) than the zero-reward control "
                "on the same seed/config/budget, that supports reward causality. "
                "If both look similar, changes may be entropy drift / noise."
            ),
        }
    dest = Path("examples/apollolander/rl_overnight/results/causality_comparison.json")
    dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    (ART / "causality_comparison.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, nargs="+", required=True)
    parser.add_argument("--causality-real", type=Path, default=None)
    parser.add_argument("--causality-ctrl", type=Path, default=None)
    args = parser.parse_args()
    for d in args.run_dir:
        report = analyze_run(d)
        print(json.dumps(report, indent=2))
    if args.causality_real and args.causality_ctrl:
        print(json.dumps(compare_causality(args.causality_real, args.causality_ctrl), indent=2))


if __name__ == "__main__":
    main()
