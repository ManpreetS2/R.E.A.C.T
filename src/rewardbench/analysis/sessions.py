"""Per-session summaries and group estimates.

Sessions are summarized first. Group intervals are then taken across those
session summaries. Episode-level pooling is not used for confidence intervals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from rewardbench.analysis.schema import AttemptObservation, EpisodeObservation, Interval, LogBundle
from rewardbench.analysis.stats import mean_interval, median, wilson_interval

GroupKey = tuple[str, ...]


@dataclass(frozen=True)
class SessionSummary:
    experiment_id: str
    session_id: str
    environment_id: str
    provider: str
    model_id: str
    feedback_condition: str
    split: str
    experiment_status: str
    validation_status: str
    synthetic: bool
    n_episodes: int
    n_scored_episodes: int
    n_selected_attempts: int
    n_invalid_selected: int
    invalid_rate: float | None
    n_crash_known: int
    n_crashed: int
    crash_rate: float | None
    n_success_known: int
    n_success: int
    success_rate: float | None
    initial_revision: int | None
    final_revision: int | None
    initial_mean_reward: float | None
    final_mean_reward: float | None
    improvement: float | None
    total_cost_usd: float
    total_tokens: int
    improvement_per_dollar: float | None
    total_elapsed_seconds: float
    reward_by_revision: tuple[tuple[int, float], ...]
    success_by_attempt: tuple[tuple[int, float], ...]
    cumulative_seconds_by_revision: tuple[tuple[int, float], ...]
    environment_config: str = "{}"
    episodes: tuple[EpisodeObservation, ...] = field(default=(), repr=False)
    attempts: tuple[AttemptObservation, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class GroupEstimate:
    """Descriptive estimates for one model, condition, and split.

    Field order is alphabetical by model id at the call site. There is no
    rank, winner, or significance flag.
    """

    model_id: str
    provider: str
    feedback_condition: str
    split: str
    environment_id: str
    validation_status: str
    n_sessions: int
    initial_reward: Interval
    final_reward: Interval
    improvement: Interval
    improvement_per_dollar: Interval
    invalid_rate: Interval
    crash_rate: Interval
    success_rate: Interval
    n_experiments: int
    environment_config: str = "{}"


@dataclass(frozen=True)
class TargetTime:
    target_reward: float
    session_id: str
    model_id: str
    provider: str
    feedback_condition: str
    split: str
    environment_id: str
    validation_status: str
    synthetic: bool
    reached: bool
    seconds: float | None
    observed_seconds: float
    environment_config: str = "{}"


def session_summaries(bundle: LogBundle) -> list[SessionSummary]:
    """One summary per session that has an attempt or an episode."""

    keys: set[tuple[str, str]] = set()
    for row in bundle.episodes:
        keys.add((row.experiment_id, row.session_id))
    for row in bundle.attempts:
        keys.add((row.experiment_id, row.session_id))
    summaries = [
        _summarize_session(
            [row for row in bundle.episodes if (row.experiment_id, row.session_id) == key],
            [row for row in bundle.attempts if (row.experiment_id, row.session_id) == key],
        )
        for key in keys
    ]
    return sorted(summaries, key=_session_sort)


def summarize_groups(
    summaries: list[SessionSummary],
    *,
    validation_status: str | None = None,
    confidence: float = 0.95,
) -> list[GroupEstimate]:
    """Mean and confidence interval of session-level metrics."""

    chosen = [
        summary
        for summary in summaries
        if validation_status is None or summary.validation_status == validation_status
    ]
    grouped: dict[GroupKey, list[SessionSummary]] = {}
    for summary in chosen:
        grouped.setdefault(_group_key(summary), []).append(summary)
    estimates = [
        _estimate_group(rows, confidence)
        for _, rows in sorted(grouped.items(), key=lambda item: item[0])
    ]
    return estimates


def experiment_rollups(summaries: list[SessionSummary]) -> list[SessionSummary]:
    """Collapse sessions that share an experiment id into one replicate.

    A resumed run opens another session for the same experiment. Rebuild all
    metrics from its observations, including revisions split across sessions.
    """

    grouped: dict[tuple[str, GroupKey], list[SessionSummary]] = {}
    for summary in summaries:
        grouped.setdefault((summary.experiment_id, _group_key(summary)), []).append(summary)
    rolled: list[SessionSummary] = []
    for rows in grouped.values():
        episodes = [episode for row in rows for episode in row.episodes]
        attempts = [attempt for row in rows for attempt in row.attempts]
        combined = _summarize_session(episodes, attempts)
        rolled.append(replace(combined, session_id=rows[-1].session_id))
    return sorted(rolled, key=_session_sort)


def time_to_targets(
    summaries: list[SessionSummary],
    targets: tuple[float, ...],
    *,
    validation_status: str | None = None,
) -> list[TargetTime]:
    """First cumulative time at which a session's revision mean reaches a target.

    Sessions that never reach the target stay in the result with ``reached``
    false. Their observed duration is not treated as a time-to-target.
    """

    results: list[TargetTime] = []
    for summary in summaries:
        if validation_status is not None and summary.validation_status != validation_status:
            continue
        cumulative = dict(summary.cumulative_seconds_by_revision)
        for target in targets:
            reached_at: float | None = None
            for revision, mean_reward in summary.reward_by_revision:
                if mean_reward >= target:
                    reached_at = cumulative[revision]
                    break
            results.append(
                TargetTime(
                    target_reward=target,
                    environment_config=summary.environment_config,
                    session_id=summary.session_id,
                    model_id=summary.model_id,
                    provider=summary.provider,
                    feedback_condition=summary.feedback_condition,
                    split=summary.split,
                    environment_id=summary.environment_id,
                    validation_status=summary.validation_status,
                    synthetic=summary.synthetic,
                    reached=reached_at is not None,
                    seconds=reached_at,
                    observed_seconds=summary.total_elapsed_seconds,
                )
            )
    return results


def reached_proportion(rows: list[TargetTime], confidence: float = 0.95) -> Interval:
    """Wilson interval for the share of sessions that reached a target."""

    if not rows:
        return Interval(None, None, None, 0, "no observations")
    successes = sum(1 for row in rows if row.reached)
    return wilson_interval(successes, len(rows), confidence)


def conditional_median_seconds(rows: list[TargetTime]) -> float | None:
    """Median time among sessions that reached the target."""

    return median([row.seconds for row in rows if row.reached and row.seconds is not None])


def _summarize_session(
    episodes: list[EpisodeObservation],
    attempts: list[AttemptObservation],
) -> SessionSummary:
    source = episodes[0] if episodes else attempts[0]
    scored: dict[int, list[float]] = {}
    elapsed_by_revision: dict[int, float] = {}
    success_by_attempt: dict[int, list[float]] = {}
    crash_known = 0
    crashed = 0
    success_known = 0
    successes = 0
    ordered_episodes = sorted(episodes, key=lambda row: (row.revision_index, row.episode_index))
    for ordinal, episode in enumerate(ordered_episodes):
        elapsed_by_revision[episode.revision_index] = (
            elapsed_by_revision.get(episode.revision_index, 0.0) + episode.elapsed_seconds
        )
        if episode.total_reward is not None and episode.error is None:
            scored.setdefault(episode.revision_index, []).append(episode.total_reward)
        if episode.success is not None and episode.error is None:
            success_known += 1
            if episode.success:
                successes += 1
            success_by_attempt.setdefault(ordinal, []).append(
                1.0 if episode.success else 0.0
            )
        if episode.crashed is not None and episode.error is None:
            crash_known += 1
            if episode.crashed:
                crashed += 1
    latency_by_revision: dict[int, float] = {}
    cost = 0.0
    tokens = 0
    selected = 0
    invalid_selected = 0
    for attempt in attempts:
        cost += attempt.estimated_cost_usd
        tokens += attempt.total_tokens
        latency_by_revision[attempt.revision_index] = (
            latency_by_revision.get(attempt.revision_index, 0.0) + attempt.latency_seconds
        )
        if attempt.selected:
            selected += 1
            if not attempt.valid:
                invalid_selected += 1
    reward_by_revision = tuple(
        (revision, sum(values) / len(values)) for revision, values in sorted(scored.items())
    )
    revisions = sorted(set(elapsed_by_revision) | set(latency_by_revision) | set(scored))
    cumulative: list[tuple[int, float]] = []
    running = 0.0
    for revision in revisions:
        running += elapsed_by_revision.get(revision, 0.0) + latency_by_revision.get(revision, 0.0)
        cumulative.append((revision, running))
    initial_revision = reward_by_revision[0][0] if reward_by_revision else None
    final_revision = reward_by_revision[-1][0] if reward_by_revision else None
    initial_mean = reward_by_revision[0][1] if reward_by_revision else None
    final_mean = reward_by_revision[-1][1] if reward_by_revision else None
    improvement = None if initial_mean is None or final_mean is None else final_mean - initial_mean
    per_dollar = None if improvement is None or cost <= 0.0 else improvement / cost
    return SessionSummary(
        experiment_id=source.experiment_id,
        environment_config=source.environment_config,
        episodes=tuple(episodes),
        attempts=tuple(attempts),
        session_id=source.session_id,
        environment_id=source.environment_id,
        provider=source.provider,
        model_id=source.model_id,
        feedback_condition=source.feedback_condition,
        split=source.split,
        experiment_status=source.experiment_status,
        validation_status=source.validation_status,
        synthetic=source.synthetic,
        n_episodes=len(episodes),
        n_scored_episodes=sum(len(values) for values in scored.values()),
        n_selected_attempts=selected,
        n_invalid_selected=invalid_selected,
        invalid_rate=None if selected == 0 else invalid_selected / selected,
        n_crash_known=crash_known,
        n_crashed=crashed,
        crash_rate=None if crash_known == 0 else crashed / crash_known,
        n_success_known=success_known,
        n_success=successes,
        success_rate=None if success_known == 0 else successes / success_known,
        initial_revision=initial_revision,
        final_revision=final_revision,
        initial_mean_reward=initial_mean,
        final_mean_reward=final_mean,
        improvement=improvement,
        total_cost_usd=cost,
        total_tokens=tokens,
        improvement_per_dollar=per_dollar,
        total_elapsed_seconds=cumulative[-1][1] if cumulative else 0.0,
        reward_by_revision=reward_by_revision,
        success_by_attempt=tuple(
            (attempt, sum(values) / len(values))
            for attempt, values in sorted(success_by_attempt.items())
        ),
        cumulative_seconds_by_revision=tuple(cumulative),
    )


def _estimate_group(rows: list[SessionSummary], confidence: float) -> GroupEstimate:
    sample = rows[0]
    return GroupEstimate(
        model_id=sample.model_id,
        environment_config=sample.environment_config,
        provider=sample.provider,
        feedback_condition=sample.feedback_condition,
        split=sample.split,
        environment_id=sample.environment_id,
        validation_status=sample.validation_status,
        n_sessions=len(rows),
        n_experiments=len({row.experiment_id for row in rows}),
        initial_reward=mean_interval([row.initial_mean_reward for row in rows], confidence),
        final_reward=mean_interval([row.final_mean_reward for row in rows], confidence),
        improvement=mean_interval([row.improvement for row in rows], confidence),
        improvement_per_dollar=mean_interval(
            [row.improvement_per_dollar for row in rows],
            confidence,
        ),
        invalid_rate=mean_interval([row.invalid_rate for row in rows], confidence),
        crash_rate=mean_interval([row.crash_rate for row in rows], confidence),
        success_rate=mean_interval([row.success_rate for row in rows], confidence),
    )


def _group_key(summary: SessionSummary) -> GroupKey:
    return (
        summary.environment_id,
        summary.environment_config,
        summary.validation_status,
        summary.split,
        summary.feedback_condition,
        summary.provider,
        summary.model_id.lower(),
    )


def _session_sort(summary: SessionSummary) -> tuple[str, str, str, str, str]:
    return (
        summary.model_id.lower(),
        summary.feedback_condition,
        summary.split,
        summary.experiment_id,
        summary.session_id,
    )
