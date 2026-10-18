"""Vectorized ApolloLander training environments (Python physics port).

Observation kind: state-observation RL pilot, not visual learning.
Every underlying step is the unmodified physics step from physics.js.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from rewardbench.environments.apollolander.starts import START_SCHEDULE_VERSION, derive_start
from rewardbench.rl.physics_python import (
    N_ACTIONS,
    OBS_DIM,
    OBS_LABELS,
    ApolloPhysicsPython,
    decode_action,
    load_landscape,
    normalize_obs,
    observation_vector,
)
from rewardbench.rl.reserved_seeds import assert_seed_allowed, assert_seeds_allowed

OBSERVATION_KIND = "state-observation RL pilot, not visual learning"


@dataclass(frozen=True)
class EnvConfig:
    """Fixed environment configuration frozen before the first training step."""

    max_steps: int = 8000
    research_mode: bool = True
    start_schedule_version: str = START_SCHEDULE_VERSION
    vary_fuel: bool = False
    action_repeat: int = 1  # each policy action is applied this many physics steps
    bonuses: bool = False
    locked_camera: bool = True
    observation_kind: str = OBSERVATION_KIND
    action_space: str = "Discrete(95)=5 thrust bins x 19 rotation bins (-90..90/10)"
    physics_backend: str = "python_port_of_frontend/apollolander/experiment/physics.js"
    landscape_source: str = "examples/apollolander/rl_pilot/landscape_map.json"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def config_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ApolloLanderPythonEnv:
    """Single-instance gym-like wrapper around the Python physics port."""

    def __init__(self, config: EnvConfig | None = None, landscape: dict[str, Any] | None = None) -> None:
        self.config = config or EnvConfig()
        if self.config.action_repeat < 1:
            raise ValueError("action_repeat must be >= 1")
        if self.config.bonuses:
            raise ValueError("bonuses must stay false")
        self.landscape = landscape if landscape is not None else load_landscape()
        self.sim = ApolloPhysicsPython(self.landscape)
        self._episode_seed: int | None = None
        self._obs: np.ndarray | None = None

    @property
    def observation_dim(self) -> int:
        return OBS_DIM

    @property
    def n_actions(self) -> int:
        return N_ACTIONS

    def reset(self, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
        if isinstance(seed, bool) or not isinstance(seed, int) or seed < 0:
            raise ValueError("episode seed must be a non-negative integer")
        assert_seed_allowed(seed, context="env.reset")
        if self.config.research_mode:
            start = derive_start(
                seed,
                version=self.config.start_schedule_version,
                vary_fuel=self.config.vary_fuel,
            ).as_dict()
        else:
            start = self.sim.standard_start()
        obs = self.sim.reset(
            {
                "maxSteps": self.config.max_steps,
                "lockedCamera": self.config.locked_camera,
                "bonuses": False,
                "start": start,
            }
        )
        self._episode_seed = seed
        self._obs = normalize_obs(observation_vector(obs))
        info = {
            "seed": seed,
            "start": start,
            "observation_kind": self.config.observation_kind,
            "obs_labels": list(OBS_LABELS),
        }
        return self._obs.copy(), info

    def step(self, action_index: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._obs is None:
            raise RuntimeError("call reset() before step()")
        command = decode_action(int(action_index))
        total_reward = 0.0
        terminated = False
        truncated = False
        last_step: dict[str, Any] | None = None
        for _ in range(self.config.action_repeat):
            last_step = self.sim.step(command)
            total_reward += float(last_step["reward"])
            result = self.sim.get_result()
            if result["done"]:
                # Include landed_outside_zone (done but neither landed nor crashed).
                truncated = bool(result["timedOut"])
                terminated = bool(result["done"]) and not truncated
                break
        assert last_step is not None
        obs = normalize_obs(observation_vector(self.sim.observe()))
        self._obs = obs
        result = self.sim.get_result()
        if result["done"] and not (terminated or truncated):
            truncated = bool(result["timedOut"])
            terminated = bool(result["done"]) and not truncated
        info = {
            "status": result["status"],
            "landed": bool(result["landed"]),
            "crashed": bool(result["crashed"]),
            "timed_out": bool(result["timedOut"]),
            "fuel_used": float(result["fuelUsed"]),
            "steps": int(result["steps"]),
            "raw_reward": float(result["reward"]),
            "applied": last_step.get("applied"),
            "action_repeat": self.config.action_repeat,
        }
        return obs.copy(), float(total_reward), terminated, truncated, info


class VectorApolloLanderEnv:
    """Simple sequential vectorization over independent Python sims."""

    def __init__(self, n_envs: int, config: EnvConfig | None = None) -> None:
        if n_envs < 1:
            raise ValueError("n_envs must be >= 1")
        landscape = load_landscape()
        self.config = config or EnvConfig()
        self.n_envs = n_envs
        self.envs = [ApolloLanderPythonEnv(self.config, landscape=landscape) for _ in range(n_envs)]
        self._seeds = np.zeros(n_envs, dtype=np.int64)

    @property
    def observation_dim(self) -> int:
        return OBS_DIM

    @property
    def n_actions(self) -> int:
        return N_ACTIONS

    def reset(self, seeds: np.ndarray) -> tuple[np.ndarray, list[dict[str, Any]]]:
        seeds = np.asarray(seeds, dtype=np.int64)
        if seeds.shape != (self.n_envs,):
            raise ValueError(f"expected {self.n_envs} seeds, got shape {seeds.shape}")
        assert_seeds_allowed(seeds.tolist(), context="vector_env.reset")
        obs = np.zeros((self.n_envs, OBS_DIM), dtype=np.float32)
        infos: list[dict[str, Any]] = []
        for i, env in enumerate(self.envs):
            o, info = env.reset(int(seeds[i]))
            obs[i] = o
            infos.append(info)
            self._seeds[i] = seeds[i]
        return obs, infos

    def step(
        self, actions: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
        actions = np.asarray(actions, dtype=np.int64)
        if actions.shape != (self.n_envs,):
            raise ValueError(f"expected {self.n_envs} actions")
        obs = np.zeros((self.n_envs, OBS_DIM), dtype=np.float32)
        rewards = np.zeros(self.n_envs, dtype=np.float64)
        terminated = np.zeros(self.n_envs, dtype=bool)
        truncated = np.zeros(self.n_envs, dtype=bool)
        infos: list[dict[str, Any]] = []
        for i, env in enumerate(self.envs):
            o, r, term, trunc, info = env.step(int(actions[i]))
            obs[i] = o
            rewards[i] = r
            terminated[i] = term
            truncated[i] = trunc
            infos.append(info)
        return obs, rewards, terminated, truncated, infos
