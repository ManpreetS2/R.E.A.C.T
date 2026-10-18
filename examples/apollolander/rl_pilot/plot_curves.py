#!/usr/bin/env python3
"""Plot raw learning curves from training logs (no smoothing that hides failures)."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def rolling_mean(values: np.ndarray, window: int) -> np.ndarray:
    if len(values) == 0:
        return values
    window = max(1, min(window, len(values)))
    cumsum = np.cumsum(np.insert(values, 0, 0.0))
    return (cumsum[window:] - cumsum[:-window]) / window


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--prefix", type=str, default="learning")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = read_csv(args.log)
    if not rows:
        raise SystemExit(f"no rows in {args.log}")

    steps = np.asarray([float(r["global_step"]) for r in rows], dtype=np.float64)
    returns = np.asarray([float(r["episodic_return"]) for r in rows], dtype=np.float64)
    land = np.asarray([float(r["landing_success"]) for r in rows], dtype=np.float64)
    crash = np.asarray([float(r["crash"]) for r in rows], dtype=np.float64)
    timeout = np.asarray([float(r["timeout"]) for r in rows], dtype=np.float64)
    fuel = np.asarray([float(r["fuel_used"]) for r in rows], dtype=np.float64)

    # Raw scatter + light rolling mean overlay (raw points always shown).
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    panels = [
        (axes[0, 0], returns, "Episodic return (raw)", "return"),
        (axes[0, 1], land, "Landing success (1/0 raw)", "landing_rate"),
        (axes[1, 0], crash, "Crash (1/0 raw)", "crash_rate"),
        (axes[1, 1], timeout, "Timeout (1/0 raw)", "timeout_rate"),
    ]
    for ax, values, title, _ in panels:
        ax.scatter(steps, values, s=4, alpha=0.25, c="#1f4e79", label="raw episodes")
        if len(values) >= 20:
            w = min(50, max(5, len(values) // 20))
            rm = rolling_mean(values, w)
            ax.plot(steps[w - 1 :], rm, color="#c45c26", linewidth=1.5, label=f"rolling mean w={w}")
        ax.set_title(title)
        ax.set_xlabel("cumulative env steps")
        ax.legend(loc="best", fontsize=8)
    fig.suptitle("ApolloLander PPO learning curves (failures not omitted)")
    out1 = args.out_dir / f"{args.prefix}_curves.png"
    fig.savefig(out1, dpi=140)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4), constrained_layout=True)
    ax.scatter(steps, fuel, s=4, alpha=0.25, c="#1f4e79", label="raw")
    if len(fuel) >= 20:
        w = min(50, max(5, len(fuel) // 20))
        ax.plot(steps[w - 1 :], rolling_mean(fuel, w), color="#c45c26", linewidth=1.5, label=f"rolling mean w={w}")
    ax.set_title("Fuel used per episode (raw)")
    ax.set_xlabel("cumulative env steps")
    ax.set_ylabel("fuel used")
    ax.legend(fontsize=8)
    out2 = args.out_dir / f"{args.prefix}_fuel.png"
    fig.savefig(out2, dpi=140)
    plt.close(fig)
    print(f"wrote {out1}")
    print(f"wrote {out2}")


if __name__ == "__main__":
    main()
