"""Controller schema tests. These never start the physics simulation."""

from __future__ import annotations

import math

from rewardbench.environments.lunarlander.schema import (
    REFERENCE_HEURISTIC_PARAMETERS,
    SCHEMA_ID,
    idle_controller,
    normalize_controller,
    random_controller,
    reference_controller,
    validate_controller,
)


def test_reference_and_idle_controllers_are_valid() -> None:
    assert validate_controller(reference_controller()).valid
    assert validate_controller(idle_controller()).valid
    assert validate_controller(random_controller(7)).valid


def test_reference_parameters_match_the_published_heuristic() -> None:
    normalized = normalize_controller(reference_controller())
    assert normalized.parameter_map() == REFERENCE_HEURISTIC_PARAMETERS


def test_json_string_controller_is_accepted() -> None:
    status = validate_controller(
        '{"schema": "rewardbench.lunarlander.controller.v1", "policy": "random", "seed": 3}'
    )
    assert status.valid
    assert status.policy == "random"


def test_python_source_is_rejected_as_data() -> None:
    status = validate_controller("def act(obs):\n    return 2\n")
    assert not status.valid
    assert status.reason is not None
    assert "JSON" in status.reason


def test_embedded_python_field_is_rejected() -> None:
    payload = reference_controller()
    payload["code"] = "import os; os.system('echo owned')"
    status = validate_controller(payload)
    assert not status.valid
    assert status.reason is not None
    assert "code" in status.reason


def test_nested_forbidden_field_is_rejected() -> None:
    payload = reference_controller()
    payload["parameters"] = dict(payload["parameters"])
    payload["parameters"]["exec"] = "print(1)"
    status = validate_controller(payload)
    assert not status.valid
    assert status.reason is not None
    assert "exec" in status.reason


def test_unknown_policy_and_extra_field_are_rejected() -> None:
    status = validate_controller(
        {"schema": SCHEMA_ID, "policy": "python", "parameters": {}}
    )
    assert not status.valid
    missing = validate_controller({"schema": SCHEMA_ID, "policy": "random", "seed": 1, "note": "x"})
    assert not missing.valid
    assert missing.reason is not None
    assert "note" in missing.reason


def test_non_finite_and_out_of_range_parameters_are_rejected() -> None:
    parameters = dict(REFERENCE_HEURISTIC_PARAMETERS)
    parameters["angle_target_x_gain"] = math.nan
    nan_status = validate_controller(
        {"schema": SCHEMA_ID, "policy": "heuristic", "parameters": parameters}
    )
    assert not nan_status.valid

    parameters = dict(REFERENCE_HEURISTIC_PARAMETERS)
    parameters["hover_x_gain"] = 100.0
    range_status = validate_controller(
        {"schema": SCHEMA_ID, "policy": "heuristic", "parameters": parameters}
    )
    assert not range_status.valid
    assert range_status.reason is not None
    assert "hover_x_gain" in range_status.reason


def test_linear_shape_and_bool_seed_are_rejected() -> None:
    status = validate_controller(
        {"schema": SCHEMA_ID, "policy": "linear", "weights": [[1.0, 2.0]], "bias": [0, 0, 0, 0]}
    )
    assert not status.valid
    seed_status = validate_controller({"schema": SCHEMA_ID, "policy": "random", "seed": True})
    assert not seed_status.valid


def test_partial_heuristic_is_not_silently_filled() -> None:
    status = validate_controller(
        {
            "schema": SCHEMA_ID,
            "policy": "heuristic",
            "parameters": {"angle_target_x_gain": 0.5},
        }
    )
    assert not status.valid
    assert status.reason is not None
    assert "missing heuristic parameter" in status.reason


def test_rejection_is_a_status_not_an_exception() -> None:
    status = validate_controller({"not": "a controller"})
    assert not status.valid
    assert status.policy is None
    assert status.reason
