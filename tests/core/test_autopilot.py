"""Automatic matched rounds: every guard still runs, nothing is spent past the owner's limits.

The real run CLI, live preflight, AggregateCeilingGate, ledger and Node physics run here; only the
HTTP transport is fake, so no request leaves the process and no key is used.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Callable

import pytest
import yaml

from rewardbench import autopilot, study
from rewardbench.core.locking import ExperimentRunLock
from rewardbench.environments.apollolander.schema import GUIDANCE_BOUNDS, SCHEMA_ID, constant_controller
from rewardbench.run.ceiling import ledger_spent_usd
from rewardbench.run.cli import main as real_run_main

from tests.core.test_live_cli import TEST_KEY
from tests.providers.conftest import http_json
from tests.providers.e2e_helpers import openai_reply

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")

HEADERS = {
    "no_feedback": "Scores were withheld on purpose.",
    "reward_only": "include only the simulator's numeric reward",
    "numerical_reward": "include the simulator's numeric reward",
}


def guidance(scale: float = 0.5) -> dict:
    return {"schema": SCHEMA_ID, "policy": "guidance",
            "parameters": {k: lo + (hi - lo) * scale for k, (lo, hi) in GUIDANCE_BOUNDS.items()}}


class ArmTransport:
    """Fake OpenAI endpoint that answers per arm and records (arm, revision) for every request it receives."""

    def __init__(self, reply: Callable[[str, int], object]) -> None:
        self.reply = reply
        self.calls: list[tuple[str, int]] = []

    def send(self, request):
        user = json.loads(request.body)["messages"][-1]["content"]
        arm = next(name for name, header in HEADERS.items() if header in user)
        revision = int(re.search(r"^Revision: (\d+)$", user, re.M).group(1))
        self.calls.append((arm, revision))
        return self.reply(arm, revision)


def ok(controller: dict, *, prompt: int = 120, completion: int = 80) -> object:
    return http_json(openai_reply(controller, prompt=prompt, completion=completion, reasoning=0))


def write_arms(tmp_path: Path, *, revisions: int = 2, seeds: int = 2, steps: int = 300) -> list[Path]:
    """Real study arms, shortened: fewer revisions, seeds and steps so physics stays fast."""
    paths = []
    for condition in study.CONDITIONS:
        config = study.study_config("pilot", condition)
        config.update(num_revisions=revisions, development_seeds=list(range(seeds)), episodes_per_revision=seeds,
                      max_episode_steps=steps)
        config["metadata"]["adapter_kwargs"]["max_steps"] = steps
        config["budget"] = {"max_cost_usd": 1.0, "max_tokens": 10_000_000, "max_wall_seconds": 3600,
                            "max_revisions": revisions, "max_episodes": revisions * seeds, "max_model_calls": revisions}
        path = tmp_path / "configs" / f"{condition}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
        paths.append(path)
    return paths


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def make(reply, *, revisions: int = 2, name: str = "ledger", **settings):
        transport = ArmTransport(reply)
        monkeypatch.setattr(autopilot, "run_main", lambda argv: real_run_main(
            argv, _api_key=TEST_KEY, _transport=transport, _sleeper=lambda _s: None))
        root = tmp_path / name
        out = root / "pilot"
        root.mkdir()
        arms = autopilot.load_arms(write_arms(tmp_path / f"{name}-configs", revisions=revisions), out)
        values = {"ceiling_usd": 1.0, "max_total_calls": 100, "ledger_root": root, "out": out, **settings}
        return transport, arms, autopilot.Settings(**values)

    return make


def statuses(arms) -> dict[str, tuple[str | None, int]]:
    return {a.condition: (autopilot.read_state(a).status, autopilot.read_state(a).next_revision) for a in arms}


def test_completes_matched_rounds_with_rotated_arm_order(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance(0.3 + 0.1 * rev)))
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.PLANNED and "all arms completed 2 revisions" in outcome.stop_reason
    assert transport.calls == [("no_feedback", 0), ("reward_only", 0), ("numerical_reward", 0),
                               ("reward_only", 1), ("numerical_reward", 1), ("no_feedback", 1)]
    assert outcome.calls_made == 6 and outcome.rounds_completed == 2
    assert all(state == ("completed", 2) for state in statuses(arms).values())
    assert outcome.spent_after == pytest.approx(ledger_spent_usd(settings.ledger_root)[0])
    journal = [json.loads(line) for line in (settings.out / autopilot.JOURNAL).read_text().splitlines()]
    assert [e["event"] for e in journal].count("call") == 6 and journal[-1]["event"] == "stop"


def test_stops_before_a_round_that_cannot_fit_and_never_advances_one_arm(harness) -> None:
    probe, probe_arms, probe_settings = harness(lambda arm, rev: ok(guidance()), name="probe")
    planned = autopilot.run_autopilot(probe_arms, probe_settings, plan_only=True, say=lambda _m: None)
    first_round = sum(planned.events[0]["quotes_usd"].values())  # exact worst case of the three first calls
    # Round 0 fits; the next round's quotes are at least as large and spend has grown, so it cannot.
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()), ceiling_usd=first_round + 0.001)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.PLANNED and "No request was sent" in outcome.stop_reason
    assert len(transport.calls) == 3 and {rev for _arm, rev in transport.calls} == {0}
    assert {state[1] for state in statuses(arms).values()} == {1}  # still matched
    assert outcome.spent_after <= settings.ceiling_usd
    # A ceiling that fits two of three first calls sends nothing at all.
    transport2, arms2, settings2 = harness(lambda arm, rev: ok(guidance()), ceiling_usd=first_round * 0.9,
                                           name="ledger2")
    assert autopilot.run_autopilot(arms2, settings2, say=lambda _m: None).calls_made == 0
    assert transport2.calls == []


def test_owner_call_limit_stops_at_a_round_boundary(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()), max_total_calls=5)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert len(transport.calls) == 3 and outcome.calls_made == 3
    assert "--max-total-calls 5" in outcome.stop_reason and outcome.code == autopilot.PLANNED


def test_counts_spend_from_earlier_runs_under_the_ledger_root(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()), ceiling_usd=0.035)
    old = settings.ledger_root / "pilot-old"
    old.mkdir()
    with closing(sqlite3.connect(old / "earlier.sqlite")) as db, db:
        db.execute("CREATE TABLE attempts (provider TEXT, estimated_cost_usd REAL)")
        db.execute("INSERT INTO attempts VALUES ('openai', 0.01)")
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert transport.calls == [] and "recorded spend $0.010000" in outcome.stop_reason


def test_provider_error_is_terminal_with_no_retry_and_no_further_calls(harness) -> None:
    def reply(arm, rev):
        if arm == "reward_only":
            return http_json({"error": {"message": "limit", "code": "project_spend_limit_exceeded"}},
                             status=429, headers={"Retry-After": "0"})
        return ok(guidance())

    transport, arms, settings = harness(reply)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.SAFETY
    assert transport.calls == [("no_feedback", 0), ("reward_only", 0)]  # one try, then stop
    assert statuses(arms)["reward_only"][0] == "failed"
    # Re-running refuses to continue the broken matched comparison.
    again = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert again.code == autopilot.SAFETY and "terminal" in again.stop_reason and len(transport.calls) == 2


def test_corrupted_ledger_stops_before_any_request(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()))
    (settings.ledger_root / "broken.sqlite").write_text("not a database")
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.SAFETY and "spending ledger problem" in outcome.stop_reason
    assert transport.calls == []


def test_spending_outside_this_session_is_detected(harness, monkeypatch) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()))
    real = autopilot._execute

    def execute_then_someone_else_spends(arm, state, s):
        code = real(arm, state, s)
        with closing(sqlite3.connect(settings.ledger_root / "intruder.sqlite")) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS attempts (provider TEXT, estimated_cost_usd REAL)")
            db.execute("INSERT INTO attempts VALUES ('openai', 0.001)")
        return code

    monkeypatch.setattr(autopilot, "_execute", execute_then_someone_else_spends)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.SAFETY and "something else is spending" in outcome.stop_reason
    assert len(transport.calls) == 1


def test_a_reply_billed_above_its_reservation_is_an_unsafe_stop(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance(), prompt=400_000))
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert outcome.code == autopilot.SAFETY and len(transport.calls) == 1


@pytest.mark.parametrize("scope, expected_calls", [("all", 9), ("any", 6)])
def test_early_stop_on_unchanged_controllers_respects_scope(harness, scope, expected_calls) -> None:
    # no_feedback repeats itself; the other arms keep changing.
    def reply(arm, rev):
        return ok(guidance(0.5 if arm == "no_feedback" else 0.3 + 0.2 * rev))

    transport, arms, settings = harness(reply, revisions=3, stop_after_unchanged=1, early_stop_scope=scope)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert len(transport.calls) == expected_calls
    if scope == "any":
        assert "early stop (any arms)" in outcome.stop_reason and "unchanged" in outcome.stop_reason
    else:
        assert "all arms completed" in outcome.stop_reason


def test_early_stop_on_repeated_invalid_controllers(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(constant_controller(0.5, 0)), revisions=4)
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert "2 invalid controllers in a row" in outcome.stop_reason and outcome.code == autopilot.PLANNED
    assert len(transport.calls) == 6  # two matched rounds, then stop instead of paying for rounds 3 and 4


def test_an_interrupted_round_is_completed_before_a_new_one(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()))
    # An operator made one manual call for the first arm only.
    assert autopilot._execute(arms[0], autopilot.read_state(arms[0]), settings) == 0
    outcome = autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert transport.calls[:3] == [("no_feedback", 0), ("reward_only", 0), ("numerical_reward", 0)]
    assert transport.calls[3:] == [("reward_only", 1), ("numerical_reward", 1), ("no_feedback", 1)]
    assert outcome.calls_made == 5


def test_a_second_autopilot_on_the_same_ledger_is_refused(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()))
    with ExperimentRunLock("autopilot", settings.ledger_root):
        with pytest.raises(Exception, match="another autopilot"):
            autopilot.run_autopilot(arms, settings, say=lambda _m: None)
    assert transport.calls == []


def test_plan_quotes_without_sending_or_writing(harness) -> None:
    transport, arms, settings = harness(lambda arm, rev: ok(guidance()))
    outcome = autopilot.run_autopilot(arms, settings, plan_only=True, say=lambda _m: None)
    assert "plan: revision 0 for 3 arm(s) fits" in outcome.stop_reason
    assert transport.calls == [] and not settings.out.exists()


def test_cli_requires_explicit_owner_limits_and_both_paid_flags(tmp_path: Path, capsys) -> None:
    configs = [str(p) for p in write_arms(tmp_path)]
    root = tmp_path / "ledger"
    root.mkdir()
    base = ["run", "--mode", "live", "--out", str(root / "pilot")] + sum((["--config", c] for c in configs), [])
    limits = ["--total-usd-ceiling", "0.1", "--max-total-calls", "3"]
    assert autopilot.main(base + limits + ["--i-authorize-paid-api-calls"]) == 2
    assert "--authorize-automatic-revisions" in capsys.readouterr().err
    for missing in (["--max-total-calls", "3"], ["--total-usd-ceiling", "0.1"]):
        with pytest.raises(SystemExit):
            autopilot.main(base + missing + ["--i-authorize-paid-api-calls", "--authorize-automatic-revisions"])
    outside = ["--ledger-root", str(tmp_path / "configs")]
    assert autopilot.main(base + limits + outside + ["--i-authorize-paid-api-calls",
                                                     "--authorize-automatic-revisions"]) == 2
    assert "inside --ledger-root" in capsys.readouterr().err


def test_arms_must_be_matched_and_never_list_reserved_development_seeds(tmp_path: Path) -> None:
    paths = write_arms(tmp_path)
    data = yaml.safe_load(paths[1].read_text())
    data["history_window"] += 1
    paths[1].write_text(yaml.safe_dump(data))
    with pytest.raises(Exception, match="history_window"):
        autopilot.load_arms(paths, tmp_path / "out")
    with pytest.raises(Exception, match="duplicate experiment_name"):
        autopilot.load_arms([paths[0], paths[0]], tmp_path / "out")
    reserved = yaml.safe_load(paths[0].read_text())
    reserved["development_seeds"] = [0, study.RESERVED_FINAL_SEEDS[0]]
    paths[0].write_text(yaml.safe_dump(reserved))
    with pytest.raises(Exception):
        autopilot.load_arms(paths[:1], tmp_path / "out")
    # Automatic mode has no held-out path at all: final evaluation needs its own approval and command.
    assert "rewardbench.heldout" not in Path(autopilot.__file__).read_text(encoding="utf-8")
