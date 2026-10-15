"""Development and held-out simulation seeds.

Training or controller-development seeds stay below ``HELD_OUT_SEED_START``.
Held-out evaluation seeds occupy the disjoint range at and above that offset.
Callers choose a split explicitly so a development run cannot silently
consume the evaluation set.
"""

from __future__ import annotations

from collections.abc import Sequence

HELD_OUT_SEED_START = 1_000_000
MAX_SEED = 2**32 - 1
MAX_EPISODES_PER_REVISION = 500
MAX_SEED_CATALOG = 100_000
SPLIT_DEVELOPMENT = "development"
SPLIT_HELD_OUT = "held_out"
SPLIT_UNRESTRICTED = "unrestricted"
SEED_SPLITS = (SPLIT_DEVELOPMENT, SPLIT_HELD_OUT, SPLIT_UNRESTRICTED)


def development_seeds(count: int, *, start: int = 0) -> list[int]:
    """Return ``count`` development seeds beginning at ``start``."""
    _check_count(count)
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise ValueError("development seed start must be a non-negative integer")
    seeds = [start + offset for offset in range(count)]
    if seeds[-1] >= HELD_OUT_SEED_START:
        raise ValueError(
            "development seed range would overlap the held-out evaluation seeds "
            f"starting at {HELD_OUT_SEED_START}"
        )
    return seeds


def held_out_seeds(count: int, *, start: int = 0) -> list[int]:
    """Return ``count`` held-out seeds. These are not for controller development."""
    _check_count(count)
    if isinstance(start, bool) or not isinstance(start, int) or start < 0:
        raise ValueError("held-out seed start must be a non-negative integer")
    seeds = [HELD_OUT_SEED_START + start + offset for offset in range(count)]
    if seeds[-1] > MAX_SEED:
        raise ValueError("held-out seed range exceeds the supported seed space")
    return seeds


def validate_seed_split(seeds: Sequence[int], split: str) -> None:
    """Reject caller mistakes before any environment is created."""
    if split not in SEED_SPLITS:
        raise ValueError(
            f"seed split {split!r} is unknown; expected one of {', '.join(SEED_SPLITS)}"
        )
    if len(seeds) == 0:
        raise ValueError("at least one episode seed is required")
    if len(seeds) > MAX_EPISODES_PER_REVISION:
        raise ValueError(
            f"a controller revision can run at most {MAX_EPISODES_PER_REVISION} episodes"
        )
    for seed in seeds:
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("episode seeds must be integers")
        if seed < 0 or seed > MAX_SEED:
            raise ValueError(f"episode seed {seed} is outside 0..{MAX_SEED}")
    if split == SPLIT_DEVELOPMENT and any(seed >= HELD_OUT_SEED_START for seed in seeds):
        raise ValueError("development runs cannot use held-out evaluation seeds")
    if split == SPLIT_HELD_OUT and any(seed < HELD_OUT_SEED_START for seed in seeds):
        raise ValueError("held-out runs cannot use development seeds")


def _check_count(count: int) -> None:
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise ValueError("episode count must be a positive integer")
    if count > MAX_SEED_CATALOG:
        raise ValueError(f"episode count must be at most {MAX_SEED_CATALOG}")
