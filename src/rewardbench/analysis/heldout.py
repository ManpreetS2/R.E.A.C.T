"""Read-only sealed held-out summaries for experiment reports.

Queries ``frozen_controllers``, ``heldout_evaluations``, and ``heldout_episodes``
when present. Does not call a model and does not pool environment families.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from rewardbench.analysis.environments import environment_family, family_display, provider_label


@dataclass(frozen=True)
class HeldOutEvaluationSummary:
    """One sealed held-out evaluation already stored in SQLite."""

    evaluation_id: str
    freeze_id: str
    source_experiment_id: str
    controller_hash: str
    feedback_condition: str
    environment_id: str
    environment_family: str
    status: str
    episode_count: int
    landing_rate: float | None
    mean_reward: float | None
    crash_rate: float | None
    timeout_rate: float | None
    replay_paths: tuple[str, ...]
    start_schedule_version: str
    environment_version: str
    provider: str = "unrecorded"
    model_id: str = "unrecorded"
    vary_fuel: bool | None = None
    max_episode_steps: int | None = None


def load_heldout_summaries(path: str | Path) -> tuple[HeldOutEvaluationSummary, ...]:
    """Return sealed held-out summaries from a SQLite log, or ``()`` if absent."""

    source = Path(path)
    if source.suffix.lower() not in {".sqlite", ".sqlite3", ".db"}:
        return ()
    if not source.is_file():
        return ()
    connection = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        required = {"frozen_controllers", "heldout_evaluations", "heldout_episodes"}
        if not required.issubset(tables):
            return ()
        rows = connection.execute(
            """
            SELECT
                e.evaluation_id,
                e.freeze_id,
                e.source_experiment_id,
                e.controller_hash,
                e.environment_id,
                e.environment_version,
                e.start_schedule_version,
                e.vary_fuel,
                e.max_episode_steps,
                f.provider,
                f.model_id,
                e.status,
                f.feedback_condition
            FROM heldout_evaluations AS e
            JOIN frozen_controllers AS f ON f.freeze_id = e.freeze_id
            ORDER BY e.created_at, e.evaluation_id
            """
        ).fetchall()
        summaries: list[HeldOutEvaluationSummary] = []
        for row in rows:
            episodes = connection.execute(
                """
                SELECT total_reward, success, crashed, truncated, replay_path
                FROM heldout_episodes
                WHERE evaluation_id = ?
                ORDER BY episode_index
                """,
                (row["evaluation_id"],),
            ).fetchall()
            summaries.append(_summarize(row, episodes))
        return tuple(summaries)
    finally:
        connection.close()


def heldout_markdown(summaries: tuple[HeldOutEvaluationSummary, ...]) -> list[str]:
    """Markdown section for sealed held-out evaluations."""

    lines = [
        "## Sealed held-out evaluations",
        "",
        "These rows come from `python -m rewardbench.heldout` after a completed",
        "development experiment. Selection uses a frozen controller",
        "(`last_valid_selected`); held-out rewards are never used to choose the",
        "controller and must not enter model prompts.",
        "",
        "Engineering-demo sealed scores are **not** a pre-registered final",
        "research evaluation. See `docs/FINAL_EVALUATION_PROTOCOL.md`.",
        "",
    ]
    if not summaries:
        lines.extend(
            [
                "No `heldout_evaluations` / `heldout_episodes` tables (or rows) were found in this log.",
                "",
            ]
        )
        return lines

    if any(item.provider.lower() == "mock" for item in summaries):
        lines.extend(["> Provider `mock` rows are scripted infrastructure checks, not LLM results.", ""])
    families = sorted({item.environment_family for item in summaries})
    for family in families:
        family_rows = [item for item in summaries if item.environment_family == family]
        lines.append(f"### {family_display(family)}")
        lines.append("")
        lines.append(
            "| Evaluation | Source experiment | Provider | Model | Feedback | Controller hash | Episodes | "
            "Land rate | Mean reward | Crash rate | Timeout rate | Status |"
        )
        lines.append("| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |")
        for item in family_rows:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{item.evaluation_id}`",
                        f"`{item.source_experiment_id}`",
                        provider_label(item.provider),
                        item.model_id,
                        item.feedback_condition,
                        f"`{item.controller_hash[:12]}…`",
                        str(item.episode_count),
                        _fmt_rate(item.landing_rate),
                        _fmt_reward(item.mean_reward),
                        _fmt_rate(item.crash_rate),
                        _fmt_rate(item.timeout_rate),
                        item.status,
                    ]
                )
                + " |"
            )
        lines.append("")
        for item in family_rows:
            replays = ", ".join(f"`{path}`" for path in item.replay_paths[:5]) or "(none recorded)"
            if len(item.replay_paths) > 5:
                replays += f", … (+{len(item.replay_paths) - 5})"
            lines.extend(
                [
                    f"- `{item.evaluation_id}` freeze `{item.freeze_id}` · "
                    f"schedule `{item.start_schedule_version}` · "
                    f"env `{item.environment_version}` · "
                    f"vary_fuel `{item.vary_fuel}` · "
                    f"max_episode_steps `{item.max_episode_steps}` · "
                    f"replay: {replays}",
                ]
            )
        lines.append("")
    return lines


def _summarize(row: sqlite3.Row, episodes: list[sqlite3.Row]) -> HeldOutEvaluationSummary:
    n = len(episodes)
    rewards = [float(ep["total_reward"]) for ep in episodes if ep["total_reward"] is not None]
    landings = sum(1 for ep in episodes if ep["success"] == 1)
    crashes = sum(1 for ep in episodes if ep["crashed"] == 1)
    timeouts = sum(
        1
        for ep in episodes
        if ep["truncated"] == 1 and ep["success"] != 1 and ep["crashed"] != 1
    )
    replays = tuple(
        str(ep["replay_path"])
        for ep in episodes
        if ep["replay_path"] not in (None, "")
    )
    env_id = str(row["environment_id"])
    return HeldOutEvaluationSummary(
        evaluation_id=str(row["evaluation_id"]),
        freeze_id=str(row["freeze_id"]),
        source_experiment_id=str(row["source_experiment_id"]),
        controller_hash=str(row["controller_hash"]),
        feedback_condition=str(row["feedback_condition"]),
        environment_id=env_id,
        environment_family=environment_family(env_id),
        status=str(row["status"]),
        episode_count=n,
        landing_rate=(landings / n) if n else None,
        mean_reward=(sum(rewards) / len(rewards)) if rewards else None,
        crash_rate=(crashes / n) if n else None,
        timeout_rate=(timeouts / n) if n else None,
        replay_paths=replays,
        start_schedule_version=str(row["start_schedule_version"]),
        environment_version=str(row["environment_version"]),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        vary_fuel=bool(row["vary_fuel"]),
        max_episode_steps=row["max_episode_steps"],
    )


def _fmt_rate(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.3f}"


def _fmt_reward(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"
