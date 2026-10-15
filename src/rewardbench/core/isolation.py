"""Keep model-facing history inside the active split and feedback condition."""

from __future__ import annotations

from typing import Mapping, Sequence

from rewardbench.contracts import ConfigError, FeedbackCondition, PriorAttempt
from rewardbench.core.history import HistoryBuilder, RevisionHistoryEntry

_REWARD_KEYS = {"total_reward", "fuel_used", "reward", "score"}


def model_history(
    builder: HistoryBuilder,
    entries: Sequence[RevisionHistoryEntry],
    allowed_seeds: Sequence[int],
) -> tuple[PriorAttempt, ...]:
    """History that is safe to place on ``ModelRequest``.

    Episodes from outside the active seed pool are dropped. Under
    ``no_feedback``, rewards are removed again so a stored score cannot ride
    along on the request.
    """

    allowed = set(allowed_seeds)
    visible: list[RevisionHistoryEntry] = []
    for entry in entries:
        episodes = tuple(episode for episode in entry.episodes if episode.seed in allowed)
        visible.append(
            RevisionHistoryEntry(
                revision_index=entry.revision_index,
                parameters=dict(entry.parameters),
                valid=entry.valid,
                validation_error=_clean_error(entry.validation_error, builder.condition),
                episodes=episodes,
            )
        )
    history = builder.build(visible)
    if builder.condition is not FeedbackCondition.NO_FEEDBACK:
        return history
    redacted = tuple(
        PriorAttempt(
            revision_index=item.revision_index,
            parameters=dict(item.parameters),
            valid=item.valid,
            validation_error=_clean_error(item.validation_error, builder.condition),
            feedback=None,
        )
        for item in history
    )
    for item in redacted:
        if item.feedback is not None:
            raise ConfigError("no-feedback history included numerical rewards")
        _reject_reward_keys(item.parameters)
    return redacted


def _clean_error(message: str | None, condition: FeedbackCondition) -> str | None:
    if message is None or condition is not FeedbackCondition.NO_FEEDBACK:
        return message
    lowered = message.lower()
    if any(token in lowered for token in _REWARD_KEYS):
        return "controller was rejected"
    return message


def _reject_reward_keys(value: object) -> None:
    if isinstance(value, Mapping):
        for key, inner in value.items():
            if str(key).lower() in _REWARD_KEYS:
                raise ConfigError("no-feedback history included a reward field")
            _reject_reward_keys(inner)
        return
    if isinstance(value, (list, tuple)):
        for inner in value:
            _reject_reward_keys(inner)
