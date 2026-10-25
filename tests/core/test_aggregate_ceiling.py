"""One owner-approved USD ceiling spans every live experiment; refusal happens before any request."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from rewardbench import operate, study
from rewardbench.contracts import BudgetExceeded, ExperimentStatus, ConfigError
from rewardbench.run.ceiling import AGGREGATE_RESOURCE, AggregateCeilingGate, ledger_spent_usd

from tests.core.test_live_cli import TEST_KEY
from tests.providers.conftest import FakeTransport, http_json, make_request
from tests.providers.e2e_helpers import openai_reply, stronger_controller, weak_controller

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="ApolloLander physics runs in Node")


def _db(path: Path, rows: list[tuple[str, float]]) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE attempts (provider TEXT, estimated_cost_usd REAL)")
        db.executemany("INSERT INTO attempts VALUES (?, ?)", rows)


def test_ledger_sums_live_spend_across_databases_and_ignores_mock(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    _db(tmp_path / "a" / "one.sqlite", [("openai", 0.01), ("mock", 5.0)])
    _db(tmp_path / "two.sqlite", [("openai", 0.0025)])
    # Invalid .sqlite files are a safety problem: never silently omit spend.
    (tmp_path / "notes.sqlite").write_text("not a database")
    with pytest.raises(ConfigError, match="cannot read spending ledger"):
        ledger_spent_usd(tmp_path)
    (tmp_path / "notes.sqlite").unlink()
    spent, count = ledger_spent_usd(tmp_path)
    assert spent == pytest.approx(0.0125) and count == 2


def test_ledger_rejects_incomplete_and_invalid_cost_records(tmp_path: Path) -> None:
    unfinished = tmp_path / "partial.sqlite"
    with sqlite3.connect(unfinished) as db:
        db.execute("CREATE TABLE experiments (id TEXT)")
    with pytest.raises(ConfigError, match="incomplete experiment"):
        ledger_spent_usd(tmp_path)
    unfinished.unlink()
    _db(tmp_path / "negative.sqlite", [("openai", -0.50)])
    with pytest.raises(ConfigError, match="invalid cost record"):
        ledger_spent_usd(tmp_path)
    (tmp_path / "negative.sqlite").unlink()
    _db(tmp_path / "null.sqlite", [("openai", None)])
    with pytest.raises(ConfigError, match="invalid cost record"):
        ledger_spent_usd(tmp_path)


class _Inner:
    provider, model_id = "openai", "gpt-5.4-mini"

    def __init__(self) -> None:
        self.calls = 0

    def propose(self, request):
        self.calls += 1
        return "response"


def test_gate_refuses_before_the_inner_client_is_called(tmp_path: Path) -> None:
    _db(tmp_path / "x.sqlite", [("openai", 0.010)])
    inner = _Inner()
    request = make_request(settings={"max_output_tokens": 800, "reasoning_effort": "none"})
    with pytest.raises(BudgetExceeded) as raised:
        AggregateCeilingGate(inner, ceiling_usd=0.011, ledger_root=tmp_path).propose(request)
    assert raised.value.resource == AGGREGATE_RESOURCE and inner.calls == 0
    assert AggregateCeilingGate(inner, ceiling_usd=1.0, ledger_root=tmp_path).propose(request) == "response"
    assert inner.calls == 1


def test_gate_rejects_nonpositive_ceilings(tmp_path: Path) -> None:
    for bad in (0, -1, True, float('nan'), float('inf'), -float('inf')):
        with pytest.raises(Exception):
            AggregateCeilingGate(_Inner(), ceiling_usd=bad, ledger_root=tmp_path)


def test_operator_requires_a_ceiling_in_live_mode_and_rejects_it_in_mock(tmp_path: Path, capsys) -> None:
    config = str(study.config_path("pilot", "no_feedback"))
    assert operate.main(["run", "--mode", "live", "--i-authorize-paid-api-calls", "--config", config,
                         "--out", str(tmp_path / "o")]) == 2
    assert "--total-usd-ceiling" in capsys.readouterr().err
    assert not (tmp_path / "o").exists() or not list((tmp_path / "o").glob("*.sqlite"))
    mock = Path(__file__).resolve().parents[2] / "configs" / "apollolander_offline_development_nofeedback.yaml"
    assert operate.main(["run", "--config", str(mock), "--total-usd-ceiling", "1", "--out", str(tmp_path / "m")]) == 2


@needs_node
def test_ceiling_spans_arms_pauses_resumably_and_never_sends_a_refused_request(tmp_path: Path, monkeypatch) -> None:
    """Costly fake replies (~$0.0074/call) against a $0.0125 ceiling: arm A and B fit one call each,
    the next paid call is refused because its worst case no longer fits."""
    costly = lambda c: http_json(openai_reply(c, prompt=5000, completion=800, reasoning=0))  # noqa: E731
    transport = FakeTransport([costly(weak_controller()), costly(weak_controller()), costly(stronger_controller())])
    real = operate.run_main
    monkeypatch.setattr(operate, "run_main", lambda argv, **kw: real(
        argv, _api_key=TEST_KEY, _transport=transport, _sleeper=lambda _s: None, **kw))
    out = tmp_path / "study" / "pilot"
    arms = [str(study.config_path("pilot", c)) for c in ("no_feedback", "reward_only")]
    base = ["run", "--mode", "live", "--i-authorize-paid-api-calls", "--total-usd-ceiling", "0.0125", "--out", str(out)]
    operate.main(base + ["--config", arms[0]])
    assert len(transport.requests) == 1
    spent, _ = ledger_spent_usd(tmp_path / "study")
    assert 0.007 < spent < 0.0075
    # Different experiment, same ledger: worst case (~$0.006) + $0.0074 spent > $0.0125 -> refused, nothing sent.
    operate.main(base + ["--config", arms[1]])
    assert len(transport.requests) == 1, "a refused call must not reach the provider"
    second = next(out.glob("*rewardonly*.sqlite"))
    with sqlite3.connect(second) as db:
        assert db.execute("SELECT status FROM experiments").fetchone()[0] == ExperimentStatus.INTERRUPTED.value
        assert db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
    # Raising the ceiling (owner action) lets the paused experiment resume.
    base[base.index("0.0125")] = "1"
    operate.main(base + ["--authorize-continuation", "--config", arms[1]])
    assert len(transport.requests) == 2


@needs_node
@pytest.mark.parametrize("code", ["project_spend_limit_exceeded", "credit_balance_exhausted"])
def test_provider_billing_429_makes_no_retry_costs_nothing_and_ends_the_session_failed(tmp_path: Path, monkeypatch, code) -> None:
    """Documents the real behaviour the launch guide warns about: an unbilled 429 is terminal, not a pause."""
    refusal = http_json({"error": {"message": "limit", "code": code}}, status=429, headers={"Retry-After": "0"})
    transport = FakeTransport([refusal, http_json(openai_reply(weak_controller()))])
    real = operate.run_main
    monkeypatch.setattr(operate, "run_main", lambda argv, **kw: real(
        argv, _api_key=TEST_KEY, _transport=transport, _sleeper=lambda _s: None, **kw))
    out = tmp_path / "ledger" / "pilot"
    operate.main(["run", "--mode", "live", "--i-authorize-paid-api-calls", "--total-usd-ceiling", "1",
                  "--config", str(study.config_path("pilot", "no_feedback")), "--out", str(out)])
    assert len(transport.requests) == 1  # no hidden retry
    with sqlite3.connect(next(out.glob("*.sqlite"))) as db:
        assert db.execute("SELECT status FROM experiments").fetchone()[0] == ExperimentStatus.FAILED.value
    assert ledger_spent_usd(tmp_path / "ledger")[0] == 0.0
