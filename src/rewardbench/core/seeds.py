"""Deterministic episode seeds that stay inside one split."""

from __future__ import annotations

import hashlib
from typing import Sequence

from rewardbench.contracts import ConfigError


def build_seed_schedule(
    master_seed: int,
    allowed_seeds: Sequence[int],
    num_revisions: int,
    episodes_per_revision: int,
) -> tuple[tuple[int, ...], ...]:
    """Assign an environment seed to every revision and episode.

    Ordering uses SHA-256 of ``master_seed:seed`` so the schedule does not
    depend on Python's ``random`` implementation. When more episodes are
    requested than seeds, the permutation repeats from the start.
    """

    if isinstance(master_seed, bool) or not isinstance(master_seed, int):
        raise ConfigError("master_seed must be an integer")
    if num_revisions < 1 or episodes_per_revision < 1:
        raise ConfigError("schedule dimensions must be >= 1")
    if len(allowed_seeds) == 0:
        raise ConfigError("allowed_seeds must be non-empty")
    order = tuple(
        sorted(
            allowed_seeds,
            key=lambda seed: hashlib.sha256(f"{master_seed}:{seed}".encode("utf-8")).hexdigest(),
        )
    )
    schedule: list[tuple[int, ...]] = []
    for revision in range(num_revisions):
        row: list[int] = []
        for episode in range(episodes_per_revision):
            index = revision * episodes_per_revision + episode
            row.append(order[index % len(order)])
        schedule.append(tuple(row))
    return tuple(schedule)
