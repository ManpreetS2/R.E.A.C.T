"""Landing labels follow the physics snapshot, not the terminal reward."""

from __future__ import annotations

from rewardbench.environments.lunarlander.outcomes import PhysicsSnapshot, classify_outcome


def _settled(**overrides: object) -> PhysicsSnapshot:
    fields: dict[str, object] = {
        "terminated": True,
        "truncated": False,
        "game_over": False,
        "out_of_bounds": False,
        "lander_awake": False,
        "in_landing_zone": True,
        "lander_x": 10.0,
        "helipad_x1": 8.0,
        "helipad_x2": 12.0,
    }
    fields.update(overrides)
    return PhysicsSnapshot(**fields)  # type: ignore[arg-type]


def test_asleep_between_the_flags_is_a_successful_landing() -> None:
    outcome = classify_outcome(_settled())
    assert outcome.landed
    assert not outcome.crashed
    assert outcome.label == "landed"
    assert outcome.in_landing_zone is True


def test_asleep_outside_the_flags_is_not_a_successful_landing() -> None:
    outcome = classify_outcome(_settled(in_landing_zone=False, lander_x=14.0))
    assert outcome.landed is False
    assert outcome.crashed is False
    assert outcome.label == "landed_outside_zone"


def test_asleep_without_a_zone_measurement_is_not_called_a_landing() -> None:
    outcome = classify_outcome(_settled(in_landing_zone=None, lander_x=None))
    assert outcome.landed is False
    assert outcome.label == "settled_zone_unknown"


def test_hull_contact_is_a_physical_crash_even_if_the_body_is_asleep() -> None:
    outcome = classify_outcome(_settled(game_over=True, in_landing_zone=True))
    assert outcome.crashed
    assert not outcome.landed
    assert outcome.label == "physical_crash"
    assert outcome.crash_cause == "hull_contact"


def test_viewport_exit_is_separate_from_a_physical_crash() -> None:
    outcome = classify_outcome(
        _settled(out_of_bounds=True, lander_awake=True, in_landing_zone=False)
    )
    assert outcome.viewport_exit
    assert outcome.crashed is False
    assert outcome.landed is False
    assert outcome.label == "viewport_exit"


def test_time_limit_is_a_timeout() -> None:
    outcome = classify_outcome(
        PhysicsSnapshot(
            terminated=False,
            truncated=True,
            game_over=False,
            out_of_bounds=False,
            lander_awake=True,
        )
    )
    assert not outcome.landed
    assert not outcome.crashed
    assert outcome.timed_out
    assert outcome.label == "timeout"


def test_in_zone_settlement_on_the_time_limit_step_still_counts() -> None:
    outcome = classify_outcome(_settled(truncated=True))
    assert outcome.landed
    assert outcome.label == "landed"
