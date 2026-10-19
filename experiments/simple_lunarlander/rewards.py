"""Reward-shaping wrappers for Phase 4 (Hari tutorial).

Do not use these until the native PPO baseline is working.
All wrappers keep physics and the Discrete(4) action space unchanged.
Evaluation must use the unwrapped native reward (no shaping).
"""

from __future__ import annotations

from typing import SupportsFloat

import gymnasium as gym
import numpy as np
from gymnasium import spaces


class ProblematicHoverReward(gym.Wrapper):
    """Deliberately bad shaping: +1 every frame while upright and slow.

    As in the Hari guide: an agent can farm points by hovering until the
    1000-step cutoff instead of landing.
    """

    def __init__(self, env: gym.Env, upright_thresh: float = 0.2, speed_thresh: float = 0.5):
        super().__init__(env)
        self.upright_thresh = upright_thresh
        self.speed_thresh = speed_thresh

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        angle = float(obs[4])
        speed = float(np.sqrt(obs[2] ** 2 + obs[3] ** 2))
        bonus = 0.0
        if abs(angle) < self.upright_thresh and speed < self.speed_thresh:
            bonus = 1.0
        shaped = float(reward) + bonus
        info = dict(info)
        info["native_reward"] = float(reward)
        info["shaping_bonus"] = bonus
        return obs, shaped, terminated, truncated, info


class CorrectedProgressReward(gym.Wrapper):
    """Pay for improvement in a potential, plus a small per-frame time cost.

    Potential mirrors the guide's "how good is this position" idea:
    closer, slower, more upright, legs down — reward the *delta*, not the level.
    """

    def __init__(self, env: gym.Env, time_cost: float = 0.05):
        super().__init__(env)
        assert isinstance(env.observation_space, spaces.Box)
        self.time_cost = time_cost
        self._prev_potential: float | None = None

    def _potential(self, obs: np.ndarray) -> float:
        # Similar structure to Gymnasium's built-in shaping terms (scaled down).
        dist = float(np.sqrt(obs[0] ** 2 + obs[1] ** 2))
        speed = float(np.sqrt(obs[2] ** 2 + obs[3] ** 2))
        angle = abs(float(obs[4]))
        legs = float(obs[6]) + float(obs[7])
        return -100.0 * dist - 100.0 * speed - 100.0 * angle + 10.0 * legs

    def reset(self, **kwargs):
        obs, info = self.env.reset(**kwargs)
        self._prev_potential = self._potential(obs)
        return obs, info

    def step(self, action):
        obs, reward, terminated, truncated, info = self.env.step(action)
        pot = self._potential(obs)
        delta = 0.0 if self._prev_potential is None else (pot - self._prev_potential)
        self._prev_potential = pot
        shaped = float(reward) + float(delta) - self.time_cost
        # On terminal, keep native terminal signal dominant (already in reward).
        info = dict(info)
        info["native_reward"] = float(reward)
        info["potential_delta"] = float(delta)
        info["time_cost"] = self.time_cost
        return obs, shaped, terminated, truncated, info


def wrap_reward(env: gym.Env, mode: str) -> gym.Env:
    """mode: native | hover_bad | progress_good"""
    if mode in ("native", "A", "baseline"):
        return env
    if mode in ("hover_bad", "B", "problematic"):
        return ProblematicHoverReward(env)
    if mode in ("progress_good", "C", "corrected"):
        return CorrectedProgressReward(env)
    raise ValueError(f"unknown reward mode: {mode}")
