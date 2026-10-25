"""verify_flight_record must reject every inconsistent action trace, and agree with the browser engine.

Re-sealed records (declared trace_length and trace_hash recomputed to match the edited
trace) are the hard case: only a comparison with what the physics actually consumed can
catch them.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import constant_controller, demonstration_guidance_controller
from rewardbench.environments.apollolander.flight_record import trace_hash

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "frontend" / "apollolander" / "experiment" / "replay.test.js"
TRACKED = ROOT / "docs" / "assets" / "v1-evidence" / "flights" / "offline_mock_development_episode.flight.json"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


@pytest.fixture(scope="module")
def adapter():
    return make_environment("ApolloLander", research_mode=True, max_steps=8000)


@pytest.fixture(scope="module")
def genuine(adapter) -> dict[str, dict]:
    def flight(controller, seed, max_steps=8000):
        return adapter.evaluate(controller, [seed], revision=1, max_steps=max_steps,
                                split="development")["episodes"][0]["flight_record"]
    records = {
        "landing": flight(demonstration_guidance_controller(), 0),
        "crash": flight(constant_controller(0.0, 0), 2),
        "timeout": flight(constant_controller(0.0, -90), 5, max_steps=60),
        "tracked_timeout": json.loads(TRACKED.read_text()),
    }
    assert records["landing"]["terminal"]["status"] == "landed"
    assert records["crash"]["terminal"]["status"] == "crashed"
    assert records["timeout"]["terminal"]["status"] == "timeout"
    return records


def reseal(record: dict) -> dict:
    record["trace_length"] = len(record["trace"])
    record["trace_hash"] = trace_hash(record["trace"])
    return record


def js_verdicts(tmp_path: Path, records: dict[str, dict]) -> dict[str, dict]:
    files = []
    for name, record in records.items():
        path = tmp_path / f"{name}.flight.json"
        path.write_text(json.dumps(record))
        files.append(path)
    out = subprocess.run(["node", str(JS), "--json", *map(str, files)], capture_output=True, text=True, check=True)
    return {Path(o["file"]).name.removesuffix(".flight.json"): o for o in json.loads(out.stdout)}


def mutate(record: dict, kind: str) -> dict:
    r = copy.deepcopy(record)
    extra = {"rotation": 0, "thrust": 1.0}
    if kind == "trailing_resealed":
        r["trace"] += [extra] * 3
        reseal(r)
    elif kind == "trailing_resealed_with_terminal_steps":
        r["trace"] += [extra] * 3
        reseal(r)
        r["terminal"]["steps"] = len(r["trace"])
    elif kind == "trailing_stale_metadata":
        r["trace"] += [extra] * 3
    elif kind == "truncated_resealed":
        del r["trace"][-15:]
        reseal(r)
    elif kind == "truncated_stale_metadata":
        del r["trace"][-15:]
    elif kind == "trace_length":
        r["trace_length"] += 1
    elif kind == "modified_action":
        r["trace"][len(r["trace"]) // 2] = {"rotation": 90, "thrust": 1.0}
    elif kind == "wrong_hash":
        r["trace_hash"] = "sha256:" + "0" * 64
    elif kind == "terminal_steps":
        r["terminal"]["steps"] -= 1
    else:  # pragma: no cover
        raise AssertionError(kind)
    return r


INVALID = [
    "trailing_resealed", "trailing_resealed_with_terminal_steps", "trailing_stale_metadata",
    "truncated_resealed", "truncated_stale_metadata", "trace_length", "modified_action", "wrong_hash",
    "terminal_steps",
]


@pytest.mark.parametrize("name", ["landing", "crash", "timeout", "tracked_timeout"])
def test_genuine_records_end_exactly_at_termination_and_verify_everywhere(adapter, genuine, tmp_path, name) -> None:
    record = genuine[name]
    assert len(record["trace"]) == record["trace_length"] == record["terminal"]["steps"]
    result = adapter.verify_flight_record(record)
    assert result["matched"] is True, result["mismatches"]
    assert js_verdicts(tmp_path, {name: record})[name]["matched"] is True


@pytest.mark.parametrize("kind", INVALID)
@pytest.mark.parametrize("name", ["landing", "crash", "timeout"])
def test_python_rejects_and_agrees_with_browser_engine(adapter, genuine, tmp_path, name, kind) -> None:
    bad = mutate(genuine[name], kind)
    result = adapter.verify_flight_record(bad)
    assert result["matched"] is False, f"python accepted {kind} on {name}"
    assert result["mismatches"], "a rejection must carry a specific reason"
    js = js_verdicts(tmp_path, {"bad": bad})["bad"]
    assert js["matched"] is False, f"browser engine accepted {kind} on {name}"


def test_resealed_trailing_actions_get_a_specific_reason(adapter, genuine) -> None:
    for name in ("landing", "crash", "timeout"):
        result = adapter.verify_flight_record(mutate(genuine[name], "trailing_resealed"))
        assert any("trailing action" in m for m in result["mismatches"]), result["mismatches"]


def test_truncated_resealed_trace_reports_truncation(adapter, genuine) -> None:
    result = adapter.verify_flight_record(mutate(genuine["landing"], "truncated_resealed"))
    assert any("truncated" in m or "terminal" in m for m in result["mismatches"]), result["mismatches"]


def test_terminal_steps_must_match_the_recorded_action_count(adapter, genuine) -> None:
    result = adapter.verify_flight_record(mutate(genuine["crash"], "terminal_steps"))
    assert any("terminal.steps" in m or "steps" in m for m in result["mismatches"])


def test_existing_valid_evidence_still_verifies(adapter) -> None:
    assert adapter.verify_flight_record(TRACKED)["matched"] is True


def test_recorded_fuel_totals_are_verified(adapter, genuine, tmp_path) -> None:
    for field in ("fuel_remaining", "fuel_used"):
        bad = copy.deepcopy(genuine["landing"])
        bad["terminal"][field] += 7.0
        result = adapter.verify_flight_record(bad)
        assert result["matched"] is False
        assert any(field in m for m in result["mismatches"]), result["mismatches"]
        assert js_verdicts(tmp_path, {"bad": bad})["bad"]["matched"] is False


@pytest.mark.parametrize("breakage", ["missing_terminal", "trace_not_list", "action_missing_key", "missing_seed"])
def test_malformed_records_are_rejected_with_a_reason_not_an_exception(adapter, genuine, breakage) -> None:
    bad = copy.deepcopy(genuine["crash"])
    if breakage == "missing_terminal":
        del bad["terminal"]
    elif breakage == "trace_not_list":
        bad["trace"] = "abc"
    elif breakage == "action_missing_key":
        bad["trace"][3] = {"rotation": 0}
        reseal(bad)
    else:
        del bad["episode_seed"]
    result = adapter.verify_flight_record(bad)
    assert result["matched"] is False and result["mismatches"]


def test_known_unauthenticated_fields_are_documented_not_silently_trusted(adapter, genuine) -> None:
    """Pins current behaviour: provenance labels and the controller field are not re-derived.

    A record's `controller`, `model` and `origin` are claims; verification proves that the
    recorded ACTIONS reproduce the recorded outcome, not that the named controller or model
    produced them. If this ever starts failing because the verifier gained that ability,
    update docs/OPERATING.md accordingly.
    """
    relabeled = copy.deepcopy(genuine["crash"])
    relabeled["model"], relabeled["origin"] = "some-llm", "model_generated"
    assert adapter.verify_flight_record(relabeled)["matched"] is True
