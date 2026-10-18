#!/usr/bin/env python3
"""Record original-game HUD videos for selected checkpoints/seeds.

Seeds are chosen BEFORE seeing outcomes. Uses the overnight browser bridge renderer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from rewardbench.environments.apollolander.starts import derive_start  # noqa: E402
from rewardbench.rl.continuous_policy import ContinuousThrustActorCritic  # noqa: E402
from rewardbench.rl.env import EnvConfig  # noqa: E402
from rewardbench.rl.reserved_seeds import assert_seed_allowed  # noqa: E402
from rewardbench.rl.upstream_env import ApolloLanderUpstreamEnv  # noqa: E402

BRIDGE = "/frontend/apollolander/rl_overnight/browser_rl_bridge.html"
ART = Path("/opt/cursor/artifacts/rl_curriculum_v3")
ART.mkdir(parents=True, exist_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--label", type=str, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--level", type=str, default="apollolander.starts.v1")
    parser.add_argument("--max-steps", type=int, default=4000)
    parser.add_argument("--deterministic", action="store_true")
    args = parser.parse_args()

    # Seeds frozen in argv before outcomes.
    for s in args.seeds:
        assert_seed_allowed(s, context="record_videos")

    device = torch.device("cpu")
    ckpt = torch.load(args.checkpoint, map_location=device, weights_only=False)
    policy = ContinuousThrustActorCritic(hidden=int(ckpt.get("cfg", {}).get("hidden", 128))).to(device)
    policy.load_state_dict(ckpt["policy"])
    policy.eval()
    sha = hashlib.sha256(args.checkpoint.read_bytes()).hexdigest()

    from playwright.sync_api import sync_playwright

    class _RootHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, format, *a):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 8770), _RootHandler)
    Thread(target=server.serve_forever, daemon=True).start()
    time.sleep(0.3)

    env = ApolloLanderUpstreamEnv(
        EnvConfig(
            max_steps=args.max_steps,
            research_mode=True,
            start_schedule_version=args.level,
            vary_fuel=False,
            action_repeat=2,
            bonuses=False,
            locked_camera=True,
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        ),
        reward_mode="touchdown_v1",
    )

    manifests = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 800, "height": 600})
            page.goto(f"http://127.0.0.1:8770{BRIDGE}", wait_until="load")
            page.wait_for_function("() => window.__rl && window.__rl.ready")

            for seed in args.seeds:
                start = derive_start(seed, version=args.level).as_dict()
                obs, _ = env.reset(seed)
                page.evaluate("(cfg) => window.__rl.reset(cfg)", {"start": start, "maxSteps": args.max_steps})
                frames = []
                status = "flying"
                steps = 0
                done = False
                while not done and steps < args.max_steps:
                    with torch.no_grad():
                        t = torch.as_tensor(obs[None], dtype=torch.float32, device=device)
                        if args.deterministic:
                            thrust, rot_idx, _ = policy.act_deterministic(t)
                        else:
                            thrust, rot_idx, _, _, _ = policy.act(t)
                        command = {
                            "thrust": float(thrust.item()),
                            "rotation": int(policy.decode_rotation(rot_idx).item()),
                        }
                    obs, _, terminated, truncated, info = env.step_command(command)
                    # Mirror in browser for rendering (action_repeat=2 → two browser steps)
                    for _ in range(2):
                        step = page.evaluate("(a) => window.__rl.step(a)", command)
                        png = page.evaluate(
                            """() => {
                              const c = document.querySelector('canvas') || (() => {
                                const el = document.createElement('canvas');
                                el.width = 800; el.height = 600; document.body.appendChild(el); return el;
                              })();
                              window.__rl.renderFrame(c);
                              return c.toDataURL('image/png');
                            }"""
                        )
                        frames.append(png)
                        if step["done"]:
                            status = step["status"]
                            break
                    steps = int(info.get("steps", steps + 2))
                    done = terminated or truncated
                    if done:
                        status = info.get("status", status)

                # Write frames via imageio
                import base64
                import io

                import imageio.v2 as imageio
                from PIL import Image

                out_mp4 = ART / f"{args.label}_seed{seed}_{status}.mp4"
                writer = imageio.get_writer(str(out_mp4), fps=30, codec="libx264", quality=8)
                for b64 in frames[::2]:  # ~30fps from 60hz-ish
                    data = base64.b64decode(b64.split(",", 1)[1])
                    img = Image.open(io.BytesIO(data)).convert("RGB")
                    writer.append_data(np.asarray(img))
                writer.close()
                manifest = {
                    "label": args.label,
                    "seed": seed,
                    "level": args.level,
                    "checkpoint": str(args.checkpoint),
                    "checkpoint_sha256": sha,
                    "outcome": status,
                    "steps": steps,
                    "video": str(out_mp4),
                    "env_version": "upstream browser bridge + vm host",
                    "seeds_chosen_before_outcomes": True,
                }
                man_path = ART / f"{args.label}_seed{seed}_{status}.manifest.json"
                man_path.write_text(json.dumps(manifest, indent=2) + "\n")
                manifests.append(manifest)
                print("Wrote", out_mp4, status, flush=True)
            browser.close()
    finally:
        env.close()
        server.shutdown()

    index = ART / f"{args.label}_manifests.json"
    index.write_text(json.dumps(manifests, indent=2) + "\n")
    print("Wrote", index)


if __name__ == "__main__":
    main()
