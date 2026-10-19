#!/usr/bin/env python3
"""Publication-style Phase 4 comparison charts."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "phase4"
CHARTS = OUT / "charts"
CHARTS.mkdir(parents=True, exist_ok=True)

LABELS = ["A native", "B hover+", "C progress"]
KEYS = ["eval_A_best", "eval_B_best", "eval_C_best"]
COLORS = ["#2a6f97", "#c1121f", "#40916c"]


def load(name: str) -> dict:
    return json.loads((OUT / f"{name}.json").read_text())


def style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(True, axis="y", alpha=0.3)


def main() -> None:
    data = [load(k) for k in KEYS]

    # 1) Native mean reward with CI
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    means = [d["mean_reward"] for d in data]
    cis = [d["ci95_mean"] for d in data]
    ax.bar(LABELS, means, yerr=cis, color=COLORS, capsize=6, alpha=0.9)
    ax.axhline(200, color="gray", linestyle="--", label="solved (≥200)")
    ax.set_ylabel("Mean native episode reward")
    ax.set_title("Held-out native evaluation (50 episodes, seeds 50000–50049)")
    ax.legend()
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "native_mean_reward.png", dpi=160)
    plt.close(fig)

    # 2) Success rate ≥200
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    rates = [100 * d["solved_rate"] for d in data]
    ax.bar(LABELS, rates, color=COLORS, alpha=0.9)
    ax.set_ylabel("% episodes with native reward ≥ 200")
    ax.set_ylim(0, 100)
    ax.set_title("Solved-rate comparison (native scoring)")
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "solved_rate.png", dpi=160)
    plt.close(fig)

    # 3) Episode duration
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    means_s = [d["mean_steps"] for d in data]
    med_s = [d["median_steps"] for d in data]
    x = np.arange(len(LABELS))
    w = 0.35
    ax.bar(x - w / 2, means_s, w, label="mean steps", color=COLORS, alpha=0.85)
    ax.bar(x + w / 2, med_s, w, label="median steps", color=COLORS, alpha=0.45)
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS)
    ax.set_ylabel("Episode length (frames)")
    ax.set_title("Episode duration (longer ≈ delayed touchdown / hovering)")
    ax.legend()
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "episode_duration.png", dpi=160)
    plt.close(fig)

    # 4) Timeouts / long episodes
    fig, ax = plt.subplots(figsize=(7.5, 4.5))
    timeouts = [d["timeout_count"] for d in data]
    longs = [d["long_episode_ge_800"] for d in data]
    x = np.arange(len(LABELS))
    ax.bar(x - w / 2, timeouts, w, label="timeouts (1000 steps)", color="#6c757d")
    ax.bar(x + w / 2, longs, w, label="episodes ≥800 steps", color=COLORS, alpha=0.85)
    ax.set_xticks(x)
    ax.set_xticklabels(LABELS)
    ax.set_ylabel("Count / 50 episodes")
    ax.set_title("Delayed / truncated episodes")
    ax.legend()
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "timeouts_long.png", dpi=160)
    plt.close(fig)

    # 5) Training curves side-by-side (native EvalCallback)
    fig, axes = plt.subplots(1, 3, figsize=(12, 3.8), sharey=True)
    runs = [
        ("ppo_baseline", "A native"),
        ("ppo_hover_bad", "B hover+"),
        ("ppo_progress_good", "C progress"),
    ]
    for ax, (run, title), color in zip(axes, runs, COLORS):
        npz = ROOT / "logs" / run / "eval" / "evaluations.npz"
        if npz.exists():
            d = np.load(npz)
            ax.plot(d["timesteps"], d["results"].mean(axis=1), color=color, marker="o", ms=3)
        ax.axhline(200, color="gray", linestyle="--", linewidth=1)
        ax.set_title(title)
        ax.set_xlabel("Timesteps")
        style(ax)
    axes[0].set_ylabel("Mean NATIVE eval reward")
    fig.suptitle("Dev-val EvalCallback curves (native reward, wrappers off)", y=1.02)
    fig.tight_layout()
    fig.savefig(CHARTS / "native_eval_curves.png", dpi=160, bbox_inches="tight")
    plt.close(fig)

    # 6) Combined summary table image-like text chart: reward distributions
    fig, ax = plt.subplots(figsize=(8, 4.5))
    for d, lab, color in zip(data, LABELS, COLORS):
        rewards = [e["reward"] for e in d["episodes_detail"]]
        ax.scatter(
            np.full(len(rewards), LABELS.index(lab)) + np.random.default_rng(0).uniform(-0.08, 0.08, len(rewards)),
            rewards,
            alpha=0.45,
            color=color,
            s=28,
            label=lab,
        )
    ax.axhline(200, color="gray", linestyle="--")
    ax.set_xticks(range(3))
    ax.set_xticklabels(LABELS)
    ax.set_ylabel("Native episode reward")
    ax.set_title("Per-episode native rewards (held-out)")
    style(ax)
    fig.tight_layout()
    fig.savefig(CHARTS / "reward_scatter.png", dpi=160)
    plt.close(fig)

    print("wrote charts to", CHARTS)


if __name__ == "__main__":
    main()
