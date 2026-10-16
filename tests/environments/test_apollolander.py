"""ApolloLander adapter tests. These do not replace the Gymnasium tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import (
    START_SCHEDULE_VERSION,
    assert_schedules_disjoint,
    constant_controller,
    demonstration_guidance_controller,
    derive_start,
    development_start_catalog,
    held_out_start_catalog,
    standard_start,
)
from rewardbench.environments.apollolander.recording import write_flight_video
from rewardbench.environments.apollolander.schema import validate_controller

ROOT = Path(__file__).resolve().parents[2]


def test_make_environment_keeps_both_adapters() -> None:
    gym = make_environment("LunarLander-v3")
    apollo = make_environment("ApolloLander")
    assert gym.environment_id == "LunarLander-v3"
    assert apollo.environment_id == "ApolloLander"
    gym.close()
    apollo.close()


def test_controller_rejects_javascript() -> None:
    status = validate_controller(
        {
            "schema": "rewardbench.apollolander.controller.v1",
            "policy": "constant",
            "thrust": 1,
            "rotation": 0,
            "code": "lander.fuel = 9999",
        }
    )
    assert status.valid is False
    adapter = make_environment("ApolloLander")
    report = adapter.evaluate(
        {
            "schema": "rewardbench.apollolander.controller.v1",
            "policy": "constant",
            "thrust": 1,
            "rotation": 0,
            "js": "step()",
        },
        [0],
        revision=1,
    )
    assert report["controller_valid"] is False
    assert report["episodes"][0]["executed"] is False


def test_development_split_rejects_held_out_seeds() -> None:
    adapter = make_environment("ApolloLander")
    with pytest.raises(ValueError, match="held-out"):
        adapter.evaluate(constant_controller(0, -90), [1_000_000], revision=1, split="development")


def test_node_physics_suite() -> None:
    completed = subprocess.run(
        ["node", "frontend/apollolander/experiment/physics.test.js"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_matched_trials_ignore_the_seed() -> None:
    adapter = make_environment("ApolloLander", max_steps=40)
    report = adapter.evaluate(constant_controller(0, -90), [3, 9], revision=1, max_steps=40)
    first, second = report["episodes"]
    assert first["reward"] == second["reward"]
    assert first["status"] == "timeout"
    assert first["steps"] == 40
    assert report["seed_affects_physics"] is False
    assert report["autonomous_learning"] is False


def test_replay_matches_live_steps() -> None:
    adapter = make_environment("ApolloLander")
    trace = [
        {"thrust": 0, "rotation": -90},
        {"thrust": 0.4, "rotation": -80},
        {"thrust": 0.4, "rotation": -70},
    ]
    replayed = adapter.replay(trace, max_steps=20)
    live = adapter.evaluate(constant_controller(0, -90), [0], revision=1, max_steps=1)
    assert len(replayed["frames"]) == 3
    assert replayed["frames"][0]["observation"]["rotation"] == -90
    assert live["episodes"][0]["executed"] is True


def test_weak_controller_crashes_and_guidance_lands_in_zone() -> None:
    adapter = make_environment("ApolloLander")
    crash = adapter.evaluate(constant_controller(0, -90), [0], revision=1, origin="hand_specified_demonstration")
    episode = crash["episodes"][0]
    assert episode["crashed"] is True
    assert episode["landed"] is False
    assert episode["verified"]["kind"] == "crashed"
    assert crash["autonomous_learning"] is False

    landing = adapter.evaluate(
        demonstration_guidance_controller(),
        [0],
        revision=2,
        origin="hand_specified_demonstration",
        model="hand-specified-guidance",
    )
    landed = landing["episodes"][0]
    assert landed["landed"] is True
    assert landed["in_landing_zone"] is True
    assert landed["verified"]["designated"] is True
    assert landed["verified"]["rotation"] == 0
    assert landed["verified"]["vy"] < 0.075
    assert landing["origin"] == "hand_specified_demonstration"


def test_short_video_is_1920_by_1080_at_60_fps(tmp_path: Path) -> None:
    terrain = [{"x": 0, "y": 100}, {"x": 80, "y": 100}, {"x": 160, "y": 140}]
    camera = {"left": -20, "top": 0, "width": 320, "height": 180, "screenWidth": 1920, "screenHeight": 1080}
    frames = []
    for step in range(4):
        frames.append(
            {
                "camera": camera,
                "zone": {"x1": 40, "x2": 120, "y": 100},
                "lander": [[{"x": 20 + step, "y": 40}, {"x": 28 + step, "y": 55}, {"x": 12 + step, "y": 55}]],
                "thrust": None,
                "observation": {"vx": 0.1, "vy": 0.02, "fuel": 900 - step},
                "result": {"reward": -0.2 * step, "status": "flying"},
            }
        )
    path = tmp_path / "clip.mp4"
    write_flight_video(path, terrain, frames, hud={"model": "test", "revision": "1"})
    import imageio.v2 as imageio

    reader = imageio.get_reader(path)
    meta = reader.get_meta_data()
    frame = reader.get_data(0)
    count = sum(1 for _ in reader.iter_data())
    reader.close()
    assert frame.shape == (1080, 1920, 3)
    assert meta["fps"] == 60
    assert count == 4


def test_research_mode_varies_starts_by_seed() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=30)
    report = adapter.evaluate(constant_controller(0, -90), [0, 1], revision=1, max_steps=30)
    first, second = report["episodes"]
    assert report["seed_affects_physics"] is True
    assert report["start_schedule_version"] == START_SCHEDULE_VERSION
    assert first["start"] != second["start"]
    assert first["reward"] != second["reward"] or first["start"]["x"] != second["start"]["x"]
    assert first["identical_start"] is False


def test_research_mode_is_reproducible_for_same_seed_and_controller() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=80)
    controller = constant_controller(0.2, -80)
    first = adapter.evaluate(controller, [7], revision=1, max_steps=80)
    second = adapter.evaluate(controller, [7], revision=1, max_steps=80)
    assert first["episodes"][0]["start"] == second["episodes"][0]["start"]
    assert first["episodes"][0]["reward"] == second["episodes"][0]["reward"]
    assert first["episodes"][0]["steps"] == second["episodes"][0]["steps"]
    assert first["episodes"][0]["status"] == second["episodes"][0]["status"]


def test_matched_models_share_research_starts() -> None:
    left = make_environment("ApolloLander", research_mode=True)
    right = make_environment("ApolloLander", research_mode=True)
    seeds = [2, 5, 11]
    assert [left.start_for_seed(seed) for seed in seeds] == [right.start_for_seed(seed) for seed in seeds]
    assert left.start_for_seed(2) == derive_start(2).as_dict()


def test_development_and_held_out_start_schedules_are_disjoint() -> None:
    development = development_start_catalog(64)
    held_out = held_out_start_catalog(64)
    assert_schedules_disjoint(development, held_out)
    assert len({tuple(start.as_dict().values()) for _, start in development}) == 64
    assert len({tuple(start.as_dict().values()) for _, start in held_out}) == 64


def test_research_mode_rejects_explicit_start_override() -> None:
    adapter = make_environment("ApolloLander", research_mode=True)
    with pytest.raises(ValueError, match="research mode"):
        adapter.evaluate(
            constant_controller(0, -90),
            [0],
            revision=1,
            start={"x": 10, "y": 80, "vx": 0, "vy": 0, "rotation": 0, "fuel": 500, "scale": 0.25},
        )


def test_research_replay_matches_live_trace() -> None:
    adapter = make_environment("ApolloLander", research_mode=True)
    seed = 4
    start = adapter.start_for_seed(seed)
    rotation = int(start["rotation"])
    trace = [
        {"thrust": 0, "rotation": rotation},
        {"thrust": 0.3, "rotation": max(-90, min(90, rotation + 10))},
        {"thrust": 0.3, "rotation": max(-90, min(90, rotation + 20))},
    ]
    first = adapter.replay(trace, seed=seed, max_steps=20)
    second = adapter.replay(trace, seed=seed, max_steps=20)
    live = adapter.evaluate(constant_controller(0, rotation), [seed], revision=1, max_steps=1)
    assert len(first["frames"]) == 3
    assert first["frames"] == second["frames"]
    assert first["result"] == second["result"]
    assert live["episodes"][0]["start"] == start
    # After the first control step the craft has moved, but from the seeded start.
    assert abs(first["frames"][0]["observation"]["x"] - start["x"]) < 5.0
    assert abs(first["frames"][0]["observation"]["x"] - standard_start().x) > 1.0


def test_demonstration_origin_stays_non_autonomous_under_research_mode() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=40)
    report = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        origin="hand_specified_demonstration",
        model="constant-coast",
        max_steps=40,
    )
    assert report["origin"] == "hand_specified_demonstration"
    assert report["autonomous_learning"] is False
    assert report["episodes"][0]["executed"] is True


def test_vary_fuel_changes_start_fuel() -> None:
    plain = derive_start(3, vary_fuel=False)
    fueled = derive_start(3, vary_fuel=True)
    assert plain.fuel == 1000.0
    assert fueled.fuel != plain.fuel
    assert 850.0 <= fueled.fuel <= 1000.0
