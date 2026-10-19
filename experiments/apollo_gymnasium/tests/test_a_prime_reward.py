"""Unit tests for progress_a_prime terminal and nonterminal rewards (no browser)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import A_PRIME_ALPHA, A_PRIME_TIME_COST, ApolloLanderGym, _potential


def _env(**kwargs) -> ApolloLanderGym:
    defaults = dict(
        reward_mode="progress_a_prime",
        potential_scale=10.0,
        time_cost=0.005,
        timeout_as_terminated=True,
        max_physics_frames=2000,
        start_mode="research",
        headless=True,
    )
    defaults.update(kwargs)
    return ApolloLanderGym(**defaults)


def test_a_prime_defaults_alpha_and_time_cost():
    env = ApolloLanderGym(reward_mode="progress_a_prime")
    assert env.potential_scale == A_PRIME_ALPHA == 10.0
    assert env.time_cost == A_PRIME_TIME_COST == 0.005
    assert env.timeout_as_terminated is True


def test_perfect_landing_terminal_plus_100():
    env = _env()
    obs = np.zeros(10, dtype=np.float32)
    env._prev_phi = _potential(obs)
    r = env._train_reward(
        obs,
        {"perfect": True, "landed": True, "crashed": False},
        timed_out=False,
        raw={},
    )
    assert r == 100.0


def test_hard_landing_terminal_plus_40():
    env = _env()
    obs = np.zeros(10, dtype=np.float32)
    env._prev_phi = _potential(obs)
    r = env._train_reward(
        obs,
        {"perfect": False, "landed": True, "hard_landing": True, "crashed": False},
        timed_out=False,
        raw={},
    )
    assert r == 40.0


def test_crash_terminal_minus_100():
    env = _env()
    obs = np.zeros(10, dtype=np.float32)
    env._prev_phi = _potential(obs)
    r = env._train_reward(
        obs,
        {"perfect": False, "landed": False, "crashed": True},
        timed_out=False,
        raw={},
    )
    assert r == -100.0


def test_timeout_terminal_minus_100():
    env = _env()
    obs = np.zeros(10, dtype=np.float32)
    env._prev_phi = _potential(obs)
    r = env._train_reward(
        obs,
        {"perfect": False, "landed": False, "crashed": False, "timeout": True},
        timed_out=True,
        raw={},
    )
    assert r == -100.0


def test_nonterminal_equals_alpha_delta_phi_minus_c():
    env = _env()
    prev = np.array([0.5, 1.0, 0.1, 0.2, 0.3, 0, 1, 0, 0.9, 0.5], dtype=np.float32)
    nxt = np.array([0.4, 0.9, 0.05, 0.1, 0.2, 0, 1, 0, 0.9, 0.4], dtype=np.float32)
    env._prev_phi = _potential(prev)
    expected = 10.0 * (_potential(nxt) - _potential(prev)) - 0.005
    r = env._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={"rotation": 0.0, "vx": 0.0, "vy": 0.0},
    )
    assert r == pytest.approx(expected, rel=0, abs=1e-6)


def test_timeout_flags_terminated_not_truncated():
    """Experimental frame budget is a terminal failure for A′ (documented design)."""
    env = _env(max_physics_frames=10)
    env._physics_frames = 10
    env._prev_phi = 0.0
    last = {
        "observation": {
            "dx": 0,
            "altitude": 100,
            "vx": 0,
            "vy": 0,
            "rotation": 0,
            "fuel": 1000,
            "thrust": 0,
            "pad_width": 179,
            "dy": 100,
            "native_score": 0,
        },
        "result": {
            "done": False,
            "landed": False,
            "crashed": False,
            "perfect": False,
            "status": "flying",
            "native_score": 0,
            "fuelRemaining": 1000,
        },
    }
    _obs, reward, terminated, truncated, info = env._finish_step(last)
    assert terminated is True
    assert truncated is False
    assert info["status"] == "timeout"
    assert info["timeout"] is True
    assert reward == -100.0
    assert info["landed"] is False
    assert info["crashed"] is False


def test_native_land_not_relabeled_as_timeout():
    env = _env(max_physics_frames=10)
    env._physics_frames = 10  # at budget, but native already landed
    env._prev_phi = 0.0
    last = {
        "observation": {
            "dx": 0,
            "altitude": 0,
            "vx": 0,
            "vy": 0.01,
            "rotation": 0,
            "fuel": 900,
            "thrust": 0,
            "pad_width": 179,
            "dy": 0,
            "native_score": 50,
        },
        "result": {
            "done": True,
            "landed": True,
            "crashed": False,
            "perfect": True,
            "status": "landed",
            "native_score": 50,
            "fuelRemaining": 900,
        },
    }
    _obs, reward, terminated, truncated, info = env._finish_step(last)
    assert terminated is True
    assert truncated is False
    assert info["status"] == "landed"
    assert info.get("timeout") in (False, None)
    assert reward == 100.0
