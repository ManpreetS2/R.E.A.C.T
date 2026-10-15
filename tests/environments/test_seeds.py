"""Development seeds stay out of the held-out evaluation range."""

from __future__ import annotations

import pytest

from rewardbench.environments.lunarlander.seeds import (
    HELD_OUT_SEED_START,
    development_seeds,
    held_out_seeds,
    validate_seed_split,
)


def test_development_and_held_out_ranges_are_disjoint() -> None:
    development = development_seeds(1_000)
    held_out = held_out_seeds(1_000)
    assert development[0] == 0
    assert held_out[0] == HELD_OUT_SEED_START
    assert set(development).isdisjoint(held_out)
    assert max(development) < min(held_out)


def test_development_range_cannot_cross_the_held_out_boundary() -> None:
    edge = development_seeds(1, start=HELD_OUT_SEED_START - 1)
    assert edge == [HELD_OUT_SEED_START - 1]
    with pytest.raises(ValueError, match="held-out"):
        development_seeds(2, start=HELD_OUT_SEED_START - 1)


def test_split_guard_rejects_contaminated_seeds() -> None:
    with pytest.raises(ValueError, match="held-out"):
        validate_seed_split([0, HELD_OUT_SEED_START], "development")
    with pytest.raises(ValueError, match="development"):
        validate_seed_split([HELD_OUT_SEED_START, 0], "held_out")
    validate_seed_split([HELD_OUT_SEED_START, HELD_OUT_SEED_START + 1], "held_out")
    validate_seed_split([0, HELD_OUT_SEED_START], "unrestricted")
