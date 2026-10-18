"""Reserved ApolloLander episode seeds that RL pilot code must never touch.

Owner safeguard: seeds ``2000000`` through ``2000015`` inclusive are sealed.
They must not be used for training, evaluation, rendering, reset, or inspection.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

RESERVED_SEED_START = 2_000_000
RESERVED_SEED_END = 2_000_015  # inclusive
RESERVED_SEEDS = frozenset(range(RESERVED_SEED_START, RESERVED_SEED_END + 1))


class ReservedSeedError(ValueError):
    """Raised when a reserved sealed seed is requested."""


def is_reserved_seed(seed: int) -> bool:
    if isinstance(seed, bool) or not isinstance(seed, int):
        return False
    return seed in RESERVED_SEEDS


def assert_seed_allowed(seed: int, *, context: str = "episode") -> None:
    """Raise if ``seed`` is in the reserved sealed range."""
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError(f"{context} seed must be an integer")
    if is_reserved_seed(seed):
        raise ReservedSeedError(
            f"{context} seed {seed} is reserved and sealed "
            f"({RESERVED_SEED_START}..{RESERVED_SEED_END} inclusive); "
            "RL pilot code must not train on, evaluate on, render, reset with, "
            "or otherwise inspect this seed"
        )


def assert_seeds_allowed(seeds: Sequence[int] | Iterable[int], *, context: str = "episode") -> None:
    for seed in seeds:
        assert_seed_allowed(int(seed), context=context)
