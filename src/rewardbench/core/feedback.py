"""Build the reward view that a model is allowed to see."""

from __future__ import annotations

import math
from dataclasses import replace
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
        item = RewardFeedback.from_episode(episode)
        if condition is FeedbackCondition.REWARD_ONLY:
            # Defense in depth: outcome fields never leave this function, so no
            # ModelClient can read them even if it bypasses the prompt renderer.
            item = replace(item, success=False, crashed=None, steps=0, metrics={})
        feedback.append(item)
    return tuple(feedback)
