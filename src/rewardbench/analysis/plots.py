"""Publication figures for RewardBench logs.

Model order is alphabetical. Axis titles name the metric. Empty logs produce
an explicit empty figure. Synthetic sessions are labeled on the figure.
"""

from __future__ import annotations

import textwrap

from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from rewardbench.analysis.environments import config_label, environment_family, family_display, provider_label
from rewardbench.analysis.schema import EMPTY_LOG_MESSAGE, SYNTHETIC_BANNER
from rewardbench.analysis.sessions import SessionSummary, TargetTime
from rewardbench.analysis.stats import mean_interval

OKABE_ITO = (
    "#000000",
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
)

CONDITION_LINESTYLE = {
    "numerical_reward": "solid",
    "no_feedback": "dashed",
}


def plot_reward_vs_revision(
    summaries: list[SessionSummary],
    path: str | Path,
    *,
    confidence: float = 0.95,
) -> Path:
    return _save(draw_reward_vs_revision(summaries, confidence=confidence), path)


def plot_landing_success_vs_attempt(
    summaries: list[SessionSummary],
    path: str | Path,
    *,
    confidence: float = 0.95,
) -> Path:
    return _save(draw_landing_success_vs_attempt(summaries, confidence=confidence), path)


def plot_initial_vs_final(summaries: list[SessionSummary], path: str | Path) -> Path:
    return _save(draw_initial_vs_final(summaries), path)


def plot_improvement_per_dollar(
    summaries: list[SessionSummary],
    path: str | Path,
    *,
    confidence: float = 0.95,
) -> Path:
    return _save(draw_improvement_per_dollar(summaries, confidence=confidence), path)


def plot_time_to_target(rows: list[TargetTime], path: str | Path, *, target: float) -> Path:
    return _save(draw_time_to_target(rows, target=target), path)


def plot_invalid_and_crash_rates(
    summaries: list[SessionSummary],
    path: str | Path,
    *,
    confidence: float = 0.95,
) -> Path:
    return _save(draw_invalid_and_crash_rates(summaries, confidence=confidence), path)


def draw_reward_vs_revision(
    summaries: list[SessionSummary],
    *,
    confidence: float = 0.95,
) -> Figure:
    fig, ax = _figure(
        "Mean reward versus controller revision",
        summaries,
        "Each point is the mean of session means. Bars are "
        f"{_percent(confidence)} confidence intervals across sessions.",
    )
    if not summaries:
        return fig
    colors = _colors(summaries)
    grouped: dict[str, list[SessionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[_series_label(summary, summaries)].append(summary)
    for label in sorted(grouped):
        rows = grouped[label]
        revisions = sorted({revision for row in rows for revision, _ in row.reward_by_revision})
        xs: list[int] = []
        ys: list[float] = []
        lows: list[float] = []
        highs: list[float] = []
        for revision in revisions:
            interval = mean_interval(
                [dict(row.reward_by_revision).get(revision) for row in rows],
                confidence,
            )
            if interval.point is None:
                continue
            xs.append(revision)
            ys.append(interval.point)
            if interval.defined:
                lows.append(interval.point - interval.low)  # type: ignore[operator]
                highs.append(interval.high - interval.point)  # type: ignore[operator]
            else:
                lows.append(0.0)
                highs.append(0.0)
        if not xs:
            continue
        model_id = rows[0].model_id
        ax.errorbar(
            xs,
            ys,
            yerr=[lows, highs],
            label=label,
            color=colors[model_id],
            linestyle=CONDITION_LINESTYLE.get(rows[0].feedback_condition, "solid"),
            marker="o",
            linewidth=1.6,
            capsize=3,
        )
    ax.set_xlabel("Controller revision")
    ax.set_ylabel("Mean episode reward")
    _legend(ax)
    return fig


def draw_landing_success_vs_attempt(
    summaries: list[SessionSummary],
    *,
    confidence: float = 0.95,
) -> Figure:
    fig, ax = _figure(
        "Landing success versus episode attempt",
        summaries,
        "Attempt is the zero-based episode ordinal ordered by (revision, episode). "
        f"Bars are {_percent(confidence)} confidence intervals across sessions.",
    )
    if not summaries:
        return fig
    colors = _colors(summaries)
    grouped: dict[str, list[SessionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[_series_label(summary, summaries)].append(summary)
    for label in sorted(grouped):
        rows = grouped[label]
        attempts = sorted({attempt for row in rows for attempt, _ in row.success_by_attempt})
        xs: list[int] = []
        ys: list[float] = []
        lows: list[float] = []
        highs: list[float] = []
        for attempt in attempts:
            interval = mean_interval(
                [dict(row.success_by_attempt).get(attempt) for row in rows],
                confidence,
            )
            if interval.point is None:
                continue
            xs.append(attempt)
            ys.append(interval.point)
            if interval.defined:
                lows.append(max(0.0, interval.point - interval.low))  # type: ignore[operator]
                highs.append(max(0.0, interval.high - interval.point))  # type: ignore[operator]
            else:
                lows.append(0.0)
                highs.append(0.0)
        if not xs:
            continue
        ax.errorbar(
            xs,
            ys,
            yerr=[lows, highs],
            label=label,
            color=colors[rows[0].model_id],
            linestyle=CONDITION_LINESTYLE.get(rows[0].feedback_condition, "solid"),
            marker="o",
            linewidth=1.6,
            capsize=3,
        )
    ax.set_xlabel("Episode attempt")
    ax.set_ylabel("Landing success rate")
    ax.set_ylim(-0.05, 1.05)
    _legend(ax)
    return fig


def draw_initial_vs_final(summaries: list[SessionSummary]) -> Figure:
    fig, ax = _figure(
        "Initial versus final session reward",
        summaries,
        "Each line is one session. Initial is the first scored revision. "
        "Final is the last scored revision. Alphabetical color assignment is not a ranking.",
    )
    if not summaries:
        return fig
    colors = _colors(summaries)
    labeled: set[str] = set()
    plotted = False
    for summary in summaries:
        if summary.initial_mean_reward is None or summary.final_mean_reward is None:
            continue
        plotted = True
        label = summary.model_id if summary.model_id not in labeled else None
        labeled.add(summary.model_id)
        ax.plot(
            [0, 1],
            [summary.initial_mean_reward, summary.final_mean_reward],
            color=colors[summary.model_id],
            marker="o",
            linewidth=1.4,
            alpha=0.85,
            label=label,
        )
    if not plotted:
        _empty(ax)
        return fig
    ax.set_xticks([0, 1], ["Initial revision", "Final revision"])
    ax.set_ylabel("Mean episode reward")
    _legend(ax)
    return fig


def draw_improvement_per_dollar(
    summaries: list[SessionSummary],
    *,
    confidence: float = 0.95,
) -> Figure:
    fig, ax = _figure(
        "Reward improvement per dollar",
        summaries,
        "Improvement is final minus initial session mean reward, divided by "
        "the session's total estimated cost. Zero-cost sessions are omitted. "
        f"Bars are {_percent(confidence)} confidence intervals across sessions.",
    )
    if not summaries:
        return fig
    grouped: dict[str, list[SessionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[_series_label(summary, summaries)].append(summary)
    labels = sorted(grouped)
    points = []
    errors = []
    defined = []
    for label in labels:
        interval = mean_interval(
            [row.improvement_per_dollar for row in grouped[label]],
            confidence,
        )
        points.append(0.0 if interval.point is None else interval.point)
        if interval.defined:
            errors.append(
                (
                    interval.point - interval.low,  # type: ignore[operator]
                    interval.high - interval.point,  # type: ignore[operator]
                )
            )
        else:
            errors.append((0.0, 0.0))
        defined.append(interval.point is not None)
    if not any(defined):
        _empty(ax, "No session has both a reward change and a positive cost.")
        return fig
    colors = _colors(summaries)
    xs = list(range(len(labels)))
    yerr = [[item[0] for item in errors], [item[1] for item in errors]]
    ax.bar(
        xs,
        points,
        color=[colors[grouped[label][0].model_id] for label in labels],
        yerr=yerr,
        capsize=3,
        width=0.7,
    )
    ax.axhline(0.0, color="#444444", linewidth=0.8)
    ax.set_xticks(xs, labels, rotation=25, ha="right")
    ax.set_ylabel("Reward change per dollar")
    return fig


def draw_time_to_target(rows: list[TargetTime], *, target: float) -> Figure:
    fig, ax = _figure(
        f"Time to reach reward {target:g}",
        [],
        "Filled markers reached the target. Open markers did not; their x position "
        "is observed duration, not a time-to-target. Vertical offsets separate sessions.",
        synthetic=any(row.synthetic for row in rows),
    )
    if not rows:
        _empty(ax)
        return fig
    labels = sorted({_target_label(row) for row in rows})
    positions = {label: index for index, label in enumerate(labels)}
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        label = _target_label(row)
        offset = (counts[label] % 7) * 0.08
        counts[label] += 1
        y = positions[label] + offset
        if row.reached and row.seconds is not None:
            ax.scatter(row.seconds, y, marker="o", color="#0072B2", s=28, zorder=3)
        else:
            ax.scatter(
                row.observed_seconds,
                y,
                marker="o",
                facecolors="none",
                edgecolors="#D55E00",
                s=28,
                zorder=3,
            )
    ax.set_yticks(list(positions.values()), list(positions))
    ax.set_xlabel("Seconds")
    ax.set_ylabel("Model, condition, and split")
    return fig


def draw_invalid_and_crash_rates(
    summaries: list[SessionSummary],
    *,
    confidence: float = 0.95,
) -> Figure:
    fig, ax = _figure(
        "Invalid-controller and crash rates",
        summaries,
        "Invalid rate uses selected controller revisions. Crash rate uses executed "
        "episodes with a recorded crash flag. "
        f"Bars are {_percent(confidence)} confidence intervals across sessions.",
    )
    if not summaries:
        return fig
    grouped: dict[str, list[SessionSummary]] = defaultdict(list)
    for summary in summaries:
        grouped[_series_label(summary, summaries)].append(summary)
    labels = sorted(grouped)
    invalid = [mean_interval([row.invalid_rate for row in grouped[label]], confidence) for label in labels]
    crashes = [mean_interval([row.crash_rate for row in grouped[label]], confidence) for label in labels]
    if all(item.point is None for item in invalid) and all(item.point is None for item in crashes):
        _empty(ax, "No invalid-controller or crash rates were recorded.")
        return fig
    xs = list(range(len(labels)))
    width = 0.36
    ax.bar(
        [x - width / 2 for x in xs],
        [0.0 if item.point is None else item.point for item in invalid],
        width=width,
        label="Invalid controller",
        color="#D55E00",
        yerr=_yerr(invalid),
        capsize=3,
    )
    ax.bar(
        [x + width / 2 for x in xs],
        [0.0 if item.point is None else item.point for item in crashes],
        width=width,
        label="Crash",
        color="#0072B2",
        yerr=_yerr(crashes),
        capsize=3,
    )
    ax.set_xticks(xs, labels, rotation=25, ha="right")
    ax.set_ylabel("Rate")
    ax.set_ylim(0.0, 1.05)
    _legend(ax)
    return fig


def _figure(
    title: str,
    summaries: list[SessionSummary],
    footnote: str,
    *,
    synthetic: bool | None = None,
) -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=(8.2, 4.8), dpi=160)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    is_synthetic = any(summary.synthetic for summary in summaries) if synthetic is None else synthetic
    title = _with_family(title, summaries)
    if not summaries and synthetic is None:
        _empty(ax)
    if is_synthetic:
        fig.suptitle(SYNTHETIC_BANNER, color="#D55E00", fontsize=11, fontweight="bold")
        ax.set_title(title, fontsize=12, pad=16)
    else:
        ax.set_title(title, fontsize=13)
    fig.text(0.01, 0.01, footnote, fontsize=7.5, color="#333333", wrap=True)
    fig.tight_layout(rect=(0, 0.06, 1, 0.96 if is_synthetic else 1))
    return fig, ax


def _with_family(title: str, summaries: list[SessionSummary]) -> str:
    families = sorted({environment_family(summary.environment_id) for summary in summaries})
    if len(families) == 1:
        return f"{family_display(families[0])}: {title}"
    if len(families) > 1:
        return f"Separate environment families: {title}"
    return title


def _empty(ax: Axes, message: str = EMPTY_LOG_MESSAGE) -> None:
    ax.set_axis_off()
    ax.text(0.5, 0.5, message, ha="center", va="center", fontsize=12)


def _save(fig: Figure, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destination, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return destination


def _legend(ax: Axes) -> None:
    handles, labels = ax.get_legend_handles_labels()
    if labels:
        ax.legend(
            handles, [textwrap.fill(label, width=48, break_long_words=False) for label in labels],
            frameon=False, fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1.0),
        )


def _colors(summaries: list[SessionSummary]) -> dict[str, str]:
    models = sorted({summary.model_id for summary in summaries}, key=str.lower)
    return {model: OKABE_ITO[index % len(OKABE_ITO)] for index, model in enumerate(models)}


def _series_label(summary: SessionSummary, summaries: list[SessionSummary]) -> str:
    return (
        f"{provider_label(summary.provider)}/{summary.model_id} | {summary.environment_id} | "
        f"config {config_label(summary.environment_config)} | {summary.feedback_condition} | {summary.split}"
    )


def _target_label(row: TargetTime) -> str:
    return textwrap.fill((
        f"{provider_label(row.provider)}/{row.model_id} | {row.environment_id} | "
        f"config {config_label(row.environment_config)} ({row.feedback_condition}, {row.split})"
    ), width=55, break_long_words=False)


def _percent(confidence: float) -> str:
    return f"{confidence * 100:g}%"


def _yerr(intervals: list) -> list[list[float]]:
    lows = []
    highs = []
    for interval in intervals:
        if interval.point is None or not interval.defined:
            lows.append(0.0)
            highs.append(0.0)
        else:
            lows.append(max(0.0, interval.point - interval.low))
            highs.append(max(0.0, interval.high - interval.point))
    return [lows, highs]
