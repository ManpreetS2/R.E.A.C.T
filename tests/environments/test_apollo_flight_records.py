"""Flight-record provenance, deterministic replay, and recording artifacts."""

from __future__ import annotations

from pathlib import Path

import pytest

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import (
    ENVIRONMENT_VERSION,
    ORIGIN_DETERMINISTIC_MOCK,
    ORIGIN_HAND_SPECIFIED,
    ORIGIN_MODEL_GENERATED,
    assert_schedules_disjoint,
    constant_controller,
    demonstration_guidance_controller,
    development_start_catalog,
    held_out_start_catalog,
    load_flight_record,
)
from rewardbench.environments.apollolander.flight_record import autonomous_learning_claimed


def test_research_reproducibility_across_development_and_held_out_seeds() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=60)
    development = [0, 3, 7, 15]
    held_out = [1_000_000, 1_000_003, 1_000_007]
    controller = constant_controller(0.15, -70)

    first = adapter.evaluate(controller, development, revision=1, max_steps=60, split="development")
    second = adapter.evaluate(controller, development, revision=1, max_steps=60, split="development")
    for left, right in zip(first["episodes"], second["episodes"], strict=True):
        assert left["start"] == right["start"]
        assert left["reward"] == right["reward"]
        assert left["steps"] == right["steps"]
        assert left["trace_hash"] == right["trace_hash"]
        assert left["environment_version"] == ENVIRONMENT_VERSION

    held = adapter.evaluate(controller, held_out, revision=1, max_steps=60, split="held_out")
    again = adapter.evaluate(controller, held_out, revision=1, max_steps=60, split="held_out")
    for left, right in zip(held["episodes"], again["episodes"], strict=True):
        assert left["start"] == right["start"]
        assert left["reward"] == right["reward"]
        assert left["flight_record"]["initial_state"] == right["start"]

    assert_schedules_disjoint(development_start_catalog(48), held_out_start_catalog(48))
    held_starts = {tuple(ep["start"].values()) for ep in held["episodes"]}
    dev_starts = {tuple(ep["start"].values()) for ep in first["episodes"]}
    assert held_starts.isdisjoint(dev_starts)


def test_model_name_does_not_change_physics() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=40)
    controller = constant_controller(0, -90)
    alpha = adapter.evaluate(controller, [5], revision=2, max_steps=40, model="alpha-model")
    beta = adapter.evaluate(controller, [5], revision=2, max_steps=40, model="beta-model")
    assert alpha["episodes"][0]["start"] == beta["episodes"][0]["start"]
    assert alpha["episodes"][0]["reward"] == beta["episodes"][0]["reward"]
    assert alpha["episodes"][0]["trace"] == beta["episodes"][0]["trace"]
    assert alpha["episodes"][0]["model"] != beta["episodes"][0]["model"]


def test_flight_record_fields_and_replay_verification(tmp_path: Path) -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=35)
    report = adapter.evaluate(
        constant_controller(0.2, -80),
        [4],
        revision=3,
        max_steps=35,
        origin=ORIGIN_DETERMINISTIC_MOCK,
        model="mock-constant",
        record_dir=tmp_path,
        record_video=True,
    )
    episode = report["episodes"][0]
    record = episode["flight_record"]
    required = {
        "schema",
        "environment_id",
        "environment_version",
        "start_schedule_version",
        "episode_seed",
        "initial_state",
        "controller",
        "revision_index",
        "terminal",
        "trace",
        "trace_hash",
        "origin",
        "model",
    }
    assert required <= set(record)
    assert record["environment_version"] == ENVIRONMENT_VERSION
    assert record["start_schedule_version"] == "apollolander.starts.v1"
    assert record["episode_seed"] == 4
    assert record["revision_index"] == 3
    assert record["origin"] == ORIGIN_DETERMINISTIC_MOCK
    assert record["autonomous_learning"] is False
    assert record["terminal"]["steps"] == episode["steps"]
    assert Path(episode["flight_record_path"]).is_file()
    assert Path(episode["video_path"]).is_file()

    loaded = load_flight_record(episode["flight_record_path"])
    verified = adapter.verify_flight_record(loaded)
    assert verified["matched"] is True
    assert verified["mismatches"] == []


def test_origins_never_claim_autonomous_learning_for_demos_or_mocks() -> None:
    assert autonomous_learning_claimed(ORIGIN_HAND_SPECIFIED) is False
    assert autonomous_learning_claimed(ORIGIN_DETERMINISTIC_MOCK) is False
    assert autonomous_learning_claimed(ORIGIN_MODEL_GENERATED) is False
    adapter = make_environment("ApolloLander", max_steps=20)
    demo = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        max_steps=20,
        origin=ORIGIN_HAND_SPECIFIED,
    )
    mock = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        max_steps=20,
        origin=ORIGIN_DETERMINISTIC_MOCK,
    )
    future = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        max_steps=20,
        origin=ORIGIN_MODEL_GENERATED,
        model="gpt-test",
    )
    assert demo["autonomous_learning"] is False
    assert mock["autonomous_learning"] is False
    assert future["autonomous_learning"] is False
    assert future["origin"] == ORIGIN_MODEL_GENERATED


def test_replay_rejects_tampered_hashes_and_nonfinite_rewards() -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=5)
    record = adapter.evaluate(constant_controller(0, -90), [4], max_steps=5)["episodes"][0]["flight_record"]
    tampered = {**record, "trace_hash": "forged"}
    assert adapter.verify_flight_record(tampered)["matched"] is False
    tampered = {**record, "terminal": {**record["terminal"], "reward": float("nan")}}
    assert adapter.verify_flight_record(tampered)["matched"] is False
    with pytest.raises(ValueError, match="vary_fuel"):
        make_environment("ApolloLander", research_mode=True, vary_fuel=True).verify_flight_record(record)


def test_hand_specified_crash_and_landing_recordings(tmp_path: Path) -> None:
    adapter = make_environment("ApolloLander")
    crash = adapter.evaluate(
        constant_controller(0, -90),
        [0],
        revision=1,
        origin=ORIGIN_HAND_SPECIFIED,
        model="constant-coast",
        record_dir=tmp_path,
        record_video=True,
    )
    crash_ep = crash["episodes"][0]
    assert crash_ep["crashed"] is True
    assert crash["autonomous_learning"] is False
    assert Path(crash_ep["video_path"]).is_file()
    assert Path(crash_ep["flight_record_path"]).is_file()
    assert adapter.verify_flight_record(crash_ep["flight_record_path"])["matched"] is True

    landing = adapter.evaluate(
        demonstration_guidance_controller(),
        [0],
        revision=1,
        origin=ORIGIN_HAND_SPECIFIED,
        model="hand-specified-guidance",
        record_dir=tmp_path,
        record_video=True,
        max_steps=8000,
    )
    land_ep = landing["episodes"][0]
    assert land_ep["landed"] is True
    assert land_ep["verified"]["designated"] is True
    assert Path(land_ep["video_path"]).is_file()
    assert land_ep["flight_record"]["origin"] == ORIGIN_HAND_SPECIFIED
    assert land_ep["flight_record"]["autonomous_learning"] is False
    assert adapter.verify_flight_record(land_ep["flight_record_path"])["matched"] is True


def test_research_mode_records_without_fixed_start(tmp_path: Path) -> None:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=45)
    report = adapter.evaluate(
        constant_controller(0, -60),
        [9],
        revision=1,
        max_steps=45,
        origin=ORIGIN_DETERMINISTIC_MOCK,
        model="research-mock",
        record_dir=tmp_path,
        record_video=True,
    )
    episode = report["episodes"][0]
    assert report["research_mode"] is True
    assert episode["seed_affects_physics"] is True
    assert episode["start"] != make_environment("ApolloLander").start_for_seed(9)
    assert Path(episode["video_path"]).is_file()
    verified = adapter.verify_flight_record(episode["flight_record_path"])
    assert verified["matched"] is True
    assert episode["flight_record"]["research_mode"] is True
    assert episode["flight_record"]["initial_state"] == episode["start"]
