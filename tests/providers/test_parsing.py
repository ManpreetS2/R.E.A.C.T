"""Structured controller parsing. Invalid text is data, not an exception."""

from __future__ import annotations

from rewardbench.providers.parsing import parse_controller


def test_plain_and_fenced_json_parse_to_the_same_object():
    body = '{"policy":"heuristic","parameters":{"angle_target_limit":0.4}}'
    fenced = "```json\n" + body + "\n```"
    plain, plain_error = parse_controller(body)
    boxed, boxed_error = parse_controller(fenced)
    assert plain_error is None and boxed_error is None
    assert plain == boxed
    assert plain["policy"] == "heuristic"


def test_prose_without_json_sets_parse_error():
    parameters, error = parse_controller("I would land softly.")
    assert parameters is None
    assert error == "response did not contain a JSON object"


def test_forbidden_code_field_is_rejected():
    parameters, error = parse_controller('{"policy":"heuristic","code":"print(1)"}')
    assert parameters is None
    assert "forbidden" in error


def test_array_and_trailing_junk_are_rejected():
    array, array_error = parse_controller("[1, 2, 3]")
    junk, junk_error = parse_controller('{"policy":"heuristic"} and then python')
    prose, prose_error = parse_controller('Sure: {"policy":"heuristic"}')
    assert array is None and "object" in array_error
    assert junk is None and "only value" in junk_error
    assert prose is None and prose_error


def test_non_finite_number_is_rejected():
    parameters, error = parse_controller('{"gain":1e309}')
    assert parameters is None
    assert "non-finite" in error
