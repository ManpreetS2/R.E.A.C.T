#!/usr/bin/env python3
"""Plot Monitor episode rewards from a PPO run."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_monitor(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rewards, lengths = [], []
    with path.open() as f:
        # SB3 monitor: first line is JSON meta comment
        lines = [ln for ln in f if not ln.startswith("#")]
    reader = csv.DictReader(lines)
    for row in reader:
        rewards.append(float(row["r"]))
        lengths.append(float(row["l"]))
    return np.asarray(rewards), np.asarray(lengths)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--monitor", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--window", type=int, default=10)
    args = ap.parse_args()

    rewards, lengths = load_monitor(Path(args.monitor))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    fig, axes = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
    x = np.arange(1, len(rewards) + 1)
    if len(rewards) >= args.window:
        kernel = np.ones(args.window) / args.window
        smooth = np.convolve(rewards, kernel, mode="valid")
        axes[0].plot(x[args.window - 1 :], smooth, label=f"reward MA-{args.window}")
    axes[0].plot(x, rewards, alpha=0.25, label="reward")
    axes[0].set_ylabel("episode return (train)")
    axes[0].legend()
    axes[0].set_title("ApolloLander Gymnasium PPO — learning curve")

    axes[1].plot(x, lengths, alpha=0.7)
    axes[1].set_xlabel("episode")
    axes[1].set_ylabel("episode length (gym steps)")
    fig.tight_layout()
    fig.savefig(out, dpi=140)
    print(f"Wrote {out} ({len(rewards)} episodes)")


if __name__ == "__main__":
    main()
