#!/usr/bin/env python3
"""Render authentic Node-path footage for fixed held-out seeds (no cherry-picking)."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

from rewardbench.environments.apollolander import ApolloLanderAdapter
from rewardbench.rl.env import EnvConfig
from rewardbench.rl.node_eval import load_policy, policy_action_fn, run_episode_node

HERE = Path(__file__).resolve().parent
ARTIFACTS = Path("/opt/cursor/artifacts")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=HERE / "config.yaml")
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument(
        "--checkpoints",
        nargs="+",
        default=["step0", "step500000", "final"],
        help="Checkpoint tags chosen before looking at footage outcomes",
    )
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    raw = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    footage_seeds = list(raw["eval"]["footage_held_out_seeds"])
    env_raw = raw["env"]
    max_steps = int(env_raw["max_steps"])
    out = args.run_dir / "footage"
    out.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    adapter = ApolloLanderAdapter(research_mode=True, max_steps=max_steps)
    manifest: list[dict] = []
    for tag in args.checkpoints:
        ckpt = args.run_dir / "checkpoints" / f"{tag}.pt"
        if not ckpt.exists():
            # Fall back to nearest existing intermediate if exact tag missing.
            print(f"missing {ckpt}, skipping")
            continue
        policy, _ = load_policy(ckpt, device=args.device)
        action_fn = policy_action_fn(policy, device=args.device, deterministic=True)
        for seed in footage_seeds:
            print(f"rendering {tag} seed={seed}…", flush=True)
            episode = run_episode_node(
                action_fn,
                seed=seed,
                max_steps=max_steps,
                research_mode=True,
                record=True,
                output=out,
                model=f"ppo-{tag}",
                origin="rl_ppo_footage",
                revision=1,
                adapter=adapter,
            )
            verify = adapter.verify_flight_record(episode["flight_record_path"])
            assert verify["matched"], verify["mismatches"]
            video = Path(episode["video_path"])
            dest_name = f"apollolander_rl_{tag}_heldout_seed{seed}.mp4"
            dest = ARTIFACTS / dest_name
            shutil.copy2(video, dest)
            entry = {
                "checkpoint": tag,
                "seed": seed,
                "seed_chosen_before_outcomes": True,
                "reward": episode["reward"],
                "status": episode["status"],
                "landed": episode["landed"],
                "crashed": episode["crashed"],
                "timed_out": episode["timed_out"],
                "replay_matched": verify["matched"],
                "video_artifact": str(dest),
                "flight_record": episode["flight_record_path"],
            }
            manifest.append(entry)
            print(f"  status={episode['status']} reward={episode['reward']:.2f} -> {dest}", flush=True)

    man_path = out / "footage_manifest.json"
    man_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(man_path, ARTIFACTS / "apollolander_rl_footage_manifest.json")
    print(f"wrote {man_path}")


if __name__ == "__main__":
    main()
