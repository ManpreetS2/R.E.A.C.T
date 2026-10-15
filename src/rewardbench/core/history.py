"""Bounded memory of earlier controller revisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from rewardbench.contracts import (
    ConfigError,
    EpisodeResult,
    FeedbackCondition,
    PriorAttempt,
)
from rewardbench.core.feedback import feedback_for_revision


@dataclass(frozen=True)
class RevisionHistoryEntry:
    """A stored revision plus the episodes the runner may reveal."""

    revision_index: int
    parameters: Mapping[str, object]
    valid: bool
    validation_error: str | None
    episodes: tuple[EpisodeResult, ...]


class HistoryBuilder:
    """Keep the last ``window`` revisions and apply the feedback condition."""

    def __init__(self, window: int, condition: FeedbackCondition) -> None:
        if isinstance(window, bool) or not isinstance(window, int) or window < 0:
            raise ConfigError("history_window must be >= 0")
        if not isinstance(condition, FeedbackCondition):
            raise ConfigError("condition must be a FeedbackCondition")
        self.window = window
        self.condition = condition

    def build(self, entries: Sequence[RevisionHistoryEntry]) -> tuple[PriorAttempt, ...]:
        if self.window == 0:
            return ()
        selected = tuple(entries[-self.window :])
        attempts: list[PriorAttempt] = []
        for entry in selected:
            attempts.append(
                PriorAttempt(
                    revision_index=entry.revision_index,
                    parameters=dict(entry.parameters),
                    valid=entry.valid,
                    validation_error=entry.validation_error,
                    feedback=feedback_for_revision(entry.episodes, self.condition),
                )
            )
        return tuple(attempts)
