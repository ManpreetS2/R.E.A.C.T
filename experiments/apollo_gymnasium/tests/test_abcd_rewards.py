"""Unit tests for frozen A/B/C/D reward modes (no browser required for reward math)."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import (
    A_PRIME_ALPHA,
    A_PRIME_TIME_COST,
    PPO_GAMMA,
    ApolloLanderGym,
    _potential,
    _potential_c,
)
from env.seeds import (
    ABCD_AUDIT_SEEDS,
    ABCD_DEV_SEEDS,
    ABCD_HELD_OUT_SEEDS,
    ABCD_REWARD_MODE,
    ABCD_TRAIN_BASES,
    abcd_train_auto_seed_base,
)


def _env(mode: str, **kwargs) -> ApolloLanderGym:
    defaults = dict(
        reward_mode=mode,
        potential_scale=10.0,
        time_cost=0.005,
        timeout_as_terminated=True,
        commitment_shaping=False,
        max_physics_frames=2000,
        start_mode="research",
        headless=True,
    )
    defaults.update(kwargs)
    return ApolloLanderGym(**defaults)


@pytest.mark.parametrize("mode", ["abcd_a", "abcd_b", "abcd_c", "abcd_d"])
def test_abcd_obs_10d_no_commitment(mode):
    env = _env(mode)
    assert env.observation_space.shape == (10,)
    assert env.commitment_shaping is False
    assert env.timeout_as_terminated is True


@pytest.mark.parametrize("mode", ["abcd_a", "abcd_b", "abcd_c", "abcd_d"])
@pytest.mark.parametrize(
    "result,timed_out,expect",
    [
        ({"perfect": True, "landed": True, "crashed": False}, False, 100.0),
        ({"perfect": False, "landed": True, "crashed": False}, False, 40.0),
        ({"perfect": False, "landed": False, "crashed": True}, False, -100.0),
        ({"perfect": False, "landed": False, "crashed": False}, True, -100.0),
    ],
)
def test_shared_native_terminals(mode, result, timed_out, expect):
    env = _env(mode)
    obs = np.zeros(10, dtype=np.float32)
    env._prev_phi = 0.0
    r = env._train_reward(obs, result, timed_out=timed_out, raw={})
    assert r == expect


def test_abcd_d_intermediate_zero():
    env = _env("abcd_d")
    obs = np.zeros(10, dtype=np.float32)
    r = env._train_reward(
        obs,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={"rotation": 0.0, "vx": 0.0, "vy": 0.0},
    )
    assert r == 0.0


def test_abcd_a_matches_alpha_delta_minus_c():
    env = _env("abcd_a")
    prev = np.array([0.5, 1.0, 0.1, 0.2, 0.3, 0, 1, 0, 0.9, 0.5], dtype=np.float32)
    nxt = np.array([0.4, 0.9, 0.05, 0.1, 0.2, 0, 1, 0, 0.9, 0.4], dtype=np.float32)
    env._prev_phi = _potential(prev)
    expected = A_PRIME_ALPHA * (_potential(nxt) - _potential(prev)) - A_PRIME_TIME_COST
    r = env._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={"rotation": 20.0, "vx": 1.0, "vy": 1.0},
    )
    assert r == pytest.approx(expected, abs=1e-6)


def test_abcd_b_adds_hover_bonus():
    env = _env("abcd_b")
    prev = np.zeros(10, dtype=np.float32)
    nxt = np.zeros(10, dtype=np.float32)
    env._prev_phi = _potential(prev)
    base = A_PRIME_ALPHA * (_potential(nxt) - _potential(prev)) - A_PRIME_TIME_COST
    r_hover = env._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={"rotation": 0.0, "vx": 0.0, "vy": 0.0},
    )
    env._prev_phi = _potential(prev)
    r_fast = env._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={"rotation": 0.0, "vx": 1.0, "vy": 1.0},
    )
    assert r_hover == pytest.approx(base + 1.0, abs=1e-6)
    assert r_fast == pytest.approx(base, abs=1e-6)


def test_abcd_c_gamma_corrected_and_distinct_phi():
    env = _env("abcd_c")
    prev = np.array([0.5, 1.0, 0.1, 0.4, 0.3, 0, 1, 0, 0.9, 0.5], dtype=np.float32)
    nxt = np.array([0.4, 0.9, 0.05, 0.05, 0.1, 0, 1, 0, 0.9, 0.4], dtype=np.float32)
    # Soft vy_n=0.05 < 0.075 → excess 0; A′ would still charge relu(vy)
    assert _potential(prev) != pytest.approx(_potential_c(prev), abs=1e-9)
    env._prev_phi = _potential_c(prev)
    expected = A_PRIME_ALPHA * (PPO_GAMMA * _potential_c(nxt) - _potential_c(prev)) - A_PRIME_TIME_COST
    r = env._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={},
    )
    assert r == pytest.approx(expected, abs=1e-6)
    # Not equal to A on same obs transition
    env_a = _env("abcd_a")
    env_a._prev_phi = _potential(prev)
    r_a = env_a._train_reward(
        nxt,
        {"perfect": False, "landed": False, "crashed": False},
        timed_out=False,
        raw={},
    )
    assert r != pytest.approx(r_a, abs=1e-6)


def test_potential_c_does_not_reward_unlimited_downward_speed():
    """Higher excess vy must not increase Φ_C (must decrease or stay)."""
    soft = np.array([0.0, 0.5, 0.0, 0.05, 0.0, 0, 1, 0, 1, 0.5], dtype=np.float32)
    hard = np.array([0.0, 0.5, 0.0, 0.5, 0.0, 0, 1, 0, 1, 0.5], dtype=np.float32)
    assert _potential_c(hard) < _potential_c(soft)


def test_legacy_sparse_d_still_pm1():
    env = _env("sparse_d")
    obs = np.zeros(10, dtype=np.float32)
    assert (
        env._train_reward(obs, {"landed": True, "perfect": True}, False, {}) == 1.0
    )
    assert env._train_reward(obs, {"crashed": True}, False, {}) == -1.0


def test_seed_pools_and_train_bases():
    assert len(ABCD_DEV_SEEDS) == 50
    assert len(ABCD_HELD_OUT_SEEDS) == 100
    assert len(ABCD_AUDIT_SEEDS) >= 10
    assert not set(ABCD_AUDIT_SEEDS) & set(ABCD_HELD_OUT_SEEDS)
    assert ABCD_REWARD_MODE == {
        "A": "abcd_a",
        "B": "abcd_b",
        "C": "abcd_c",
        "D": "abcd_d",
    }
    assert len(ABCD_TRAIN_BASES) == 12
    assert abcd_train_auto_seed_base("A", 0) == 900_000
    assert abcd_train_auto_seed_base("D", 2) == 900_000 + 3 * 30_000 + 2 * 10_000
