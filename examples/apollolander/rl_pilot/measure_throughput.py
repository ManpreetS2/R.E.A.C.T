#!/usr/bin/env python3
"""Measure env steps/sec for Python port and Node IPC (random actions)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from rewardbench.environments.apollolander.starts import derive_start
from rewardbench.rl.env import EnvConfig, VectorApolloLanderEnv
from rewardbench.rl.physics_python import ApolloPhysicsPython, decode_action

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "results" / "throughput.json"


def measure_python(n_steps: int = 50_000, n_envs: int = 16, action_repeat: int = 4) -> dict:
    cfg = EnvConfig(max_steps=8000, action_repeat=action_repeat)
    env = VectorApolloLanderEnv(n_envs, cfg)
    seeds = np.arange(n_envs, dtype=np.int64)
    obs, _ = env.reset(seeds)
    actions = np.zeros(n_envs, dtype=np.int64)
    physics_steps = 0
    t0 = time.perf_counter()
    while physics_steps < n_steps:
        actions = (actions + 17) % 95
        obs, rewards, term, trunc, infos = env.step(actions)
        physics_steps += n_envs * action_repeat
        dones = np.logical_or(term, trunc)
        if np.any(dones):
            for i, done in enumerate(dones):
                if done:
                    o, _ = env.envs[i].reset(int(1000 + physics_steps + i))
                    obs[i] = o
    elapsed = time.perf_counter() - t0
    return {
        "backend": "python_port_vectorized",
        "n_envs": n_envs,
        "action_repeat": action_repeat,
        "physics_steps": physics_steps,
        "wall_seconds": elapsed,
        "steps_per_sec": physics_steps / elapsed,
    }


def measure_python_single(n_steps: int = 20_000) -> dict:
    sim = ApolloPhysicsPython()
    start = derive_start(0).as_dict()
    sim.reset({"maxSteps": 8000, "lockedCamera": True, "bonuses": False, "start": start})
    t0 = time.perf_counter()
    steps = 0
    while steps < n_steps:
        action = decode_action(steps % 95)
        stepped = sim.step(action)
        steps += 1
        if stepped["done"]:
            start = derive_start((steps % 1000)).as_dict()
            sim.reset({"maxSteps": 8000, "lockedCamera": True, "bonuses": False, "start": start})
    elapsed = time.perf_counter() - t0
    return {
        "backend": "python_port_single",
        "physics_steps": steps,
        "wall_seconds": elapsed,
        "steps_per_sec": steps / elapsed,
    }


def measure_node_ipc(n_steps: int = 10_000) -> dict:
    import subprocess

    session = ROOT / "frontend" / "apollolander" / "experiment" / "session.js"
    proc = subprocess.Popen(
        ["node", str(session)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(ROOT),
    )

    def req(msg: dict) -> dict:
        proc.stdin.write(json.dumps(msg) + "\n")
        proc.stdin.flush()
        return json.loads(proc.stdout.readline())

    start = derive_start(0).as_dict()
    req({"cmd": "reset", "config": {"maxSteps": 8000, "lockedCamera": True, "bonuses": False, "start": start}})
    t0 = time.perf_counter()
    steps = 0
    while steps < n_steps:
        action = decode_action(steps % 95)
        r = req({"cmd": "step", "action": action})
        steps += 1
        if r["result"]["done"]:
            start = derive_start(steps % 1000).as_dict()
            req({"cmd": "reset", "config": {"maxSteps": 8000, "lockedCamera": True, "bonuses": False, "start": start}})
    elapsed = time.perf_counter() - t0
    proc.terminate()
    return {
        "backend": "node_json_ipc_single",
        "physics_steps": steps,
        "wall_seconds": elapsed,
        "steps_per_sec": steps / elapsed,
    }


def main() -> None:
    results = {
        "python_single": measure_python_single(),
        "python_vectorized": measure_python(),
        "node_ipc": measure_node_ipc(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    for name, row in results.items():
        print(f"{name}: {row['steps_per_sec']:.1f} steps/sec ({row['physics_steps']} steps)")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
