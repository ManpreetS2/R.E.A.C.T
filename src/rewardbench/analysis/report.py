"""Markdown experiment report generated only from a loaded log."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from rewardbench.analysis.diagnostics import fairness_notes, resume_notes, seed_leakage
from rewardbench.analysis.plots import (
    plot_improvement_per_dollar,
    plot_initial_vs_final,
    plot_invalid_and_crash_rates,
    plot_landing_success_vs_attempt,
    plot_reward_vs_revision,
    plot_time_to_target,
)
from rewardbench.analysis.schema import (
    INDEPENDENTLY_VALIDATED,
    PRELIMINARY,
    SYNTHETIC_BANNER,
    LogBundle,
)
from rewardbench.analysis.sessions import (
    GroupEstimate,
    SessionSummary,
    conditional_median_seconds,
    reached_proportion,
    session_summaries,
    summarize_groups,
    time_to_targets,
)
from rewardbench.analysis.stats import Interval

BANNED_CLAIMS = (
    "best model",
    "winner",
    "outperforms",
    "state of the art",
    "state-of-the-art",
)


@dataclass(frozen=True)
class ReportResult:
    markdown_path: Path
    plot_paths: tuple[Path, ...]


def write_report(
    bundle: LogBundle,
    output_directory: str | Path,
    *,
    confidence: float = 0.95,
    reward_targets: tuple[float, ...] = (200.0,),
) -> ReportResult:
    """Write ``report.md`` and the standard figures.

    Preliminary and independently validated rows are written in separate
    sections and never pooled. An empty log produces a report that states
    that no results are available.
    """

    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=True)
    summaries = session_summaries(bundle)
    lines = _header(bundle)
    if bundle.synthetic:
        lines.extend(
            [
                f"> {SYNTHETIC_BANNER}",
                ">",
                "> These rows are fixtures for tests or examples of the file format.",
                "> They are not experimental results and this report does not rank models.",
                "",
            ]
        )
    if bundle.empty:
        lines.extend(
            [
                "No experiment logs were loaded. There are no model comparisons,",
                "learning curves, or performance claims in this report.",
                "",
            ]
        )
    else:
        lines.append(
            "Estimates are descriptive session-level summaries. "
            "This report does not rank models."
        )
        lines.append("")
    lines.extend(_validation_section(bundle))
    lines.extend(_diagnostic_section(bundle, summaries))
    plot_paths: list[Path] = []
    for status in (INDEPENDENTLY_VALIDATED, PRELIMINARY):
        status_summaries = [row for row in summaries if row.validation_status == status]
        if not status_summaries:
            continue
        lines.extend(_status_section(status, status_summaries, confidence, reward_targets))
        plot_dir = directory / status
        plot_paths.extend(_plots(status_summaries, plot_dir, confidence, reward_targets))
        lines.extend(_plot_links(plot_dir, directory))
    if not any(row.validation_status == INDEPENDENTLY_VALIDATED for row in summaries):
        lines.extend(
            [
                "## Independently validated results",
                "",
                "No independently validated results are present.",
                "Do not cite this report as evidence that one model adapts more effectively.",
                "",
            ]
        )
    lines.extend(_reading_notes(reward_targets))
    text = "\n".join(lines).rstrip() + "\n"
    lowered = text.lower()
    for phrase in BANNED_CLAIMS:
        if phrase in lowered:
            raise RuntimeError(f"report text contained a ranking phrase: {phrase}")
    markdown = directory / "report.md"
    markdown.write_text(text, encoding="utf-8", newline="\n")
    return ReportResult(markdown, tuple(plot_paths))


def _header(bundle: LogBundle) -> list[str]:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return [
        "# RewardBench experiment report",
        "",
        f"- Log: `{bundle.source}`",
        f"- SHA-256: `{bundle.sha256}`",
        f"- Format: {bundle.source_format}",
        f"- Schema version: {bundle.schema_version if bundle.schema_version is not None else 'not recorded'}",
        f"- Generated (UTC): {generated}",
        f"- Python packages: numpy { _pkg('numpy') }, scipy { _pkg('scipy') }, matplotlib { _pkg('matplotlib') }",
        "",
        "Adaptation in this benchmark is in-context. The log does not record weight updates.",
        "",
    ]


def _validation_section(bundle: LogBundle) -> list[str]:
    lines = ["## Data checks", ""]
    if bundle.load_warnings:
        lines.append("Load warnings:")
        lines.append("")
        for warning in bundle.load_warnings:
            lines.append(f"- {warning}")
        lines.append("")
    errors = [issue for issue in bundle.issues if issue.level == "error"]
    warnings = [issue for issue in bundle.issues if issue.level == "warning"]
    lines.append(f"Rows excluded by validation: {len(errors)}.")
    lines.append(f"Validation warnings: {len(warnings)}.")
    lines.append(f"Stored error rows: {len(bundle.errors)}.")
    lines.append("")
    for issue in bundle.issues[:20]:
        where = issue.experiment_id or "log"
        lines.append(f"- {issue.level} `{issue.code}` ({where}): {issue.message}")
    if len(bundle.issues) > 20:
        lines.append(f"- {len(bundle.issues) - 20} additional issues omitted")
    lines.append("")
    return lines


def _diagnostic_section(bundle: LogBundle, summaries: list[SessionSummary]) -> list[str]:
    lines = ["## Diagnostics", ""]
    leakage = seed_leakage(bundle)
    if leakage:
        lines.append("Seed overlap:")
        lines.append("")
        for finding in leakage:
            seeds = ", ".join(str(seed) for seed in finding.seeds)
            lines.append(f"- {finding.kind}: {finding.message} (seeds: {seeds})")
        lines.append("")
    else:
        lines.append("No development/held-out seed overlap was detected in this log.")
        lines.append("")
    resumes = resume_notes(summaries)
    if resumes:
        lines.append("Resumed experiments:")
        lines.append("")
        for note in resumes:
            lines.append(f"- {note}")
        lines.append("")
    notes = fairness_notes(summaries)
    if notes:
        lines.append("Exposure check (not a performance comparison):")
        lines.append("")
        for note in notes:
            lines.append(
                f"- {note.environment_id}, {note.feedback_condition}, {note.split}: {note.message}"
            )
        lines.append("")
    lines.append(
        "Landing success in the current environment is the simulator's own flag. "
        "It is not a language-model judge score. A future Minecraft judge would "
        "need a separate bias check before those scores were treated as outcomes."
    )
    lines.append("")
    return lines


def _status_section(
    status: str,
    summaries: list[SessionSummary],
    confidence: float,
    targets: tuple[float, ...],
) -> list[str]:
    title = (
        "Independently validated logs"
        if status == INDEPENDENTLY_VALIDATED
        else "Preliminary logs"
    )
    lines = [f"## {title}", ""]
    if status == PRELIMINARY:
        lines.append(
            "These records have not been marked independently validated. "
            "Keep them separate from any later confirmed results."
        )
        lines.append("")
    if not summaries:
        lines.append("No sessions in this category.")
        lines.append("")
        return lines
    lines.append(
        f"Session-level {confidence * 100:g}% confidence intervals use the Student-t "
        "interval for means. Bounds are omitted when fewer than two sessions contribute."
    )
    lines.append("")
    lines.extend(_session_table(summaries))
    lines.extend(_group_table(summarize_groups(summaries, validation_status=status, confidence=confidence)))
    lines.extend(_target_table(summaries, targets, status, confidence))
    return lines


def _session_table(summaries: list[SessionSummary]) -> list[str]:
    lines = [
        "| Model | Condition | Split | Session | Status | Initial | Final | Improvement | Cost USD | Per dollar | Invalid rate | Crash rate |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for summary in summaries:
        lines.append(
            "| "
            + " | ".join(
                [
                    summary.model_id,
                    summary.feedback_condition,
                    summary.split,
                    summary.session_id,
                    summary.experiment_status,
                    _fmt(summary.initial_mean_reward),
                    _fmt(summary.final_mean_reward),
                    _fmt(summary.improvement),
                    _fmt(summary.total_cost_usd),
                    _fmt(summary.improvement_per_dollar),
                    _fmt(summary.invalid_rate),
                    _fmt(summary.crash_rate),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("Rows are sorted by model id, condition, split, and session id.")
    lines.append("")
    return lines


def _group_table(estimates: list[GroupEstimate]) -> list[str]:
    lines = [
        "| Model | Condition | Split | Sessions | Mean improvement | Interval | Mean per dollar | Interval |",
        "| --- | --- | --- | ---: | ---: | --- | ---: | --- |",
    ]
    for estimate in estimates:
        lines.append(
            "| {model} | {condition} | {split} | {n} | {improvement} | {improvement_ci} | {per_dollar} | {per_dollar_ci} |".format(
                model=estimate.model_id,
                condition=estimate.feedback_condition,
                split=estimate.split,
                n=estimate.n_sessions,
                improvement=_fmt(estimate.improvement.point),
                improvement_ci=_interval(estimate.improvement),
                per_dollar=_fmt(estimate.improvement_per_dollar.point),
                per_dollar_ci=_interval(estimate.improvement_per_dollar),
            )
        )
    lines.append("")
    return lines


def _target_table(
    summaries: list[SessionSummary],
    targets: tuple[float, ...],
    status: str,
    confidence: float,
) -> list[str]:
    lines = [
        "Time to a reward target counts a session only when its revision mean reaches the target.",
        "The median is conditional on reaching it. Sessions that never reach it stay in the proportion.",
        "",
    ]
    rows = time_to_targets(summaries, targets, validation_status=status)
    lines.append("| Target | Model | Condition | Split | Reached | Sessions | Wilson interval | Median seconds if reached |")
    lines.append("| ---: | --- | --- | --- | ---: | ---: | --- | ---: |")
    grouped: dict[tuple[float, str, str, str], list] = {}
    for row in rows:
        grouped.setdefault(
            (row.target_reward, row.model_id, row.feedback_condition, row.split),
            [],
        ).append(row)
    for key in sorted(grouped):
        sample = grouped[key]
        proportion = reached_proportion(sample, confidence)
        lines.append(
            "| {target:g} | {model} | {condition} | {split} | {reached} | {n} | {interval} | {median} |".format(
                target=key[0],
                model=key[1],
                condition=key[2],
                split=key[3],
                reached=sum(1 for row in sample if row.reached),
                n=len(sample),
                interval=_interval(proportion),
                median=_fmt(conditional_median_seconds(sample)),
            )
        )
    lines.append("")
    return lines


def _plots(
    summaries: list[SessionSummary],
    directory: Path,
    confidence: float,
    targets: tuple[float, ...],
) -> list[Path]:
    paths = [
        plot_reward_vs_revision(summaries, directory / "reward_vs_revision.png", confidence=confidence),
        plot_landing_success_vs_attempt(
            summaries,
            directory / "landing_success_vs_attempt.png",
            confidence=confidence,
        ),
        plot_initial_vs_final(summaries, directory / "initial_vs_final.png"),
        plot_improvement_per_dollar(
            summaries,
            directory / "improvement_per_dollar.png",
            confidence=confidence,
        ),
        plot_invalid_and_crash_rates(
            summaries,
            directory / "invalid_and_crash_rates.png",
            confidence=confidence,
        ),
    ]
    target = targets[0]
    target_rows = [
        row
        for row in time_to_targets(summaries, (target,))
        if row.validation_status == summaries[0].validation_status
    ]
    paths.append(plot_time_to_target(target_rows, directory / "time_to_target.png", target=target))
    return paths


def _plot_links(plot_dir: Path, report_dir: Path) -> list[str]:
    lines = ["Figures:", ""]
    for name in (
        "reward_vs_revision.png",
        "landing_success_vs_attempt.png",
        "initial_vs_final.png",
        "improvement_per_dollar.png",
        "time_to_target.png",
        "invalid_and_crash_rates.png",
    ):
        relative = (plot_dir / name).relative_to(report_dir).as_posix()
        lines.append(f"![{name}]({relative})")
        lines.append("")
    return lines


def _reading_notes(targets: tuple[float, ...]) -> list[str]:
    rendered = ", ".join(f"{target:g}" for target in targets)
    return [
        "## How to read the curves",
        "",
        "- Reward versus revision uses the environment reward. Negative values are penalties.",
        "- A rising curve is a within-session change. It is not, by itself, evidence that one model is better than another.",
        "- Compare the numerical-reward condition with the no-feedback condition before comparing models.",
        "- Landing success uses the episode index. Controller revision is a different axis.",
        "- Improvement per dollar is undefined when the recorded cost is zero.",
        f"- Time-to-target uses caller-supplied reward thresholds ({rendered}), not a threshold discovered from the data.",
        "- Development logs and held-out logs stay in separate rows because they are different experiments.",
        "",
        "See `docs/LIMITATIONS.md` before quoting any number.",
        "",
    ]


def _interval(interval: Interval) -> str:
    if interval.low is None or interval.high is None:
        if interval.n < 2:
            return f"undefined (n={interval.n})"
        return "undefined"
    return f"[{_fmt(interval.low)}, {_fmt(interval.high)}]"


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4g}"


def _pkg(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "not installed"
