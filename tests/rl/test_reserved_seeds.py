"""Reserved sealed seeds 2000000..2000015 must be unusable by the RL pilot."""

from __future__ import annotations

import pytest

from rewardbench.rl.env import ApolloLanderPythonEnv, EnvConfig
from rewardbench.rl.reserved_seeds import (
    RESERVED_SEED_END,
    RESERVED_SEED_START,
    RESERVED_SEEDS,
    ReservedSeedError,
    assert_seed_allowed,
    assert_seeds_allowed,
    is_reserved_seed,
)


def test_reserved_range_is_exactly_sixteen_seeds() -> None:
    assert RESERVED_SEED_START == 2_000_000
    assert RESERVED_SEED_END == 2_000_015
    assert len(RESERVED_SEEDS) == 16
    assert min(RESERVED_SEEDS) == RESERVED_SEED_START
    assert max(RESERVED_SEEDS) == RESERVED_SEED_END


@pytest.mark.parametrize("seed", [2_000_000, 2_000_007, 2_000_015])
def test_assert_seed_allowed_raises_on_reserved(seed: int) -> None:
    assert is_reserved_seed(seed)
    with pytest.raises(ReservedSeedError, match="reserved and sealed"):
        assert_seed_allowed(seed)


@pytest.mark.parametrize("seed", [0, 999_999, 1_000_000, 1_999_999, 2_000_016])
def test_assert_seed_allowed_permits_non_reserved(seed: int) -> None:
    assert not is_reserved_seed(seed)
    assert_seed_allowed(seed)


def test_assert_seeds_allowed_rejects_any_reserved_member() -> None:
    with pytest.raises(ReservedSeedError):
        assert_seeds_allowed([1_000_000, 2_000_000, 1_000_001])


def test_python_env_reset_rejects_reserved_seed() -> None:
    env = ApolloLanderPythonEnv(EnvConfig())
    with pytest.raises(ReservedSeedError):
        env.reset(2_000_000)


def test_config_held_out_seeds_exclude_reserved_range() -> None:
    import yaml
    from pathlib import Path

    raw = yaml.safe_load(Path("examples/apollolander/rl_pilot/config.yaml").read_text(encoding="utf-8"))
    held = list(raw["eval"]["held_out_seeds"])
    footage = list(raw["eval"]["footage_held_out_seeds"])
    assert_seeds_allowed(held)
    assert_seeds_allowed(footage)
    assert not (set(held) & RESERVED_SEEDS)
    assert not (set(footage) & RESERVED_SEEDS)
