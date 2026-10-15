"""Checks that log rows are usable before they enter a summary."""

from __future__ import annotations

import math

from rewardbench.analysis.schema import (
    FEEDBACK_CONDITIONS,
    INDEPENDENTLY_VALIDATED,
    SPLITS,
    AttemptObservation,
    EpisodeObservation,
    LogBundle,
    LogRejected,
    ValidationIssue,
)


def validate_bundle(bundle: LogBundle) -> LogBundle:
    """Return a bundle that keeps only rows safe to summarize.

    Rejected rows stay out of the lists and are described in ``issues``.
    A mix of synthetic and non-synthetic rows is refused entirely.
    """

    issues = list(bundle.issues)
    episodes: list[EpisodeObservation] = []
    seen_episodes: set[tuple[str, int, int]] = set()
    for episode in bundle.episodes:
        row_issues = _episode_issues(episode)
        if row_issues:
            issues.extend(row_issues)
            continue
        key = (episode.experiment_id, episode.revision_index, episode.episode_index)
        if key in seen_episodes:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_episode",
                    "duplicate episode key "
                    f"{episode.experiment_id} revision {episode.revision_index} "
                    f"episode {episode.episode_index}",
                    episode.experiment_id,
                    episode.session_id,
                )
            )
            continue
        seen_episodes.add(key)
        episodes.append(episode)

    attempts: list[AttemptObservation] = []
    seen_attempts: set[tuple[str, int, int]] = set()
    for attempt in bundle.attempts:
        row_issues = _attempt_issues(attempt)
        if row_issues:
            issues.extend(row_issues)
            continue
        key = (attempt.experiment_id, attempt.revision_index, attempt.call_index)
        if key in seen_attempts:
            issues.append(
                ValidationIssue(
                    "error",
                    "duplicate_attempt",
                    "duplicate attempt key "
                    f"{attempt.experiment_id} revision {attempt.revision_index} "
                    f"call {attempt.call_index}",
                    attempt.experiment_id,
                    attempt.session_id,
                )
            )
            continue
        seen_attempts.add(key)
        attempts.append(attempt)

    cleaned = LogBundle(
        episodes=episodes,
        attempts=attempts,
        errors=list(bundle.errors),
        issues=issues,
        source=bundle.source,
        sha256=bundle.sha256,
        schema_version=bundle.schema_version,
        source_format=bundle.source_format,
        load_warnings=list(bundle.load_warnings),
    )
    _reject_incoherent(cleaned)
    return cleaned


def _reject_incoherent(bundle: LogBundle) -> None:
    flags = [row.synthetic for row in bundle.episodes]
    flags.extend(row.synthetic for row in bundle.attempts)
    if any(flags) and not all(flags):
        raise LogRejected(
            "log mixes synthetic fixture rows with non-synthetic rows; "
            "it was not summarized"
        )
    if bundle.synthetic:
        for row in (*bundle.episodes, *bundle.attempts):
            if row.validation_status == INDEPENDENTLY_VALIDATED:
                raise LogRejected(
                    "a synthetic fixture cannot be marked independently validated"
                )


def _episode_issues(episode: EpisodeObservation) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _common(issues, episode.feedback_condition, episode.split, episode.validation_status, episode)
    if episode.revision_index < 0 or episode.episode_index < 0:
        issues.append(_error(episode, "bad_index", "revision and episode indexes must be >= 0"))
    if episode.total_reward is not None and not math.isfinite(episode.total_reward):
        issues.append(_error(episode, "non_finite_reward", "total_reward must be finite or null"))
    if episode.elapsed_seconds < 0 or not math.isfinite(episode.elapsed_seconds):
        issues.append(_error(episode, "bad_elapsed", "elapsed_seconds must be finite and >= 0"))
    if episode.steps < 0:
        issues.append(_error(episode, "bad_steps", "steps must be >= 0"))
    if episode.success is True and episode.crashed is True:
        issues.append(
            _error(episode, "success_and_crash", "an episode cannot be both success and crashed")
        )
    return issues


def _attempt_issues(attempt: AttemptObservation) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _common(issues, attempt.feedback_condition, attempt.split, attempt.validation_status, attempt)
    if attempt.revision_index < 0 or attempt.call_index < 0:
        issues.append(_error(attempt, "bad_index", "revision and call indexes must be >= 0"))
    if attempt.estimated_cost_usd < 0 or not math.isfinite(attempt.estimated_cost_usd):
        issues.append(_error(attempt, "bad_cost", "estimated_cost_usd must be finite and >= 0"))
    if attempt.latency_seconds < 0 or not math.isfinite(attempt.latency_seconds):
        issues.append(_error(attempt, "bad_latency", "latency_seconds must be finite and >= 0"))
    for name, value in (
        ("prompt_tokens", attempt.prompt_tokens),
        ("completion_tokens", attempt.completion_tokens),
        ("reasoning_tokens", attempt.reasoning_tokens),
        ("total_tokens", attempt.total_tokens),
    ):
        if value < 0:
            issues.append(_error(attempt, "bad_tokens", f"{name} must be >= 0"))
    if not attempt.valid and attempt.selected and attempt.validation_error is None and attempt.error is None:
        issues.append(
            ValidationIssue(
                "warning",
                "invalid_without_reason",
                "selected invalid controller has no validation_error",
                attempt.experiment_id,
                attempt.session_id,
            )
        )
    return issues


def _common(
    issues: list[ValidationIssue],
    condition: str,
    split: str,
    status: str,
    row: EpisodeObservation | AttemptObservation,
) -> None:
    if condition not in FEEDBACK_CONDITIONS:
        issues.append(_error(row, "bad_condition", f"unknown feedback_condition {condition!r}"))
    if split not in SPLITS:
        issues.append(_error(row, "bad_split", f"unknown split {split!r}"))
    if status not in {"preliminary", "independently_validated"}:
        issues.append(_error(row, "bad_status", f"unknown validation_status {status!r}"))


def _error(row: EpisodeObservation | AttemptObservation, code: str, message: str) -> ValidationIssue:
    return ValidationIssue("error", code, message, row.experiment_id, row.session_id)
