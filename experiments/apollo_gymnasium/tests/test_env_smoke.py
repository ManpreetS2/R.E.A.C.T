"""Smoke tests for the upstream Apollo Gymnasium wrapper."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from env.apollo_env import ApolloLanderGym
from env.starts import resolve_start


@pytest.fixture(scope="module")
def env():
    e = ApolloLanderGym(
        action_repeat=2,
        max_physics_frames=200,
        start_mode="research",
        start_override=resolve_start("pilot_near"),
        headless=True,
        port=18780,
    )
    yield e
    e.close()


def test_spaces(env):
    assert env.observation_space.shape == (10,)
    assert env.action_space.nvec.tolist() == [5, 3]


def test_reset_step(env):
    obs, info = env.reset(seed=1)
    assert obs.shape == (10,)
    assert info["engine"] == "upstream-original"
    assert info["zone"]["width"] > 100
    obs2, reward, term, trunc, info2 = env.step(np.array([0, 1], dtype=np.int64))
    assert obs2.shape == (10,)
    assert isinstance(reward, float)
    assert info2["physics_frames"] == 2


def test_reset_reproducible(env):
    o1, _ = env.reset(seed=99)
    o2, _ = env.reset(seed=99)
    assert np.allclose(o1, o2)
