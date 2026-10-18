"""Vectorized env wrapping the ORIGINAL upstream ApolloLander via Node vm host.

Observations come from real upstream Lander/Landscape state.
Actions map only to lander.thrust / lander.setRotation (player controls).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from rewardbench.environments.apollolander.starts import START_SCHEDULE_VERSION, derive_start
from rewardbench.rl.env import EnvConfig
from rewardbench.rl.physics_python import (
    N_ACTIONS,
    OBS_DIM,
    decode_action,
    normalize_obs,
    observation_vector,
)
from rewardbench.rl.reserved_seeds import assert_seed_allowed

ROOT = Path(__file__).resolve().parents[3]
HOST_JS = ROOT / "frontend" / "apollolander" / "rl_overnight" / "upstream_engine_host.js"


@dataclass
class UpstreamSession:
    """One Node JSON-IPC process bound to the upstream engine host."""

    proc: subprocess.Popen[str]

    @classmethod
    def start(cls) -> UpstreamSession:
        proc = subprocess.Popen(
            ["node", str(HOST_JS)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return cls(proc=proc)

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin and self.proc.stdout
        self.proc.stdin.write(json.dumps(payload) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = self.proc.stderr.read() if self.proc.stderr else ""
            raise RuntimeError(f"upstream host died: {err}")
        msg = json.loads(line)
        if not msg.get("ok"):
            raise RuntimeError(msg.get("error", "upstream ipc error"))
        return msg

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def _obs_from_raw(raw: dict[str, Any]) -> np.ndarray:
    # Host reports thrustBuild; observation_vector expects "thrust".
    mapped = dict(raw)
    if "thrust" not in mapped:
        mapped["thrust"] = float(mapped.get("thrustBuild", 0.0))
    return normalize_obs(observation_vector(mapped))


class ApolloLanderUpstreamEnv:
    """Single-instance gym-like wrapper around the upstream Node host."""

    def __init__(self, config: EnvConfig | None = None, reward_mode: str = "research_shaped") -> None:
        self.config = config or EnvConfig(
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        )
        if self.config.action_repeat < 1:
            raise ValueError("action_repeat must be >= 1")
        self.reward_mode = reward_mode
        self.session = UpstreamSession.start()
        self._episode_seed: int | None = None
        self._obs: np.ndarray | None = None

    @property
    def observation_dim(self) -> int:
        return OBS_DIM

    @property
    def n_actions(self) -> int:
        return N_ACTIONS

    def reset(self, seed: int) -> tuple[np.ndarray, dict[str, Any]]:
        assert_seed_allowed(seed, context="upstream_env.reset")
        if self.config.research_mode:
            start = derive_start(
                seed,
                version=self.config.start_schedule_version or START_SCHEDULE_VERSION,
                vary_fuel=self.config.vary_fuel,
            ).as_dict()
        else:
            start = {
                "x": 6803.2,
                "y": 150.0,
                "vx": 0.415,
                "vy": 0.0,
                "rotation": -90.0,
                "fuel": 1000.0,
                "scale": 0.25,
            }
        msg = self.session.call(
            {
                "cmd": "reset",
                "config": {
                    "maxSteps": self.config.max_steps,
                    "lockedCamera": self.config.locked_camera,
                    "bonuses": False,
                    "rewardMode": self.reward_mode,
                    "start": start,
                },
            }
        )
        self._episode_seed = seed
        self._obs = _obs_from_raw(msg["observation"])
        return self._obs.copy(), {"seed": seed, "start": start, "backend": "upstream_vm"}

    def step(self, action_index: int) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        if self._obs is None:
            raise RuntimeError("call reset() before step()")
        command = decode_action(int(action_index))
        total_reward = 0.0
        terminated = False
        truncated = False
        last: dict[str, Any] | None = None
        for _ in range(self.config.action_repeat):
            msg = self.session.call({"cmd": "step", "action": command})
            last = msg
            total_reward += float(msg["step"]["reward"])
            result = msg["result"]
            if result["done"]:
                truncated = bool(result.get("timedOut"))
                terminated = bool(result["done"]) and not truncated
                break
        assert last is not None
        obs = _obs_from_raw(last["observation"])
        self._obs = obs
        result = last["result"]
        info = {
            "status": result["status"],
            "landed": bool(result.get("landed")),
            "crashed": bool(result.get("crashed")),
            "timed_out": bool(result.get("timedOut")),
            "fuel_used": float(result.get("fuelUsed", 0.0)),
            "steps": int(result.get("steps", 0)),
            "raw_reward": float(result.get("reward", total_reward)),
            "applied": last["step"].get("applied"),
            "action_repeat": self.config.action_repeat,
            "native_outcome": result.get("nativeOutcome"),
            "backend": "upstream_vm",
        }
        return obs.copy(), float(total_reward), terminated, truncated, info

    def close(self) -> None:
        self.session.close()


class VectorApolloLanderUpstreamEnv:
    """Independent upstream hosts per env (isolated seeds, no shared RNG)."""

    def __init__(
        self,
        n_envs: int,
        config: EnvConfig | None = None,
        reward_mode: str = "research_shaped",
    ) -> None:
        if n_envs < 1:
            raise ValueError("n_envs must be >= 1")
        self.n_envs = n_envs
        self.config = config or EnvConfig(
            physics_backend="upstream_vm_host_of_frontend/apollolander/upstream",
        )
        self.envs = [ApolloLanderUpstreamEnv(self.config, reward_mode=reward_mode) for _ in range(n_envs)]

    @property
    def observation_dim(self) -> int:
        return OBS_DIM

    @property
    def n_actions(self) -> int:
        return N_ACTIONS

    def reset(self, seeds: list[int] | np.ndarray) -> tuple[np.ndarray, list[dict[str, Any]]]:
        seeds_list = [int(s) for s in seeds]
        if len(seeds_list) != self.n_envs:
            raise ValueError("seeds length must equal n_envs")
        obs = []
        infos = []
        for env, seed in zip(self.envs, seeds_list):
            o, info = env.reset(seed)
            obs.append(o)
            infos.append(info)
        return np.stack(obs, axis=0), infos

    def step(
        self, actions: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
        obs_list = []
        rewards = []
        terminated = []
        truncated = []
        infos = []
        for env, action in zip(self.envs, actions):
            o, r, term, trunc, info = env.step(int(action))
            obs_list.append(o)
            rewards.append(r)
            terminated.append(term)
            truncated.append(trunc)
            infos.append(info)
        return (
            np.stack(obs_list, axis=0),
            np.asarray(rewards, dtype=np.float64),
            np.asarray(terminated, dtype=bool),
            np.asarray(truncated, dtype=bool),
            infos,
        )

    def close(self) -> None:
        for env in self.envs:
            env.close()
