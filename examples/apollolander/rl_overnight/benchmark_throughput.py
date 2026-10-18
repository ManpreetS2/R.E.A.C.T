#!/usr/bin/env python3
"""Phase 3 throughput benchmarks + serial/parallel bit-identity check."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "examples/apollolander/rl_overnight/results/throughput_benchmark.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def measure_python(n_envs: int, action_repeat: int, physics_target: int) -> dict:
    from rewardbench.rl.env import EnvConfig, VectorApolloLanderEnv

    cfg = EnvConfig(action_repeat=action_repeat, max_steps=8000)
    env = VectorApolloLanderEnv(n_envs, cfg)
    seeds = list(range(50000, 50000 + n_envs))
    obs, _ = env.reset(seeds)
    steps = 0
    episodes = 0
    t0 = time.perf_counter()
    while steps < physics_target:
        actions = np.random.randint(0, env.n_actions, size=n_envs)
        obs, _, term, trunc, infos = env.step(actions)
        steps += action_repeat * n_envs
        dones = np.logical_or(term, trunc)
        if np.any(dones):
            episodes += int(np.sum(dones))
            for i, d in enumerate(dones):
                if d:
                    obs[i], _ = env.envs[i].reset(50000 + i + episodes)
    wall = time.perf_counter() - t0
    return {
        "backend": "python_port_custom_sim",
        "n_envs": n_envs,
        "action_repeat": action_repeat,
        "physics_frames": steps,
        "episodes": episodes,
        "wall_seconds": wall,
        "physics_frames_per_sec": steps / wall,
        "decisions_per_sec": (steps / action_repeat) / wall,
    }


def measure_upstream(n_envs: int, action_repeat: int, physics_target: int) -> dict:
    from rewardbench.rl.env import EnvConfig
    from rewardbench.rl.upstream_env import VectorApolloLanderUpstreamEnv

    cfg = EnvConfig(
        action_repeat=action_repeat,
        max_steps=8000,
        physics_backend="upstream_vm_host",
    )
    env = VectorApolloLanderUpstreamEnv(n_envs, cfg)
    try:
        seeds = list(range(51000, 51000 + n_envs))
        obs, _ = env.reset(seeds)
        steps = 0
        episodes = 0
        t0 = time.perf_counter()
        while steps < physics_target:
            actions = np.random.randint(0, env.n_actions, size=n_envs)
            obs, _, term, trunc, infos = env.step(actions)
            steps += action_repeat * n_envs
            dones = np.logical_or(term, trunc)
            if np.any(dones):
                episodes += int(np.sum(dones))
                for i, d in enumerate(dones):
                    if d:
                        obs[i], _ = env.envs[i].reset(51000 + i + episodes)
        wall = time.perf_counter() - t0
        return {
            "backend": "upstream_vm_host",
            "n_envs": n_envs,
            "action_repeat": action_repeat,
            "physics_frames": steps,
            "episodes": episodes,
            "wall_seconds": wall,
            "physics and_frames_per_sec": steps / wall,
            "physics_frames_per_sec": steps / wall,
            "decisions_per_sec": (steps / action_repeat) / wall,
        }
    finally:
        env.close()


def bit_identical_parallel_vs_serial() -> dict:
    """Same seeds + actions: parallel vectorized must match serial step-by-step."""
    from rewardbench.rl.env import EnvConfig, ApolloLanderPythonEnv, VectorApolloLanderEnv

    cfg = EnvConfig(action_repeat=2, max_steps=500)
    seeds = [70001, 70002, 70003, 70004]
    actions_seq = np.random.default_rng(0).integers(0, 95, size=(80, 4))

    # Serial
    serial_obs = []
    envs = [ApolloLanderPythonEnv(cfg) for _ in seeds]
    for e, s in zip(envs, seeds):
        e.reset(s)
    for t in range(actions_seq.shape[0]):
        row = []
        for i, e in enumerate(envs):
            o, _, term, trunc, _ = e.step(int(actions_seq[t, i]))
            if term or trunc:
                o, _ = e.reset(seeds[i] + 1000 + t)
            row.append(o.copy())
        serial_obs.append(np.stack(row))

    # Parallel
    vec = VectorApolloLanderEnv(4, cfg)
    obs, _ = vec.reset(seeds)
    parallel_obs = []
    for t in range(actions_seq.shape[0]):
        obs, _, term, trunc, _ = vec.step(actions_seq[t])
        dones = np.logical_or(term, trunc)
        if np.any(dones):
            for i, d in enumerate(dones):
                if d:
                    obs[i], _ = vec.envs[i].reset(seeds[i] + 1000 + t)
        parallel_obs.append(obs.copy())

    max_diff = 0.0
    for a, b in zip(serial_obs, parallel_obs):
        max_diff = max(max_diff, float(np.max(np.abs(a - b))))
    return {"max_abs_diff": max_diff, "bit_identical": max_diff == 0.0, "steps": len(serial_obs)}


def main() -> None:
    proc = psutil.Process(os.getpid())
    cpu_count = os.cpu_count() or 1
    mem = psutil.virtual_memory()
    results: dict = {
        "cpu_count": cpu_count,
        "mem_total_gb": mem.total / (1024**3),
        "torch_threads_recommendation": 1,
        "max_simultaneous_trainers": min(3, cpu_count),
        "runs": [],
    }
    print("bit-identity check...", flush=True)
    results["parallel_vs_serial"] = bit_identical_parallel_vs_serial()
    print(results["parallel_vs_serial"], flush=True)

    for n_envs, ar, target in [
        (1, 2, 20000),
        (4, 2, 40000),
        (8, 2, 40000),
        (16, 2, 50000),
    ]:
        print(f"python n_envs={n_envs}...", flush=True)
        row = measure_python(n_envs, ar, target)
        row["rss_mb"] = proc.memory_info().rss / (1024**2)
        results["runs"].append(row)
        print(row, flush=True)

    for n_envs, ar, target in [
        (1, 2, 4000),
        (2, 2, 4000),
        (4, 2, 8000),
    ]:
        print(f"upstream n_envs={n_envs}...", flush=True)
        try:
            row = measure_upstream(n_envs, ar, target)
            row["rss_mb"] = proc.memory_info().rss / (1024**2)
            results["runs"].append(row)
            print(row, flush=True)
        except Exception as exc:  # noqa: BLE001
            results["runs"].append({"backend": "upstream_vm_host", "n_envs": n_envs, "error": str(exc)})
            print("error", exc, flush=True)

    OUT.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
