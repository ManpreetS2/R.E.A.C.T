"""Build the reward view that a model is allowed to see."""

from __future__ import annotations

import math
from typing import Sequence

from rewardbench.contracts import EpisodeResult, FeedbackCondition, RewardFeedback


def feedback_for_revision(
    episodes: Sequence[EpisodeResult],
    condition: FeedbackCondition,
) -> tuple[RewardFeedback, ...] | None:
    """Return rewards for one revision, or ``None`` when they are withheld.

    Episodes that failed before producing a finite reward are omitted. The
    runner still stores those rows. An empty tuple means the numerical
    condition is on and this revision has no scores.
    """

    # reward_only keeps the same episodes; the prompt renderer prints only the reward.
    if condition is FeedbackCondition.NO_FEEDBACK:
        return None
    feedback: list[RewardFeedback] = []
    for episode in episodes:
        if episode.error is not None:
            continue
        if isinstance(episode.total_reward, bool) or not isinstance(episode.total_reward, (int, float)):
            continue
        if not math.isfinite(float(episode.total_reward)):
            continue
        feedback.append(RewardFeedback.from_episode(episode))
    return tuple(feedback)
