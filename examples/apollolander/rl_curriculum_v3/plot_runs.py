#!/usr/bin/env python3
"""Plot curriculum training curves (raw + rolling)."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def rolling(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) == 0:
        return x
    w = min(w, len(x))
    ker = np.ones(w) / w
    return np.convolve(x, ker, mode="valid")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    csv_path = args.run_dir / "logs" / "learning_curve.csv"
    if not csv_path.is_file():
        raise SystemExit(f"missing {csv_path}")
    rows = list(csv.DictReader(csv_path.open()))
    if not rows:
        raise SystemExit("empty learning curve")
    steps = np.asarray([float(r["global_step"]) for r in rows])
    landed = np.asarray([1.0 if r["landed"] in ("True", "true", "1") else 0.0 for r in rows])
    crashed = np.asarray([1.0 if r["crashed"] in ("True", "true", "1") else 0.0 for r in rows])
    timed = np.asarray([1.0 if r["timed_out"] in ("True", "true", "1") else 0.0 for r in rows])
    rets = np.asarray([float(r["return"]) for r in rows])
    levels = np.asarray([float(r["level_idx"]) for r in rows])

    out = args.run_dir / "plots"
    out.mkdir(exist_ok=True)
    w = 50

    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True)
    axes[0].plot(steps, landed, alpha=0.25, label="raw land")
    if len(landed) >= w:
        axes[0].plot(steps[w - 1 :], rolling(landed, w), label=f"roll{w}")
    axes[0].set_ylabel("landing")
    axes[0].legend()
    axes[0].set_title("Landing / crash / timeout rates and reward")

    axes[1].plot(steps, crashed, alpha=0.25, label="raw crash")
    if len(crashed) >= w:
        axes[1].plot(steps[w - 1 :], rolling(crashed, w), label=f"roll{w}")
    axes[1].set_ylabel("crash")
    axes[1].legend()

    axes[2].plot(steps, timed, alpha=0.25, label="raw timeout")
    if len(timed) >= w:
        axes[2].plot(steps[w - 1 :], rolling(timed, w), label=f"roll{w}")
    axes[2].set_ylabel("timeout")
    axes[2].legend()

    axes[3].plot(steps, rets, alpha=0.25, label="raw return")
    if len(rets) >= w:
        axes[3].plot(steps[w - 1 :], rolling(rets, w), label=f"roll{w}")
    axes[3].plot(steps, levels, color="black", alpha=0.7, label="level_idx")
    axes[3].set_ylabel("return / level")
    axes[3].set_xlabel("physics frames")
    axes[3].legend()
    fig.tight_layout()
    fig.savefig(out / "curriculum_curves.png", dpi=120)
    plt.close(fig)
    print("Wrote", out / "curriculum_curves.png")


if __name__ == "__main__":
    main()
