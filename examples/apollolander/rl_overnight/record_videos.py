#!/usr/bin/env python3
"""Record episodes with the ORIGINAL upstream browser renderer (Chromium).

Replays the recorded action sequence in upstream Lander/Landscape draw calls.
Does NOT use the old research visualizer.
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import numpy as np
import torch
from playwright.sync_api import sync_playwright

from rewardbench.rl.env import EnvConfig
from rewardbench.rl.policy import ActorCritic
from rewardbench.rl.reserved_seeds import assert_seed_allowed
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv
from rewardbench.rl.physics_python import decode_action

ROOT = Path(__file__).resolve().parents[3]
ART = Path("/opt/cursor/artifacts/rl_overnight")
BRIDGE = "/frontend/apollolander/rl_overnight/browser_rl_bridge.html"


def load_policy(ckpt: Path) -> ActorCritic:
    payload = torch.load(ckpt, map_location="cpu", weights_only=False)
    hidden = int(payload.get("ppo_config", {}).get("hidden", 128))
    policy = ActorCritic(10, 95, hidden)
    policy.load_state_dict(payload["policy_state_dict"])
    policy.eval()
    return policy


def collect_trace(ckpt: Path | None, seed: int, random_policy: bool = False) -> dict[str, Any]:
    assert_seed_allowed(seed, context="record_videos")
    env = ApolloLanderUpstreamEnv(EnvConfig(action_repeat=2, max_steps=8000), reward_mode="research_shaped")
    try:
        obs, info = env.reset(seed)
        actions: list[dict[str, float]] = []
        policy = None if random_policy or ckpt is None else load_policy(ckpt)
        done = False
        last = info
        while not done:
            if random_policy or policy is None:
                idx = int(np.random.randint(0, 95))
            else:
                with torch.no_grad():
                    dist, _ = policy.forward(torch.as_tensor(obs).unsqueeze(0))
                    idx = int(torch.argmax(dist.probs, dim=-1).item())
            cmd = decode_action(idx)
            # Expand action-repeat into per-physics-frame commands for faithful replay.
            for _ in range(2):
                actions.append({"thrust": float(cmd["thrust"]), "rotation": float(cmd["rotation"])})
            obs, _, term, trunc, last = env.step(idx)
            done = bool(term or trunc)
        return {
            "seed": seed,
            "start": info["start"],
            "actions": actions,
            "native_status": last.get("status"),
            "landed": bool(last.get("landed")),
            "crashed": bool(last.get("crashed")),
            "timed_out": bool(last.get("timed_out")),
            "checkpoint": str(ckpt) if ckpt else "random",
        }
    finally:
        env.close()


def render_trace(trace: dict[str, Any], out_mp4: Path, fps: int = 30) -> dict[str, Any]:
    ART.mkdir(parents=True, exist_ok=True)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, format, *args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 8766), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.2)

    manifest = {
        "checkpoint_id": trace["checkpoint"],
        "env_version": "upstream_vm_host + browser_rl_bridge (original Lander/Landscape render)",
        "seed": trace["seed"],
        "start": trace["start"],
        "native_outcome_env": trace["native_status"],
        "video": str(out_mp4),
    }
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(f"http://127.0.0.1:8766{BRIDGE}", wait_until="load")
            page.wait_for_function("() => window.__rl && window.__rl.ready")
            page.evaluate("(cfg) => window.__rl.reset(cfg)", {"start": trace["start"], "maxSteps": 20000})
            # Record via page screenshot frames → imageio
            import imageio.v2 as imageio

            frames = []
            last_status = "flying"
            for i, action in enumerate(trace["actions"]):
                step = page.evaluate("(a) => window.__rl.step(a)", action)
                last_status = step["status"]
                page.evaluate("() => window.__rl.renderFrame()")
                png = page.screenshot(type="png")
                frames.append(imageio.imread(png))
                if step["done"]:
                    # Hold final frame briefly
                    for _ in range(fps):
                        frames.append(frames[-1])
                    break
                # Subsample for file size: keep every other frame if very long
                if i > 2000 and i % 2 == 1:
                    frames.pop()
            imageio.mimsave(out_mp4, frames, fps=fps)
            browser.close()
            manifest["native_outcome_replay"] = last_status
            manifest["outcome_match"] = last_status == trace["native_status"]
            manifest["n_frames"] = len(frames)
    finally:
        server.shutdown()

    man_path = out_mp4.with_suffix(".manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, default=None)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--random", action="store_true")
    args = parser.parse_args()
    # Seeds chosen before seeing outcomes (caller responsibility).
    trace = collect_trace(args.checkpoint, args.seed, random_policy=args.random)
    man = render_trace(trace, args.out)
    print(json.dumps(man, indent=2))


if __name__ == "__main__":
    main()
