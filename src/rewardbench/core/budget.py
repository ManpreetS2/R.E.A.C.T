"""Cumulative experiment and process-wide budget limits."""

from __future__ import annotations

import time
from collections.abc import Callable

from rewardbench.contracts import BudgetExceeded, BudgetLimits, BudgetSnapshot, ConfigError


class BudgetLimiter:
    """Tracks spend and raises ``BudgetExceeded`` before the next blocked action.

    A charge that crosses a limit is kept. The exception tells the runner to
    stop further model calls and episodes. ``clock`` returns seconds from an
    arbitrary origin; tests pass a fake clock, and resumes restore elapsed time.
    """

    def __init__(
        self,
        limits: BudgetLimits,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if not isinstance(limits, BudgetLimits):
            raise ConfigError("limits must be a BudgetLimits")
        self.limits = limits
        self._clock = clock or time.monotonic
        self.cost_usd = 0.0
        self.tokens = 0
        self.episodes = 0
        self.revisions = 0
        self.model_calls = 0
        self._elapsed_offset = 0.0
        self._started = self._clock()

    def elapsed(self) -> float:
        return self._elapsed_offset + (self._clock() - self._started)

    def snapshot(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            cost_usd=self.cost_usd,
            tokens=self.tokens,
            episodes=self.episodes,
            revisions=self.revisions,
            model_calls=self.model_calls,
            elapsed_seconds=self.elapsed(),
        )

    def restore(self, snapshot: BudgetSnapshot) -> None:
        self.cost_usd = snapshot.cost_usd
        self.tokens = snapshot.tokens
        self.episodes = snapshot.episodes
        self.revisions = snapshot.revisions
        self.model_calls = snapshot.model_calls
        self._elapsed_offset = snapshot.elapsed_seconds
        self._started = self._clock()

    def ensure_can_start(
        self,
        *,
        model_call: bool = False,
        episode: bool = False,
        revision: bool = False,
    ) -> None:
        """Raise when the next action would pass a limit, or time is already up."""

        self._check_wall_clock()
        self._check_already_spent()
        if model_call:
            self._check_increment("max_model_calls", self.model_calls, self.limits.max_model_calls)
        if episode:
            self._check_increment("max_episodes", self.episodes, self.limits.max_episodes)
        if revision:
            self._check_increment("max_revisions", self.revisions, self.limits.max_revisions)

    def ensure_within_limits(self) -> None:
        """Raise when spend has already passed a limit."""

        self._check_wall_clock()
        if self.limits.max_cost_usd is not None and self.cost_usd > self.limits.max_cost_usd:
            self._raise("max_cost_usd", self.cost_usd, self.limits.max_cost_usd)
        if self.limits.max_tokens is not None and self.tokens > self.limits.max_tokens:
            self._raise("max_tokens", self.tokens, self.limits.max_tokens)
        if self.limits.max_episodes is not None and self.episodes > self.limits.max_episodes:
            self._raise("max_episodes", self.episodes, self.limits.max_episodes)
        if self.limits.max_revisions is not None and self.revisions > self.limits.max_revisions:
            self._raise("max_revisions", self.revisions, self.limits.max_revisions)
        if self.limits.max_model_calls is not None and self.model_calls > self.limits.max_model_calls:
            self._raise("max_model_calls", self.model_calls, self.limits.max_model_calls)

    def charge(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        episodes: int = 0,
        revisions: int = 0,
        model_calls: int = 0,
    ) -> None:
        for name, value in (
            ("cost_usd", cost_usd),
            ("tokens", tokens),
            ("episodes", episodes),
            ("revisions", revisions),
            ("model_calls", model_calls),
        ):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ConfigError(f"{name} charge must be a non-negative number")
        self.cost_usd += float(cost_usd)
        self.tokens += int(tokens)
        self.episodes += int(episodes)
        self.revisions += int(revisions)
        self.model_calls += int(model_calls)
        self.ensure_within_limits()

    def _check_wall_clock(self) -> None:
        limit = self.limits.max_wall_seconds
        if limit is not None and self.elapsed() >= limit:
            self._raise("max_wall_seconds", self.elapsed(), limit)

    def _check_already_spent(self) -> None:
        if self.limits.max_cost_usd is not None and self.cost_usd >= self.limits.max_cost_usd:
            self._raise("max_cost_usd", self.cost_usd, self.limits.max_cost_usd)
        if self.limits.max_tokens is not None and self.tokens >= self.limits.max_tokens:
            self._raise("max_tokens", self.tokens, self.limits.max_tokens)

    def _check_increment(self, resource: str, spent: int, limit: int | None) -> None:
        if limit is not None and spent + 1 > limit:
            self._raise(resource, spent, limit)

    def _raise(self, resource: str, spent: float, limit: float) -> None:
        raise BudgetExceeded(
            f"{resource} budget exhausted (spent={spent}, limit={limit})",
            resource=resource,
            spent=float(spent),
            limit=float(limit),
        )
