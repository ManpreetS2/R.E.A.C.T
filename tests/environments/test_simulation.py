"""Physics, scoring, and controller tests against Gymnasium LunarLander-v3."""

from __future__ import annotations

from pathlib import Path

import pytest

gymnasium = pytest.importorskip("gymnasium")
pytest.importorskip("Box2D")

from rewardbench.environments.lunarlander.actions import PHYSICS_FPS
from rewardbench.environments.lunarlander.adapter import LunarLanderAdapter
from rewardbench.environments.lunarlander.controller import compile_controller, episode_rng
from rewardbench.environments.lunarlander.recording import read_replay
from rewardbench.environments.lunarlander.schema import idle_controller, random_controller, reference_controller
from rewardbench.environments.lunarlander.seeds import development_seeds


def test_invalid_controller_does_not_open_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = LunarLanderAdapter()

    def refuse_environment(*_args, **_kwargs):
        raise AssertionError("invalid controller opened LunarLander")

    monkeypatch.setattr(adapter, "_make_env", refuse_environment)
    evaluation = adapter.evaluate(
        {"schema": "rewardbench.lunarlander.controller.v1", "policy": "heuristic", "code": "print(1)"},
        development_seeds(2),
        split="development",
        revision=3,
    )
    assert evaluation.controller_valid is False
    assert evaluation.mean_reward is None
    assert evaluation.landing_count == 0
    assert [episode.seed for episode in evaluation.episodes] == [0, 1]
    assert all(episode.outcome == "invalid" and episode.landed is False for episode in evaluation.episodes)


def test_reference_actions_match_gymnasium_heuristic() -> None:
    from gymnasium.envs.box2d.lunar_lander import heuristic

    class _env:
        class unwrapped:
            continuous = False

    adapter = LunarLanderAdapter()
    compiled = compile_controller(reference_controller())
    env = adapter._make_env(render=False, max_steps=None)
    try:
        observation, _info = env.reset(seed=2)
        rng = episode_rng(0, 2)
        compared = 0
        while compared < 250:
            expected = int(heuristic(_env(), observation))
            actual = compiled.act(observation, rng)
            assert actual == expected
            observation, _reward, terminated, truncated, _info = env.step(actual)
            compared += 1
            if terminated or truncated:
                break
        assert compared > 10
    finally:
        env.close()


def test_repeated_seed_repeats_reward_and_actions() -> None:
    adapter = LunarLanderAdapter()
    seeds = development_seeds(1)
    first = adapter.evaluate(reference_controller(), seeds, split="development")
    second = adapter.evaluate(reference_controller(), seeds, split="development")
    assert first.episodes[0].reward == second.episodes[0].reward
    assert first.episodes[0].action_checksum == second.episodes[0].action_checksum
    assert first.episodes[0].landed == second.episodes[0].landed
    assert first.episodes[0].steps == second.episodes[0].steps


def test_idle_controller_crashes_and_is_not_called_a_landing() -> None:
    adapter = LunarLanderAdapter()
    evaluation = adapter.evaluate(idle_controller(), development_seeds(2), split="development", revision=0)
    assert evaluation.controller_valid
    assert evaluation.landing_count == 0
    for episode in evaluation.episodes:
        assert episode.executed
        assert episode.landed is False
        assert episode.crashed is True
        assert episode.outcome == "physical_crash"
        assert episode.viewport_exit is False
        assert episode.timed_out is False
        assert episode.fuel_penalty == 0.0
        assert episode.main_engine_steps == 0
        assert episode.side_engine_steps == 0
        assert episode.idle_steps == episode.steps
        assert episode.reward is not None
        assert episode.steps > 0


def test_reference_controller_lands_on_development_seeds() -> None:
    adapter = LunarLanderAdapter()
    evaluation = adapter.evaluate(
        reference_controller(),
        development_seeds(4),
        split="development",
        revision=1,
    )
    assert evaluation.controller_valid
    assert evaluation.landing_count >= 1
    assert evaluation.mean_reward is not None
    for episode in evaluation.episodes:
        assert episode.main_engine_steps + episode.side_engine_steps + episode.idle_steps == episode.steps
        assert episode.fuel_penalty == round(
            episode.main_engine_steps * 0.30 + episode.side_engine_steps * 0.03,
            2,
        )
        assert episode.duration_seconds == pytest.approx(episode.steps / PHYSICS_FPS)
        if episode.landed:
            assert episode.terminated
            assert episode.crashed is False
            assert episode.hull_contact is False
            assert episode.out_of_bounds is False
            assert episode.lander_awake is False
            assert episode.last_step_reward == pytest.approx(100.0)
            assert episode.outcome == "landed"
            assert episode.in_landing_zone is True
            assert episode.helipad_x1 is not None and episode.helipad_x2 is not None
            assert episode.lander_x is not None
            assert episode.helipad_x1 <= episode.lander_x <= episode.helipad_x2
        if episode.crashed:
            assert episode.landed is False


def test_random_baseline_runs_and_stays_reproducible() -> None:
    adapter = LunarLanderAdapter()
    seeds = development_seeds(2, start=20)
    controller = random_controller(5)
    first = adapter.evaluate(controller, seeds, split="development", max_steps=40)
    second = adapter.evaluate(controller, seeds, split="development", max_steps=40)
    assert first.controller_valid
    assert [episode.action_checksum for episode in first.episodes] == [
        episode.action_checksum for episode in second.episodes
    ]
    assert all(episode.landed is False for episode in first.episodes)
    assert all(
        episode.outcome in {"timeout", "physical_crash", "viewport_exit"}
        for episode in first.episodes
    )


def test_scored_replay_matches_the_episode(tmp_path) -> None:
    adapter = LunarLanderAdapter()
    evaluation = adapter.evaluate(
        reference_controller(),
        development_seeds(1, start=7),
        split="development",
        revision=4,
        record_dir=tmp_path,
        max_steps=15,
    )
    assert len(evaluation.replay_paths) == 1
    replay = read_replay(Path(evaluation.replay_paths[0]))
    episode = evaluation.episodes[0]
    assert len(replay["steps"]) == episode.steps
    assert replay["result"]["landed"] is episode.landed
    assert replay["result"]["reward"] == episode.reward
    assert replay["steps"][0]["action_name"] in {"idle", "left_engine", "main_engine", "right_engine"}


def test_rendered_episode_matches_headless_scoring() -> None:
    adapter = LunarLanderAdapter()
    compiled = compile_controller(reference_controller())
    kwargs = {"seed": 6, "revision": None, "max_steps": 40}
    headless = adapter._make_env(render=False, max_steps=40)
    rendered = adapter._make_env(render=True, max_steps=40)
    try:
        headless_episode, _replay, _frames = adapter._run_episode(headless, compiled, **kwargs)
        rendered_episode, _replay, frames = adapter._run_episode(
            rendered, compiled, collect_frames=True, **kwargs
        )
    finally:
        headless.close()
        rendered.close()
    assert frames
    assert rendered_episode.reward == headless_episode.reward
    assert rendered_episode.action_checksum == headless_episode.action_checksum
    assert rendered_episode.landed is headless_episode.landed


def test_video_recording_writes_an_mp4(tmp_path) -> None:
    pytest.importorskip("imageio")
    adapter = LunarLanderAdapter()
    evaluation = adapter.evaluate(
        idle_controller(),
        development_seeds(1, start=3),
        split="development",
        revision=9,
        record_dir=tmp_path,
        record_video=True,
        max_steps=4,
    )
    assert evaluation.video_errors == ()
    assert len(evaluation.video_paths) == 1
    video = Path(evaluation.video_paths[0])
    assert video.is_file()
    assert video.stat().st_size > 0
    assert evaluation.episodes[0].landed is False
