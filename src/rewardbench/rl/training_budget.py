"""Hard-capped training physics-frame counter — refuse steps that would overshoot."""

from __future__ import annotations

from dataclasses import dataclass, field


class TrainingBudgetExhausted(RuntimeError):
    """Raised when a training step would exceed the hard cap."""


@dataclass
class TrainingBudget:
    hard_cap: int
    spent: int = 0
    ledger: list[dict] = field(default_factory=list)

    def remaining(self) -> int:
        return max(0, int(self.hard_cap) - int(self.spent))

    def can_afford(self, frames: int) -> bool:
        return int(self.spent) + int(frames) <= int(self.hard_cap)

    def require(self, frames: int, *, reason: str) -> None:
        frames = int(frames)
        if frames < 0:
            raise ValueError("training frames must be non-negative")
        if not self.can_afford(frames):
            raise TrainingBudgetExhausted(
                f"training hard cap {self.hard_cap} would be exceeded BEFORE step: "
                f"spent={self.spent}, requested={frames}, remaining={self.remaining()}, "
                f"reason={reason!r}"
            )

    def charge(self, frames: int, *, reason: str) -> int:
        self.require(frames, reason=reason)
        self.spent += int(frames)
        self.ledger.append({"reason": reason, "frames": int(frames), "spent_after": self.spent})
        return self.spent

    def snapshot(self) -> dict:
        return {
            "hard_cap": int(self.hard_cap),
            "spent": int(self.spent),
            "remaining": self.remaining(),
            "ledger_tail": list(self.ledger[-20:]),
            "ledger_len": len(self.ledger),
        }
