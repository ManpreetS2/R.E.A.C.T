#!/usr/bin/env python3
"""Capture original-canvas PNG frames for a policy episode (native renderer)."""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym  # noqa: E402
from env.controllers import noop_action, reference_continuous_command  # noqa: E402
from env.starts import resolve_start  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="pilot_near")
    ap.add_argument("--policy", choices=["noop", "reference", "ppo"], default="ppo")
    ap.add_argument("--model", default=None)
    ap.add_argument("--seed", type=int, default=50_000)
    ap.add_argument("--hold-end-frames", type=int, default=90)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out = Path(args.out_dir) if args.out_dir else ROOT / "outputs" / "videos" / f"{args.policy}_{args.seed}"
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    env = ApolloLanderGym(
        action_repeat=4,
        max_physics_frames=8000,
        start_mode="research",
        start_override=resolve_start(args.start),
        reward_mode="progress_a",
        headless=True,
        render_mode="rgb_array",
    )
    model = PPO.load(args.model) if args.model else None
    if args.policy == "ppo" and model is None:
        raise SystemExit("--model required for ppo")

    obs, info = env.reset(seed=args.seed)
    idx = 0
    final_info = info
    try:
        while True:
            png_b64 = env._page.evaluate("() => window.ApolloOriginal.snapshotPNG()")
            raw = base64.b64decode(png_b64.split(",", 1)[1])
            (frames_dir / f"frame_{idx:05d}.png").write_bytes(raw)
            idx += 1

            if args.policy == "noop":
                obs, _r, term, trunc, info = env.step(noop_action(obs))
            elif args.policy == "reference":
                cmd = reference_continuous_command(info["raw"])
                obs, _r, term, trunc, info = env.step_absolute(
                    cmd["thrust"], cmd["rotation"], repeats=1
                )
            else:
                action, _ = model.predict(obs, deterministic=True)
                obs, _r, term, trunc, info = env.step(action)
            final_info = info
            if term or trunc:
                break

        # Hold ending so native HUD / crash debris is visible
        for _ in range(args.hold_end_frames):
            png_b64 = env._page.evaluate("() => window.ApolloOriginal.snapshotPNG()")
            raw = base64.b64decode(png_b64.split(",", 1)[1])
            (frames_dir / f"frame_{idx:05d}.png").write_bytes(raw)
            idx += 1
            # Advance particles/render without physics if bridge loop is in step mode
            env._page.evaluate(
                "() => { if (typeof updateParticles==='function') updateParticles(); if (typeof render==='function') render(); }"
            )
    finally:
        env.close()

    meta = {
        "start": args.start,
        "policy": args.policy,
        "seed": args.seed,
        "frames": idx,
        "status": final_info.get("status"),
        "landed": final_info.get("landed"),
        "native_score": final_info.get("native_score"),
        "credit": "Seb Lee-Delisle ApolloLander (MIT) — unmodified renderer frames",
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    # Optional ffmpeg assemble
    mp4 = out / "episode.mp4"
    import subprocess

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        "30",
        "-i",
        str(frames_dir / "frame_%05d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(mp4),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        meta["mp4"] = str(mp4)
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
        print(f"Wrote {mp4}")
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Frames saved under {frames_dir} (ffmpeg skipped: {exc})")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
