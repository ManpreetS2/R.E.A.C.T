"""Scripted, NON-AI input sequences that exercise the blind-play pipeline end to end.

These are infrastructure checks, not players: a script never looks at the screen and never tries to
land. Each runs through the same pipe a future model tool runner would use (``player_client`` ->
``serve``), so the whole boundary is exercised. Sessions are labelled ``scripted:<name> (NOT AI)``.

    python -m rewardbench.blindplay.scripted --script idle --episodes 2 --out runs/blind-visual/<id>
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path
from typing import Any, Callable

from rewardbench.blindplay import contract
from rewardbench.blindplay.player_client import BlindPlayClient

Policy = Callable[[dict[str, Any], random.Random, int], tuple[list[str], int]]


def idle(_obs: dict[str, Any], _rng: random.Random, _step: int) -> tuple[list[str], int]:
    """No keys, maximum frames: whatever the game does on its own."""
    return [], contract.MAX_FRAMES_PER_ACT


def key_sweep(_obs: dict[str, Any], _rng: random.Random, step: int) -> tuple[list[str], int]:
    """Each allowed key alone for 20 frames, in enumeration order, then no keys for 20 frames, repeating."""
    cycle = list(contract.ALLOWED_KEYS) + [None]
    key = cycle[step % len(cycle)]
    return ([key] if key else []), 20


def seeded_random(_obs: dict[str, Any], rng: random.Random, _step: int) -> tuple[list[str], int]:
    """0-2 uniformly random keys for 1-120 frames; ignores the screen."""
    keys = rng.sample(contract.ALLOWED_KEYS, rng.randint(0, 2))
    return keys, rng.randint(1, contract.MAX_FRAMES_PER_ACT)


SCRIPTS: dict[str, Policy] = {"idle": idle, "key-sweep": key_sweep, "seeded-random": seeded_random}


def serve_command(out: Path, label: str, *, seed: int, episodes: int, frame_budget: int) -> list[str]:
    return [sys.executable, "-m", "rewardbench.blindplay.serve", "--out", str(out), "--player-label", label,
            "--player-is-ai", "false", "--seed", str(seed), "--max-episodes", str(episodes),
            "--episode-frame-budget", str(frame_budget)]


def run(script: str, out: Path, *, episodes: int, frame_budget: int, seed: int = 0, script_seed: int = 0) -> dict[str, Any]:
    policy = SCRIPTS[script]
    rng = random.Random(script_seed)
    label = f"scripted:{script} script_seed={script_seed} (NOT AI)"
    env = dict(os.environ)
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    calls = 0
    with BlindPlayClient(serve_command(out, label, seed=seed, episodes=episodes, frame_budget=frame_budget), env=env) as client:
        client.brief()
        obs = client.observe()
        while not obs.get("session_over"):
            if "error" in obs:
                raise RuntimeError(f"referee error: {obs['error']}")
            keys, frames = policy(obs, rng, calls)
            obs = client.act(keys, frames)
            calls += 1
    return {"script": script, "out": str(out), "act_calls": calls}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.blindplay.scripted", description=__doc__.split("\n\n")[0])
    parser.add_argument("--script", choices=sorted(SCRIPTS), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--episode-frame-budget", type=int, default=8000)
    parser.add_argument("--seed", type=int, default=0, help="game seed (fixed start)")
    parser.add_argument("--script-seed", type=int, default=0)
    args = parser.parse_args(argv)
    result = run(args.script, args.out, episodes=args.episodes, frame_budget=args.episode_frame_budget,
                 seed=args.seed, script_seed=args.script_seed)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
