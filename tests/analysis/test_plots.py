from pathlib import Path

from rewardbench.analysis.load import load_logs
from rewardbench.analysis.plots import (
    draw_initial_vs_final,
    draw_invalid_and_crash_rates,
    draw_landing_success_vs_attempt,
    draw_reward_vs_revision,
    draw_time_to_target,
    plot_reward_vs_revision,
)
from rewardbench.analysis.schema import EMPTY_LOG_MESSAGE, SYNTHETIC_BANNER
from rewardbench.analysis.sessions import session_summaries, time_to_targets
from fixtures import build_synthetic_plot_log


def test_empty_figure_states_that_no_logs_were_loaded() -> None:
    figure = draw_reward_vs_revision([])
    text = figure.axes[0].texts[0].get_text()
    assert text == EMPTY_LOG_MESSAGE
    figure.clf()


def test_synthetic_fixture_draws_every_required_figure(tmp_path: Path) -> None:
    database = tmp_path / "synthetic.sqlite"
    build_synthetic_plot_log(database)
    bundle = load_logs(database)
    assert bundle.synthetic
    summaries = session_summaries(bundle)
    reward = draw_reward_vs_revision(summaries)
    assert SYNTHETIC_BANNER in reward.texts[0].get_text() or any(
        SYNTHETIC_BANNER in text.get_text() for text in reward.texts
    )
    assert reward.axes[0].get_ylabel() == "Mean episode reward"
    labels = [text.get_text() for text in reward.axes[0].get_legend().get_texts()]
    assert labels == sorted(labels)
    landing = draw_landing_success_vs_attempt(summaries)
    assert landing.axes[0].get_xlabel() == "Episode attempt"
    initial = draw_initial_vs_final(summaries)
    assert initial.axes[0].get_ylabel() == "Mean episode reward"
    rates = draw_invalid_and_crash_rates(summaries)
    assert rates.axes[0].get_ylabel() == "Rate"
    timed = draw_time_to_target(time_to_targets(summaries, (200.0,)), target=200.0)
    assert timed.axes[0].get_xlabel() == "Seconds"
    for figure in (reward, landing, initial, rates, timed):
        figure.clf()

    saved = plot_reward_vs_revision(summaries, tmp_path / "reward.png")
    payload = saved.read_bytes()
    assert payload.startswith(b"\x89PNG")
    assert saved.stat().st_size > 1000
