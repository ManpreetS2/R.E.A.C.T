"""In-process retries, rate limits, and a provider spending cap."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from rewardbench.contracts import BudgetExceeded


@dataclass(frozen=True)
class RetryPolicy:
    """Extra attempts after the first request. The runner may retry again."""

    max_retries: int = 2
    base_delay_s: float = 0.25
    max_delay_s: float = 8.0

    def delay(self, attempt: int, rng: random.Random, retry_after_s: float | None) -> float:
        if retry_after_s is not None:
            return min(self.max_delay_s, retry_after_s)
        growth = self.base_delay_s * (2**attempt)
        # Half to full delay. The injected RNG keeps tests deterministic.
        return min(self.max_delay_s, growth * (0.5 + rng.random() * 0.5))


@dataclass
class RateLimiter:
    """A local token bucket. This does not coordinate across processes."""

    min_interval_s: float = 0.0
    max_per_window: int | None = None
    window_s: float = 60.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: float | None = field(default=None, init=False)
    _stamps: list[float] = field(default_factory=list, init=False)

    def acquire(self) -> None:
        now = self.clock()
        if self.min_interval_s > 0 and self._last is not None:
            wait = self._last + self.min_interval_s - now
            if wait > 0:
                self.sleep(wait)
                now = self.clock()
        if self.max_per_window is not None and self.max_per_window > 0:
            self._stamps = [stamp for stamp in self._stamps if now - stamp < self.window_s]
            if len(self._stamps) >= self.max_per_window:
                wait = self.window_s - (now - self._stamps[0])
                if wait > 0:
                    self.sleep(wait)
                    now = self.clock()
                self._stamps = [stamp for stamp in self._stamps if now - stamp < self.window_s]
        self._stamps.append(now)
        self._last = now


@dataclass
class SpendingGuard:
    """Reserve an estimate before the request, then charge the priced result.

    A call that cannot be priced is refused when a cap is set. The guard does
    not invent a rate. One in-flight response can finish after its estimate;
    the next call stops if the cap is already exhausted.
    """

    max_spend_usd: float | None = None
    spent_usd: float = 0.0

    @property
    def capped(self) -> bool:
        return self.max_spend_usd is not None

    def ensure(self, estimate_usd: float) -> None:
        if self.max_spend_usd is None:
            return
        projected = self.spent_usd + max(0.0, estimate_usd)
        if projected > self.max_spend_usd + 1e-12:
            raise BudgetExceeded(
                (
                    f"estimated request cost {estimate_usd:.6f} USD would bring "
                    f"provider spend to {projected:.6f} USD, over the cap "
                    f"{self.max_spend_usd:.6f} USD"
                ),
                resource="provider_cost_usd",
                spent=self.spent_usd,
                limit=self.max_spend_usd,
            )

    def charge(self, actual_usd: float) -> None:
        if actual_usd < 0:
            actual_usd = 0.0
        self.spent_usd += actual_usd
