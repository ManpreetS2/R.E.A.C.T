"""Diagnostics that qualify a comparison without ranking models."""

from __future__ import annotations

from dataclasses import dataclass

from rewardbench.analysis.schema import LogBundle
from rewardbench.analysis.sessions import SessionSummary


@dataclass(frozen=True)
class SeedFinding:
    kind: str
    message: str
    seeds: tuple[int, ...]


@dataclass(frozen=True)
class FairnessNote:
    environment_id: str
    split: str
    feedback_condition: str
    validation_status: str
    message: str


def seed_leakage(bundle: LogBundle) -> list[SeedFinding]:
    """Flag seed overlap between development and held-out logs.

    Configured pools are read from each experiment's stored config. Executed
    episode seeds are compared with every held-out pool in the same log.
    """

    experiments: dict[str, tuple[str, tuple[int, ...], tuple[int, ...]]] = {}
    executed: dict[str, set[int]] = {}
    for episode in bundle.episodes:
        experiments.setdefault(
            episode.experiment_id,
            (episode.split, episode.development_seeds, episode.held_out_seeds),
        )
        executed.setdefault(episode.experiment_id, set()).add(episode.episode_seed)
    findings: list[SeedFinding] = []
    for experiment_id, (split, development, held_out) in sorted(experiments.items()):
        overlap = tuple(sorted(set(development) & set(held_out)))
        if overlap:
            findings.append(
                SeedFinding(
                    "configured_pool_overlap",
                    f"{experiment_id} ({split}) stores overlapping development and held-out seeds",
                    overlap,
                )
            )
    held_out_pools = {
        experiment_id: set(held_out)
        for experiment_id, (split, _, held_out) in experiments.items()
        if split == "held_out" and held_out
    }
    for experiment_id, (split, _, _) in sorted(experiments.items()):
        if split != "development":
            continue
        used = executed.get(experiment_id, set())
        for held_id, pool in sorted(held_out_pools.items()):
            leaked = tuple(sorted(used & pool))
            if leaked:
                findings.append(
                    SeedFinding(
                        "executed_development_seed_in_held_out_pool",
                        f"development experiment {experiment_id} executed seeds reserved by {held_id}",
                        leaked,
                    )
                )
    return findings


def resume_notes(summaries: list[SessionSummary]) -> list[str]:
    """Warn when several sessions share one experiment id.

    A resumed run opens a new session for the same experiment. Those sessions
    are not independent replicates, so a confidence interval across them
    overstates the evidence.
    """

    grouped: dict[str, list[str]] = {}
    for summary in summaries:
        grouped.setdefault(summary.experiment_id, []).append(summary.session_id)
    notes = []
    for experiment_id, session_ids in sorted(grouped.items()):
        if len(session_ids) > 1:
            notes.append(
                f"{experiment_id} has {len(session_ids)} sessions "
                f"({', '.join(sorted(session_ids))}). Treat them as one resumed run, "
                "not as independent replicates."
            )
    return notes


def fairness_notes(summaries: list[SessionSummary]) -> list[FairnessNote]:
    """Describe unequal exposure inside a condition and split.

    Notes are alphabetical by model id. They do not say which model adapted
    more successfully.
    """

    cells: dict[tuple[str, str, str, str], list[SessionSummary]] = {}
    for summary in summaries:
        key = (
            summary.environment_id,
            summary.split,
            summary.feedback_condition,
            summary.validation_status,
        )
        cells.setdefault(key, []).append(summary)
    notes: list[FairnessNote] = []
    for key, rows in sorted(cells.items()):
        by_model: dict[str, list[SessionSummary]] = {}
        for row in rows:
            by_model.setdefault(row.model_id, []).append(row)
        if len(by_model) < 2:
            continue
        environment_id, split, condition, status = key
        revisions = {
            model: _mean(row.final_revision for row in model_rows)
            for model, model_rows in by_model.items()
        }
        costs = {
            model: _mean(row.total_cost_usd for row in model_rows)
            for model, model_rows in by_model.items()
        }
        tokens = {
            model: _mean(float(row.total_tokens) for row in model_rows)
            for model, model_rows in by_model.items()
        }
        episodes = {
            model: _mean(float(row.n_scored_episodes) for row in model_rows)
            for model, model_rows in by_model.items()
        }
        pieces = []
        if _spread(revisions) > 0:
            pieces.append("selected revision counts differ across models")
        if _relative_spread(costs) > 0.25:
            pieces.append("mean session cost differs by more than 25%")
        if _relative_spread(tokens) > 0.25:
            pieces.append("mean token counts differ by more than 25%")
        if _relative_spread(episodes) > 0.25:
            pieces.append("mean scored-episode counts differ by more than 25%")
        if not pieces:
            pieces.append("session budgets are within the 25% exposure check")
        ordered = ", ".join(sorted(by_model))
        notes.append(
            FairnessNote(
                environment_id=environment_id,
                split=split,
                feedback_condition=condition,
                validation_status=status,
                message=f"Models in alphabetical order ({ordered}): " + "; ".join(pieces) + ".",
            )
        )
    return notes


def _mean(values: object) -> float:
    sample = [float(value) for value in values if value is not None]  # type: ignore[union-attr]
    if not sample:
        return 0.0
    return sum(sample) / len(sample)


def _spread(values: dict[str, float]) -> float:
    if not values:
        return 0.0
    return max(values.values()) - min(values.values())


def _relative_spread(values: dict[str, float]) -> float:
    if not values:
        return 0.0
    low = min(values.values())
    high = max(values.values())
    if high == 0.0:
        return 0.0
    if low <= 0.0:
        return 1.0
    return (high - low) / low
