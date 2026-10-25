"""The browser replay (frontend replay.js) must agree with the Python replay verifier."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import constant_controller, demonstration_guidance_controller

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "frontend" / "apollolander" / "experiment" / "replay.test.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def _records(tmp_path: Path) -> list[Path]:
    adapter = make_environment("ApolloLander", research_mode=True, max_steps=8000)
    reports = [
        adapter.evaluate(demonstration_guidance_controller(), [0, 1], revision=1, max_steps=8000, split="development"),
        adapter.evaluate(constant_controller(0.0, 0), [2], revision=2, max_steps=8000, split="development"),
    ]
    files = []
    for report in reports:
        for episode in report["episodes"]:
            path = tmp_path / f"r{episode['revision']}_s{episode['seed']}.flight.json"
            path.write_text(json.dumps(episode["flight_record"]))
            files.append(path)
    return files


def test_browser_replay_matches_python_verifier_on_landing_and_failure(tmp_path: Path) -> None:
    files = _records(tmp_path)
    assert len(files) >= 3
    adapter = make_environment("ApolloLander", research_mode=True)
    out = subprocess.run(
        ["node", str(SCRIPT), "--json", *map(str, files)], capture_output=True, text=True, check=True
    )
    browser = {Path(o["file"]).name: o for o in json.loads(out.stdout)}
    statuses = set()
    for file in files:
        python = adapter.verify_flight_record(file)
        record = json.loads(file.read_text())
        outcome = browser[file.name]
        assert python["matched"] is True
        assert outcome["matched"] is True, outcome["mismatches"]
        assert outcome["steps"] == record["terminal"]["steps"]
        assert outcome["status"] == record["terminal"]["status"]
        assert outcome["reward"] == pytest.approx(record["terminal"]["reward"], abs=1e-9)
        statuses.add(outcome["status"])
    assert len(statuses) >= 2, f"expected varied outcomes, got {statuses}"


def test_tracked_evidence_flight_replays_in_the_browser_engine() -> None:
    subprocess.run(["node", str(SCRIPT)], check=True, capture_output=True)


def _run_js(files: list[Path]) -> dict[str, dict]:
    out = subprocess.run(["node", str(SCRIPT), "--json", *map(str, files)], capture_output=True, text=True, check=True)
    return {Path(o["file"]).name: o for o in json.loads(out.stdout)}


def test_tampered_records_are_rejected_by_browser_engine_and_python_verifier(tmp_path: Path) -> None:
    from rewardbench.environments.apollolander.flight_record import trace_hash

    base = _records(tmp_path)
    crashed = next(f for f in base if json.loads(f.read_text())["terminal"]["status"] == "crashed")
    record = json.loads(crashed.read_text())
    adapter = make_environment("ApolloLander", research_mode=True)

    def reseal(r: dict) -> None:
        r["trace_length"] = len(r["trace"])
        r["trace_hash"] = trace_hash(r["trace"])

    def trace_length(r): r["trace_length"] += 1
    def wrong_hash(r): r["trace_hash"] = "sha256:" + "0" * 64
    def terminal_reward(r): r["terminal"]["reward"] += 0.5
    def truncated(r): del r["trace"][-20:]; reseal(r)
    def trailing(r): r["trace"].extend([{"rotation": 0, "thrust": 1.0}] * 3); reseal(r)

    cases = {"trace_length": trace_length, "wrong_hash": wrong_hash, "terminal_reward": terminal_reward,
             "truncated": truncated, "trailing": trailing}
    files = {}
    for name, mutate in cases.items():
        copy = json.loads(json.dumps(record))
        mutate(copy)
        path = tmp_path / f"mut_{name}.flight.json"
        path.write_text(json.dumps(copy))
        files[name] = path
    verdicts = _run_js(list(files.values()))
    for name, path in files.items():
        assert verdicts[path.name]["matched"] is False, f"browser engine accepted {name}"
    # Python verifier agrees for every tamper it is able to see.
    for name in ("trace_length", "wrong_hash", "terminal_reward", "truncated"):
        assert adapter.verify_flight_record(files[name])["matched"] is False, f"python accepted {name}"
    # Known gap in the Python verifier: resealed trailing actions after termination are not detected there.
    # The browser engine reports them; recorded here so a future Python change is noticed.
    assert any("trailing" in m for m in verdicts[files["trailing"].name]["mismatches"])
