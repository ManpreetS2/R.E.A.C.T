"""Cumulative experiment and process-wide budget limits."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from rewardbench.contracts import BudgetExceeded, BudgetLimits, BudgetSnapshot, ConfigError


class _SpendHold:
    """In-flight reservation. Settling or cancelling it is idempotent."""

    def __init__(
        self,
        *,
        key: str,
        reserved_cost: float,
        reserved_tokens: int,
        model_calls: int,
        episodes: int,
        revisions: int,
    ) -> None:
        self.key = key
        self.reserved_cost = reserved_cost
        self.reserved_tokens = reserved_tokens
        self.model_calls = model_calls
        self.episodes = episodes
        self.revisions = revisions
        self.active = True


class BudgetLimiter:
    """Tracks spend and raises ``BudgetExceeded`` before the next blocked action.

    A charge that crosses a limit is kept. The exception tells the runner to
    stop further model calls. ``clock`` returns seconds from an arbitrary
    origin; tests pass a fake clock, and resumes restore elapsed time.

    Shared limiters are safe for overlapping runs. ``begin`` reserves the
    remaining dollar and token cap for one in-flight model call, and other
    callers wait until that call settles. ``commit_once`` records spend that
    is already stored so a new limiter cannot ignore it.
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
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._keys: set[str] = set()
        self._inflight = 0

    def elapsed(self) -> float:
        with self._cv:
            return self._elapsed_unlocked()

    def snapshot(self) -> BudgetSnapshot:
        with self._cv:
            return self._snapshot_unlocked()

    def restore(self, snapshot: BudgetSnapshot) -> None:
        with self._cv:
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
        """Raise when the next action would pass a limit, or time is already up.

        Dollar and token caps block further model calls. They do not block an
        episode for a controller that has already been paid for.
        """

        with self._cv:
            self._ensure_can_start_unlocked(
                model_call=model_call,
                episode=episode,
                revision=revision,
            )

    def ensure_within_limits(self) -> None:
        """Raise when spend has already passed a limit."""

        with self._cv:
            self._ensure_within_unlocked()

    def charge(
        self,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        episodes: int = 0,
        revisions: int = 0,
        model_calls: int = 0,
    ) -> None:
        amounts = _nonnegative(cost_usd=cost_usd, tokens=tokens, episodes=episodes, revisions=revisions, model_calls=model_calls)
        with self._cv:
            self._add_unlocked(**amounts)
            self._cv.notify_all()
            self._ensure_within_unlocked()

    def commit_once(
        self,
        key: str,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        episodes: int = 0,
        revisions: int = 0,
        model_calls: int = 0,
    ) -> None:
        """Record spend for ``key`` at most once, even if the total is over the cap."""

        amounts = _nonnegative(cost_usd=cost_usd, tokens=tokens, episodes=episodes, revisions=revisions, model_calls=model_calls)
        with self._cv:
            if key in self._keys:
                return
            self._keys.add(key)
            self._add_unlocked(**amounts)
            self._cv.notify_all()

    def begin(
        self,
        *,
        key: str,
        model_call: bool = False,
        episode: bool = False,
        revision: bool = False,
    ) -> _SpendHold | None:
        """Reserve one action. Returns ``None`` when ``key`` was already recorded.

        A model call reserves the remaining dollar and token budget so a second
        caller cannot start a paid call until this one settles.
        """

        with self._cv:
            while True:
                if key in self._keys:
                    return None
                try:
                    self._ensure_can_start_unlocked(
                        model_call=model_call,
                        episode=episode,
                        revision=revision,
                    )
                    break
                except BudgetExceeded:
                    if self._inflight == 0:
                        raise
                    self._cv.wait()
            reserved_cost = 0.0
            reserved_tokens = 0
            if model_call:
                if self.limits.max_cost_usd is not None:
                    reserved_cost = max(0.0, float(self.limits.max_cost_usd) - self.cost_usd)
                    self.cost_usd += reserved_cost
                if self.limits.max_tokens is not None:
                    reserved_tokens = max(0, int(self.limits.max_tokens) - self.tokens)
                    self.tokens += reserved_tokens
            hold = _SpendHold(
                key=key,
                reserved_cost=reserved_cost,
                reserved_tokens=reserved_tokens,
                model_calls=1 if model_call else 0,
                episodes=1 if episode else 0,
                revisions=1 if revision else 0,
            )
            self.model_calls += hold.model_calls
            self.episodes += hold.episodes
            self.revisions += hold.revisions
            self._inflight += 1
            return hold

    def settle(
        self,
        hold: _SpendHold | None,
        *,
        cost_usd: float = 0.0,
        tokens: int = 0,
        episodes: int = 0,
        revisions: int = 0,
        model_calls: int = 0,
    ) -> None:
        """Replace a reservation with the measured spend and wake waiters."""

        if hold is None:
            return
        amounts = _nonnegative(
            cost_usd=cost_usd,
            tokens=tokens,
            episodes=episodes,
            revisions=revisions,
            model_calls=model_calls,
        )
        with self._cv:
            if not hold.active:
                return
            if hold.key in self._keys:
                self._rollback_unlocked(hold)
                self._cv.notify_all()
                return
            self.cost_usd = self.cost_usd - hold.reserved_cost + amounts["cost_usd"]
            self.tokens = self.tokens - hold.reserved_tokens + int(amounts["tokens"])
            self.model_calls += int(amounts["model_calls"]) - hold.model_calls
            self.episodes += int(amounts["episodes"]) - hold.episodes
            self.revisions += int(amounts["revisions"]) - hold.revisions
            self._keys.add(hold.key)
            hold.active = False
            self._inflight -= 1
            self._cv.notify_all()
            self._ensure_within_unlocked()

    def cancel(self, hold: _SpendHold | None) -> None:
        """Drop a reservation when the paid action did not happen."""

        if hold is None:
            return
        with self._cv:
            if not hold.active:
                return
            self._rollback_unlocked(hold)
            self._cv.notify_all()

    def _elapsed_unlocked(self) -> float:
        return self._elapsed_offset + (self._clock() - self._started)

    def _snapshot_unlocked(self) -> BudgetSnapshot:
        return BudgetSnapshot(
            cost_usd=self.cost_usd,
            tokens=self.tokens,
            episodes=self.episodes,
            revisions=self.revisions,
            model_calls=self.model_calls,
            elapsed_seconds=self._elapsed_unlocked(),
        )

    def _add_unlocked(
        self,
        *,
        cost_usd: float,
        tokens: int,
        episodes: int,
        revisions: int,
        model_calls: int,
    ) -> None:
        self.cost_usd += cost_usd
        self.tokens += int(tokens)
        self.episodes += int(episodes)
        self.revisions += int(revisions)
        self.model_calls += int(model_calls)

    def _rollback_unlocked(self, hold: _SpendHold) -> None:
        self.cost_usd -= hold.reserved_cost
        self.tokens -= hold.reserved_tokens
        self.model_calls -= hold.model_calls
        self.episodes -= hold.episodes
        self.revisions -= hold.revisions
        hold.active = False
        self._inflight -= 1

    def _ensure_can_start_unlocked(
        self,
        *,
        model_call: bool,
        episode: bool,
        revision: bool,
    ) -> None:
        self._check_wall_clock()
        if model_call:
            self._check_already_spent()
            self._check_increment("max_model_calls", self.model_calls, self.limits.max_model_calls)
        if revision:
            self._check_increment("max_revisions", self.revisions, self.limits.max_revisions)
        if episode:
            self._check_increment("max_episodes", self.episodes, self.limits.max_episodes)

    def _ensure_within_unlocked(self) -> None:
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

    def _check_wall_clock(self) -> None:
        limit = self.limits.max_wall_seconds
        if limit is not None and self._elapsed_unlocked() >= limit:
            self._raise("max_wall_seconds", self._elapsed_unlocked(), limit)

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


def _nonnegative(
    *,
    cost_usd: float,
    tokens: int,
    episodes: int,
    revisions: int,
    model_calls: int,
) -> dict[str, float]:
    amounts: dict[str, float] = {
        "cost_usd": cost_usd,
        "tokens": tokens,
        "episodes": episodes,
        "revisions": revisions,
        "model_calls": model_calls,
    }
    for name, value in amounts.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ConfigError(f"{name} charge must be a non-negative number")
    return amounts
