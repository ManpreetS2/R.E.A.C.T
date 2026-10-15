from rewardbench.contracts import EpisodeResult, FeedbackCondition, RewardFeedback
from rewardbench.core.feedback import feedback_for_revision
from rewardbench.core.history import HistoryBuilder, RevisionHistoryEntry


def _episode(revision: int, episode: int, reward: float) -> EpisodeResult:
    return EpisodeResult(
        revision_index=revision,
        episode_index=episode,
        seed=1000 + episode,
        total_reward=reward,
        success=reward > 0,
        crashed=reward < 0,
        steps=4,
        terminated=True,
        truncated=False,
        elapsed_seconds=0.1,
        metrics={"fuel_used": 1.0},
    )


def _entry(revision: int, reward: float) -> RevisionHistoryEntry:
    return RevisionHistoryEntry(
        revision_index=revision,
        parameters={"gain": reward},
        valid=True,
        validation_error=None,
        episodes=(_episode(revision, 0, reward),),
    )


def test_history_window_keeps_the_latest_revisions() -> None:
    builder = HistoryBuilder(1, FeedbackCondition.NUMERICAL_REWARD)
    history = builder.build((_entry(0, 1.0), _entry(1, 2.0), _entry(2, 3.0)))
    assert [item.revision_index for item in history] == [2]
    assert history[0].feedback is not None
    assert history[0].feedback[0].total_reward == 3.0
    assert history[0].feedback[0].metrics["fuel_used"] == 1.0


def test_zero_window_hides_every_prior_attempt() -> None:
    builder = HistoryBuilder(0, FeedbackCondition.NUMERICAL_REWARD)
    assert builder.build((_entry(0, 1.0),)) == ()


def test_no_feedback_withholds_rewards_but_keeps_the_controller() -> None:
    builder = HistoryBuilder(2, FeedbackCondition.NO_FEEDBACK)
    history = builder.build((_entry(0, -5.0),))
    assert history[0].parameters["gain"] == -5.0
    assert history[0].feedback is None
    assert history[0].validation_error is None


def test_failed_episodes_are_omitted_from_numerical_feedback() -> None:
    failed = EpisodeResult(
        revision_index=0,
        episode_index=1,
        seed=3,
        total_reward=0.0,
        success=False,
        crashed=True,
        steps=1,
        terminated=True,
        truncated=False,
        elapsed_seconds=0.0,
        error="boom",
    )
    feedback = feedback_for_revision((_episode(0, 0, 4.0), failed), FeedbackCondition.NUMERICAL_REWARD)
    assert feedback is not None
    assert len(feedback) == 1
    assert isinstance(feedback[0], RewardFeedback)
    assert feedback_for_revision((_episode(0, 0, 4.0),), FeedbackCondition.NO_FEEDBACK) is None
