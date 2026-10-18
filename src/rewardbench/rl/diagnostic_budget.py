"""Hard-capped diagnostic physics-frame counter for RL experiments.

Diagnostics include baselines, gates, evals, step-0 measurement, and parity
reruns. Training physics frames are tracked separately and must not use this
counter.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class DiagnosticBudgetExhausted(RuntimeError):
    """Raised when a diagnostic spend would exceed the hard cap."""


@dataclass
class DiagnosticBudget:
    """Mutable counter with a non-raisable hard cap (do not raise the cap)."""

    hard_cap: int
    spent: int = 0
    ledger: list[dict] = field(default_factory=list)

    def remaining(self) -> int:
        return max(0, int(self.hard_cap) - int(self.spent))

    def can_afford(self, frames: int) -> bool:
        return int(self.spent) + int(frames) <= int(self.hard_cap)

    def charge(self, frames: int, *, reason: str) -> int:
        """Charge ``frames`` or raise if the spend would exceed the cap."""
        frames = int(frames)
        if frames < 0:
            raise ValueError("diagnostic frames must be non-negative")
        if not self.can_afford(frames):
            raise DiagnosticBudgetExhausted(
                f"diagnostic hard cap {self.hard_cap} reached: "
                f"spent={self.spent}, requested={frames}, reason={reason!r}"
            )
        self.spent += frames
        self.ledger.append({"reason": reason, "frames": frames, "spent_after": self.spent})
        return self.spent

    def snapshot(self) -> dict:
        return {
            "hard_cap": int(self.hard_cap),
            "spent": int(self.spent),
            "remaining": self.remaining(),
            "ledger": list(self.ledger),
        }
