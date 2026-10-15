"""Development versus held-out seed isolation."""

from __future__ import annotations

from typing import Sequence

from rewardbench.contracts import ConfigError, Split, SplitViolation


class SplitGuard:
    """Refuse seeds that belong to the other split."""

    def __init__(
        self,
        split: Split,
        development_seeds: Sequence[int],
        held_out_seeds: Sequence[int],
    ) -> None:
        if not isinstance(split, Split):
            raise ConfigError("split must be a Split")
        self.split = split
        self.development_seeds = tuple(development_seeds)
        self.held_out_seeds = tuple(held_out_seeds)
        overlap = set(self.development_seeds) & set(self.held_out_seeds)
        if overlap:
            raise ConfigError(
                "development_seeds and held_out_seeds must be disjoint; "
                f"overlap={sorted(overlap)}"
            )
        if split is Split.DEVELOPMENT:
            self._allowed = set(self.development_seeds)
            self._forbidden = set(self.held_out_seeds)
        else:
            self._allowed = set(self.held_out_seeds)
            self._forbidden = set(self.development_seeds)
        if not self._allowed:
            raise ConfigError(f"{split.value} seed pool must be non-empty")

    def allowed_seeds(self) -> tuple[int, ...]:
        if self.split is Split.DEVELOPMENT:
            return self.development_seeds
        return self.held_out_seeds

    def check(self, seed: int) -> None:
        if seed in self._forbidden or seed not in self._allowed:
            raise SplitViolation(
                f"seed {seed} is not allowed for the {self.split.value} split"
            )
