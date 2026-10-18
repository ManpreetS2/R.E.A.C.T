"""Evaluate a neural policy on the ORIGINAL Node ApolloLander adapter path.

Does not change physics, scoring, or starts. Builds flight records compatible
with ``ApolloLanderAdapter.verify_flight_record``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import torch

from rewardbench.environments.apollolander.adapter import SESSION, ApolloLanderAdapter, _Session, _frame, _slug
from rewardbench.environments.apollolander.flight_record import (
    ENVIRONMENT_VERSION,
    build_flight_record,
    write_flight_record,
)
from rewardbench.environments.apollolander.recording import write_flight_video
from rewardbench.environments.apollolander.starts import standard_start
from rewardbench.environments.lunarlander.seeds import validate_seed_split
from rewardbench.rl.env import EnvConfig
from rewardbench.rl.physics_python import (
    N_ACTIONS,
    decode_action,
    normalize_obs,
    observation_vector,
)
from rewardbench.rl.policy import ActorCritic
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed

PolicyFn = Callable[[dict[str, Any]], dict[str, float | int]]


def load_policy(checkpoint: Path | str, device: str = "cpu") -> tuple[ActorCritic, dict[str, Any]]:
    payload = torch.load(checkpoint, map_location=device, weights_only=False)
    env_cfg = payload.get("env_config") or {}
    hidden = int((payload.get("ppo_config") or {}).get("hidden", 128))
    policy = ActorCritic(hidden=hidden).to(device)
    policy.load_state_dict(payload["policy_state_dict"])
    policy.eval()
    return policy, payload


def policy_action_fn(policy: ActorCritic, device: str = "cpu", *, deterministic: bool = True) -> PolicyFn:
    def _act(observation: dict[str, Any]) -> dict[str, float | int]:
        obs = normalize_obs(observation_vector(observation))
        tensor = torch.as_tensor(obs, dtype=torch.float32, device=device).unsqueeze(0)
        with torch.no_grad():
            dist, _ = policy.forward(tensor)
            if deterministic:
                index = int(torch.argmax(dist.probs, dim=-1).item())
            else:
                index = int(dist.sample().item())
        return decode_action(index)

    return _act


def random_network_action_fn(seed: int = 0, device: str = "cpu") -> tuple[PolicyFn, ActorCritic]:
    """Fresh randomly initialized network (untrained baseline)."""
    torch.manual_seed(seed)
    policy = ActorCritic().to(device)
    policy.eval()
    return policy_action_fn(policy, device=device, deterministic=True), policy


def run_episode_node(
    action_fn: PolicyFn,
    *,
    seed: int,
    max_steps: int,
    research_mode: bool = True,
    start_schedule_version: str = "apollolander.starts.v1",
    vary_fuel: bool = False,
    record: bool = False,
    output: Path | None = None,
    model: str = "rl-policy",
    origin: str = "autonomous_learning_rl",
    revision: int | None = 1,
    episode_index: int | None = None,
    adapter: ApolloLanderAdapter | None = None,
) -> dict[str, Any]:
    """One episode on the custom Node ApolloLander simulator session."""
    assert_seed_allowed(seed, context="node_eval.run_episode")
    if adapter is None:
        adapter = ApolloLanderAdapter(
            max_steps=max_steps,
            research_mode=research_mode,
            start_schedule_version=start_schedule_version,
            vary_fuel=vary_fuel,
        )
    resolved = adapter._resolve_start(seed=seed, start=None)
    applied_start = resolved if resolved is not None else standard_start().as_dict()
    session = _Session(SESSION)
    try:
        opened = session.request(
            {
                "cmd": "reset",
                "config": {
                    "maxSteps": max_steps,
                    "lockedCamera": True,
                    "bonuses": False,
                    **({} if resolved is None else {"start": dict(resolved)}),
                },
            }
        )
        terrain = opened["map"]["points"]
        zone = opened["map"]["zone"]
        frames: list[dict] = []
        trace: list[dict[str, float | int]] = []
        fuel_penalty = 0.0
        terminal = 0.0
        observation = opened["observation"]
        result = None
        if record:
            frames.append(_frame(session, observation, session.request({"cmd": "result"})["result"]))
        for _ in range(max_steps):
            action = action_fn(observation)
            trace.append({"thrust": float(action["thrust"]), "rotation": int(action["rotation"])})
            stepped = session.request({"cmd": "step", "action": action})
            if not stepped.get("ok", False):
                raise RuntimeError(stepped.get("error", "physics step failed"))
            fuel_penalty += float(stepped["step"]["breakdown"]["fuelPenalty"])
            terminal += float(stepped["step"]["breakdown"]["terminal"])
            observation = stepped["observation"]
            result = stepped["result"]
            if record:
                frames.append(_frame(session, observation, result))
            if result["done"]:
                break
        if result is None:
            raise RuntimeError("episode produced no physics result")
    finally:
        session.close()

    video_path = None
    flight_record_path = None
    controller = {
        "schema": "rewardbench.apollolander.rl_policy.v1",
        "policy": "neural_ppo",
        "note": "state-observation RL pilot, not visual learning",
        "n_actions": N_ACTIONS,
    }
    episode_tag = f"ep-{episode_index}" if episode_index is not None else "ep"
    stem = f"apollo-{_slug(model)}-revision-{revision}-{episode_tag}-seed-{seed}"
    if record and output is not None:
        video_file = output / f"{stem}.mp4"
        write_flight_video(
            video_file,
            terrain,
            frames,
            hud={
                "model": model,
                "revision": "-" if revision is None else str(revision),
                "origin": origin,
                "seed": str(seed),
                "mode": "RESEARCH" if research_mode else "FIXED MAP",
            },
        )
        video_path = str(video_file)

    flight = build_flight_record(
        environment_id=adapter.environment_id,
        environment_version=ENVIRONMENT_VERSION,
        research_mode=research_mode,
        start_schedule_version=start_schedule_version if research_mode else None,
        vary_fuel=vary_fuel,
        seed=seed,
        start=applied_start,
        controller=controller,
        revision=revision,
        origin=origin,
        model=model,
        split=None,
        max_steps=max_steps,
        result=result,
        zone=zone,
        trace=trace,
        fuel_penalty=fuel_penalty,
        terminal_reward=terminal,
        video_path=video_path,
        experiment_id=None,
        episode_index=episode_index,
    )
    if output is not None:
        output.mkdir(parents=True, exist_ok=True)
        record_file = output / f"{stem}.flight.json"
        write_flight_record(record_file, flight)
        flight_record_path = str(record_file)
        flight = {**flight, "flight_record_path": flight_record_path}

    return {
        "seed": seed,
        "executed": True,
        "reward": result["reward"],
        "status": result["status"],
        "landed": result["landed"],
        "crashed": result["crashed"],
        "in_landing_zone": result["inLandingZone"],
        "timed_out": result["timedOut"],
        "steps": result["steps"],
        "fuel_used": result["fuelUsed"],
        "fuel_remaining": result["fuelRemaining"],
        "video_path": video_path,
        "flight_record_path": flight_record_path,
        "flight_record": flight,
        "trace": trace,
        "trace_hash": flight["trace_hash"],
        "origin": origin,
        "model": model,
        "start": applied_start,
    }


def summarize_episodes(episodes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    n = len(episodes)
    if n == 0:
        raise ValueError("no episodes")
    rewards = [float(e["reward"]) for e in episodes]
    fuels = [float(e["fuel_used"]) for e in episodes]
    land = sum(1 for e in episodes if e["landed"])
    crash = sum(1 for e in episodes if e["crashed"])
    timeout = sum(1 for e in episodes if e["timed_out"])
    mean_r = sum(rewards) / n
    # Wald 95% CI for proportions; t-approx for mean reward.
    z = 1.96
    def prop_ci(k: int) -> tuple[float, float]:
        p = k / n
        se = math.sqrt(p * (1 - p) / n) if n else 0.0
        return max(0.0, p - z * se), min(1.0, p + z * se)

    reward_se = (np.std(rewards, ddof=1) / math.sqrt(n)) if n > 1 else 0.0
    return {
        "n": n,
        "mean_reward": mean_r,
        "mean_reward_ci95": [mean_r - z * reward_se, mean_r + z * reward_se],
        "landing_rate": land / n,
        "landing_rate_ci95": list(prop_ci(land)),
        "crash_rate": crash / n,
        "crash_rate_ci95": list(prop_ci(crash)),
        "timeout_rate": timeout / n,
        "timeout_rate_ci95": list(prop_ci(timeout)),
        "mean_fuel_used": sum(fuels) / n,
        "landings": land,
        "crashes": crash,
        "timeouts": timeout,
    }


def evaluate_policy_node(
    action_fn: PolicyFn,
    seeds: Sequence[int],
    *,
    split: str,
    max_steps: int,
    env_config: EnvConfig | None = None,
    record_dir: Path | str | None = None,
    record_video: bool = False,
    video_seeds: Sequence[int] | None = None,
    model: str = "rl-policy",
    origin: str = "autonomous_learning_rl",
    revision: int = 1,
) -> dict[str, Any]:
    validate_seed_split(seeds, split)
    assert_seeds_allowed(seeds, context=f"node_eval.{split}")
    cfg = env_config or EnvConfig(max_steps=max_steps)
    adapter = ApolloLanderAdapter(
        max_steps=cfg.max_steps,
        research_mode=cfg.research_mode,
        start_schedule_version=cfg.start_schedule_version,
        vary_fuel=cfg.vary_fuel,
        record_dir=record_dir,
        record_video=record_video,
    )
    output = Path(record_dir) if record_dir is not None else None
    selected = set(seeds if video_seeds is None else video_seeds) if record_video else set()
    episodes = []
    for i, seed in enumerate(seeds):
        episode = run_episode_node(
            action_fn,
            seed=int(seed),
            max_steps=cfg.max_steps,
            research_mode=cfg.research_mode,
            start_schedule_version=cfg.start_schedule_version,
            vary_fuel=cfg.vary_fuel,
            record=int(seed) in selected,
            output=output,
            model=model,
            origin=origin,
            revision=revision,
            episode_index=i,
            adapter=adapter,
        )
        if episode.get("flight_record_path"):
            verify = adapter.verify_flight_record(episode["flight_record_path"])
            episode["replay_matched"] = verify["matched"]
            episode["replay_mismatches"] = verify["mismatches"]
        episodes.append(episode)
    summary = summarize_episodes(episodes)
    return {
        "model": model,
        "origin": origin,
        "split": split,
        "observation_kind": cfg.observation_kind,
        "env_config": cfg.to_dict(),
        "env_config_hash": cfg.config_hash(),
        "physics_backend": (
            "custom Node ApolloLander simulator via ApolloLanderAdapter "
            "(frontend/apollolander/experiment/physics.js)"
        ),
        "observation_disclosure": (
            "numerical state observations with shaped rewards "
            "(progress/potential term + fuel penalty); NOT screenshots"
        ),
        "eval_policy_mode": "frozen (caller-supplied action_fn; no weight updates here)",
        "summary": summary,
        "episodes": episodes,
    }
