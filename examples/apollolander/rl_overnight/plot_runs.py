#!/usr/bin/env python3
"""Plot overnight learning curves (raw + rolling) into repo and artifacts."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
ART = Path("/opt/cursor/artifacts/rl_overnight")


def rolling(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) == 0:
        return x
    w = min(w, len(x))
    kern = np.ones(w) / w
    return np.convolve(x, kern, mode="same")


def plot_run(run_dir: Path) -> list[Path]:
    csv_path = run_dir / "logs" / "learning_curve.csv"
    if not csv_path.exists():
        return []
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        return []
    steps = np.asarray([float(r["global_step"]) for r in rows])
    ret = np.asarray([float(r["episodic_return"]) for r in rows])
    land = np.asarray([float(r["landing_success"]) for r in rows])
    crash = np.asarray([float(r["crash"]) for r in rows])
    timeout = np.asarray([float(r["timeout"]) for r in rows])
    fuel = np.asarray([float(r["fuel_used"]) for r in rows])

    out_dir = run_dir / "plots"
    out_dir.mkdir(exist_ok=True)
    ART.mkdir(parents=True, exist_ok=True)
    written = []

    def save(fig, name: str) -> None:
        p1 = out_dir / name
        p2 = ART / f"{run_dir.name}_{name}"
        fig.savefig(p1, dpi=120, bbox_inches="tight")
        fig.savefig(p2, dpi=120, bbox_inches="tight")
        plt.close(fig)
        written.extend([p1, p2])

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(steps, ret, s=4, alpha=0.25, label=f"raw n={len(ret)}")
    ax.plot(steps, rolling(ret, 50), color="C1", label="roll50")
    ax.set_xlabel("physics frames")
    ax.set_ylabel("episodic return")
    ax.set_title(f"{run_dir.name}: reward")
    ax.legend()
    save(fig, "reward.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(steps, rolling(land, 50), label="landing")
    ax.plot(steps, rolling(crash, 50), label="crash")
    ax.plot(steps, rolling(timeout, 50), label="timeout")
    ax.set_ylim(-0.05, 1.05)
    ax.set_xlabel("physics frames")
    ax.set_ylabel("rate (roll50)")
    ax.set_title(f"{run_dir.name}: outcomes")
    ax.legend()
    save(fig, "outcomes.png")

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.scatter(steps, fuel, s=4, alpha=0.25)
    ax.plot(steps, rolling(fuel, 50), color="C2")
    ax.set_xlabel("physics frames")
    ax.set_ylabel("fuel used")
    ax.set_title(f"{run_dir.name}: fuel")
    save(fig, "fuel.png")

    # Stability from update_stats if present
    import json

    us_path = run_dir / "logs" / "update_stats.json"
    if us_path.exists():
        us = json.loads(us_path.read_text())
        if us and us[0].get("entropy") is not None:
            g = [u["global_step"] for u in us]
            fig, axes = plt.subplots(2, 2, figsize=(9, 6))
            axes[0, 0].plot(g, [u.get("entropy") for u in us])
            axes[0, 0].set_title("entropy")
            axes[0, 1].plot(g, [u.get("approx_kl") for u in us])
            axes[0, 1].set_title("approx_kl")
            axes[1, 0].plot(g, [u.get("grad_norm") for u in us])
            axes[1, 0].set_title("grad_norm")
            axes[1, 1].plot(g, [u.get("value_loss") for u in us])
            axes[1, 1].set_title("value_loss")
            for ax in axes.ravel():
                ax.set_xlabel("physics frames")
            fig.suptitle(f"{run_dir.name}: stability")
            fig.tight_layout()
            save(fig, "stability.png")
    return written


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    for d in args.run_dir:
        paths = plot_run(d)
        print(d, "wrote", len(paths), "files")


if __name__ == "__main__":
    main()
