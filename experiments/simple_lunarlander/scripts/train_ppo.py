#!/usr/bin/env python3
"""Train PPO(MlpPolicy) on LunarLander-v3 with optional reward wrappers.

EvalCallback always uses NATIVE reward (wrappers off) so checkpoint selection
matches Experiment A protocol.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import gymnasium as gym
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from rewards import wrap_reward  # noqa: E402

REWARD_META = {
    "native": {
        "label": "native_builtin",
        "equation": "R = r_native",
    },
    "hover_bad": {
        "label": "native_plus_hover_bonus",
        "equation": "R = r_native + 1[|angle|<0.2 and speed<0.5]",
        "upright_thresh": 0.2,
        "speed_thresh": 0.5,
    },
    "progress_good": {
        "label": "native_plus_potential_delta_minus_time",
        "equation": "R = r_native + (Phi(s_t)-Phi(s_{t-1})) - 0.05",
        "time_cost": 0.05,
    },
}


def make_env(
    seed: int,
    rank: int = 0,
    monitor_dir: Path | None = None,
    reward_mode: str = "native",
):
    def _thunk():
        env = gym.make("LunarLander-v3")
        env = wrap_reward(env, reward_mode)
        if monitor_dir is not None:
            monitor_dir.mkdir(parents=True, exist_ok=True)
            env = Monitor(env, filename=str(monitor_dir / f"train_{rank}"))
        else:
            env = Monitor(env)
        env.reset(seed=seed + rank)
        return env

    return _thunk


def plot_learning_curve(monitor_csv: Path, out_png: Path, ylabel: str) -> None:
    if not monitor_csv.exists():
        candidates = list(monitor_csv.parent.glob("*.monitor.csv"))
        if not candidates:
            print(f"No monitor CSV found near {monitor_csv}")
            return
        monitor_csv = candidates[0]

    df = pd.read_csv(monitor_csv, comment="#")
    if "r" not in df.columns:
        print(f"Unexpected monitor columns: {df.columns.tolist()}")
        return
    rewards = df["r"].to_numpy()
    window = min(50, max(1, len(rewards) // 10))
    if len(rewards) >= window:
        smooth = np.convolve(rewards, np.ones(window) / window, mode="valid")
        x_smooth = np.arange(window - 1, len(rewards))
    else:
        smooth = rewards
        x_smooth = np.arange(len(rewards))

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.plot(rewards, alpha=0.35, label="episode return (training signal)")
    ax.plot(x_smooth, smooth, label=f"moving avg (w={window})")
    ax.axhline(200, color="green", linestyle="--", linewidth=1, label="native solved line (≥200)")
    ax.set_xlabel("Episode")
    ax.set_ylabel(ylabel)
    ax.set_title("PPO LunarLander-v3 — training returns")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=140)
    plt.close(fig)
    print(f"wrote {out_png}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timesteps", type=int, default=1_000_000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-envs", type=int, default=4)
    parser.add_argument("--checkpoint-freq", type=int, default=50_000)
    parser.add_argument("--eval-freq", type=int, default=25_000)
    parser.add_argument("--eval-episodes", type=int, default=10)
    parser.add_argument("--run-name", type=str, required=True)
    parser.add_argument(
        "--reward-mode",
        choices=["native", "hover_bad", "progress_good"],
        default="native",
    )
    args = parser.parse_args()

    run_dir = ROOT / "outputs" / args.run_name
    model_dir = ROOT / "models" / args.run_name
    log_dir = ROOT / "logs" / args.run_name
    for d in (run_dir, model_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    rmeta = REWARD_META[args.reward_mode]
    meta = {
        "env_id": "LunarLander-v3",
        "algo": "PPO",
        "policy": "MlpPolicy",
        "net_arch": [64, 64],
        "timesteps": args.timesteps,
        "seed": args.seed,
        "n_envs": args.n_envs,
        "reward_mode": args.reward_mode,
        "reward": rmeta,
        "eval_callback_reward": "native_only",
        "eval_seed_base": args.seed + 10_000,
        "checkpoint_selection": "EvalCallback best mean native reward",
        "started_unix": time.time(),
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    monitor_dir = run_dir / "monitor"
    train_env = DummyVecEnv(
        [
            make_env(args.seed, i, monitor_dir=monitor_dir, reward_mode=args.reward_mode)
            for i in range(args.n_envs)
        ]
    )
    # Dev-val: native reward only (identical protocol to Experiment A).
    eval_env = DummyVecEnv(
        [make_env(args.seed + 10_000, 0, reward_mode="native")]
    )

    model = PPO(
        "MlpPolicy",
        train_env,
        verbose=1,
        seed=args.seed,
        tensorboard_log=str(log_dir),
        policy_kwargs=dict(net_arch=dict(pi=[64, 64], vf=[64, 64])),
    )

    checkpoint_cb = CheckpointCallback(
        save_freq=max(args.checkpoint_freq // args.n_envs, 1),
        save_path=str(model_dir / "checkpoints"),
        name_prefix="ppo_lunar",
        save_replay_buffer=False,
        save_vecnormalize=False,
    )
    eval_cb = EvalCallback(
        eval_env,
        best_model_save_path=str(model_dir / "best"),
        log_path=str(log_dir / "eval"),
        eval_freq=max(args.eval_freq // args.n_envs, 1),
        n_eval_episodes=args.eval_episodes,
        deterministic=True,
        render=False,
    )

    ylabel = (
        "Shaped episode return"
        if args.reward_mode != "native"
        else "Native episode reward"
    )
    print(
        f"Training PPO reward_mode={args.reward_mode} for {args.timesteps} steps "
        f"(seed={args.seed}, n_envs={args.n_envs}); EvalCallback=NATIVE…"
    )
    t0 = time.time()
    model.learn(
        total_timesteps=args.timesteps,
        callback=[checkpoint_cb, eval_cb],
        progress_bar=False,
    )
    elapsed = time.time() - t0

    final_path = model_dir / "ppo_lunar_final.zip"
    model.save(str(final_path))
    print(f"saved final model -> {final_path} ({elapsed / 60:.1f} min)")

    monitor_files = sorted(monitor_dir.glob("*.monitor.csv"))
    if monitor_files:
        frames = [pd.read_csv(f, comment="#") for f in monitor_files]
        merged = pd.concat(frames, ignore_index=True)
        if "t" in merged.columns:
            merged = merged.sort_values("t").reset_index(drop=True)
        merged_path = monitor_dir / "merged_episodes.csv"
        merged.to_csv(merged_path, index=False)
        plot_learning_curve(merged_path, run_dir / "learning_curve.png", ylabel=ylabel)

    eval_npz = log_dir / "eval" / "evaluations.npz"
    if eval_npz.exists():
        data = np.load(eval_npz)
        means = data["results"].mean(axis=1)
        timesteps = data["timesteps"]
        fig, ax = plt.subplots(figsize=(8, 4.5))
        ax.plot(timesteps, means, marker="o")
        ax.axhline(200, color="green", linestyle="--", label="solved (≥200)")
        ax.set_xlabel("Timesteps")
        ax.set_ylabel("Mean NATIVE eval reward")
        ax.set_title(f"PPO {args.run_name} — periodic native EvalCallback")
        ax.legend()
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(run_dir / "eval_curve.png", dpi=140)
        plt.close(fig)
        print(f"wrote {run_dir / 'eval_curve.png'}")
        print(
            "native eval means (last 5):",
            [round(float(x), 1) for x in means[-5:]],
            "best=",
            round(float(means.max()), 1),
        )

    meta["finished_unix"] = time.time()
    meta["elapsed_seconds"] = elapsed
    meta["final_model"] = str(final_path)
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2) + "\n")

    train_env.close()
    eval_env.close()


if __name__ == "__main__":
    main()
