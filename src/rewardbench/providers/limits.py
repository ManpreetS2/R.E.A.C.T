"""In-process retries, rate limits, and a provider spending cap."""

from __future__ import annotations

import random
import threading
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
    """Hold a worst-case reservation before a request, then charge the bill.

    ``held_usd`` covers calls that have been allowed but have not finished.
    The lock makes that check safe for concurrent ``propose`` calls that share
    one guard. The guard does not invent a price. Releasing a reservation
    never increases ``spent_usd``.
    """

    max_spend_usd: float | None = None
    spent_usd: float = 0.0
    held_usd: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    @property
    def capped(self) -> bool:
        return self.max_spend_usd is not None

    def reserve(self, amount_usd: float) -> float:
        amount = max(0.0, amount_usd)
        with self._lock:
            if self.max_spend_usd is not None:
                projected = self.spent_usd + self.held_usd + amount
                if projected > self.max_spend_usd + 1e-12:
                    raise BudgetExceeded(
                        (
                            f"reserved request cost {amount:.6f} USD would bring "
                            f"provider commitments to {projected:.6f} USD, over the cap "
                            f"{self.max_spend_usd:.6f} USD"
                        ),
                        resource="provider_cost_usd",
                        spent=self.spent_usd + self.held_usd,
                        limit=self.max_spend_usd,
                    )
            self.held_usd += amount
            return amount

    def settle(self, reserved_usd: float, actual_usd: float) -> None:
        actual = max(0.0, actual_usd)
        with self._lock:
            self.held_usd = max(0.0, self.held_usd - max(0.0, reserved_usd))
            self.spent_usd += actual
            if self.max_spend_usd is not None and self.spent_usd > self.max_spend_usd + 1e-9:
                raise BudgetExceeded(
                    (
                        f"billed cost {actual:.6f} USD brought provider spend to "
                        f"{self.spent_usd:.6f} USD, over the cap {self.max_spend_usd:.6f} USD"
                    ),
                    resource="provider_cost_usd",
                    spent=self.spent_usd,
                    limit=self.max_spend_usd,
                )

    def release(self, reserved_usd: float) -> None:
        with self._lock:
            self.held_usd = max(0.0, self.held_usd - max(0.0, reserved_usd))
