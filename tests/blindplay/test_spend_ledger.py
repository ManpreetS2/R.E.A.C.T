"""The spending ledger: reservation before call, crash safety, tamper detection, shared cumulative caps."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from decimal import Decimal
from pathlib import Path

import pytest

from rewardbench.blindplay import spend_ledger as sl

SRC = Path(sl.__file__).resolve().parents[2]


def _ledger(tmp_path, name="ledger.jsonl", mode=sl.MODE_OFFLINE_MOCK):
    return sl.SpendLedger(tmp_path / name, mode=mode)


def _reserve(ledger, worst="0.01", session="s1", call=1, session_cap="1", cumulative_cap="1"):
    return ledger.reserve(session=session, call=call, worst_case=worst, session_cap=session_cap, cumulative_cap=cumulative_cap)


def test_reservation_counts_as_spent_until_settled_and_settle_replaces_it(tmp_path):
    ledger = _ledger(tmp_path)
    rid = _reserve(ledger, "0.05")
    state = ledger.state()
    assert (state.reserved, state.spent, state.committed) == (Decimal("0.05"), 0, Decimal("0.05"))
    ledger.settle(rid, charged="0.001", basis="provider_usage")
    state = ledger.state()
    assert (state.reserved, state.spent, state.session_total["s1"]) == (0, Decimal("0.001"), Decimal("0.001"))


@pytest.mark.parametrize("scope,kwargs", [
    ("session", {"worst": "0.06", "session_cap": "0.10", "cumulative_cap": "1"}),
    ("cumulative", {"worst": "0.06", "session_cap": "1", "cumulative_cap": "0.10"}),
])
def test_call_that_would_cross_a_cap_is_refused_and_nothing_is_written(tmp_path, scope, kwargs):
    ledger = _ledger(tmp_path)
    _reserve(ledger, "0.05", call=1, session_cap="1", cumulative_cap="1")
    before = ledger.path.read_bytes()
    with pytest.raises(sl.BudgetExceeded) as err:
        _reserve(ledger, call=2, **kwargs)
    assert err.value.scope == scope
    assert ledger.path.read_bytes() == before


def test_exactly_at_the_cap_is_allowed_one_nano_dollar_more_is_not(tmp_path):
    ledger = _ledger(tmp_path)
    _reserve(ledger, "0.10", session_cap="0.10", cumulative_cap="0.10")
    with pytest.raises(sl.BudgetExceeded):
        _reserve(ledger, "0.000000001", call=2, session_cap="0.20", cumulative_cap="0.10")


def test_cumulative_cap_spans_sessions_and_ledger_reopens(tmp_path):
    _reserve(_ledger(tmp_path), "0.08", session="a")
    reopened = _ledger(tmp_path)
    with pytest.raises(sl.BudgetExceeded) as err:
        _reserve(reopened, "0.08", session="b", cumulative_cap="0.10")
    assert err.value.scope == "cumulative"
    _reserve(reopened, "0.08", session="b", cumulative_cap="0.20")


def test_process_death_after_reserving_stays_charged_at_worst_case(tmp_path):
    """The call may have gone out before the crash, so it counts in full until the owner reconciles it."""
    path = tmp_path / "ledger.jsonl"
    code = ("import os,sys\nfrom rewardbench.blindplay import spend_ledger as sl\n"
            "l=sl.SpendLedger(sys.argv[1],mode=sl.MODE_OFFLINE_MOCK)\n"
            "print(l.reserve(session='s',call=1,worst_case='0.07',session_cap='1',cumulative_cap='1'),flush=True)\n"
            "os._exit(9)\n")
    done = subprocess.run([sys.executable, "-c", code, str(path)], capture_output=True, text=True, timeout=60,
                          env={"PYTHONPATH": str(SRC), "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert done.returncode == 9, done.stderr
    rid = done.stdout.strip()
    ledger = sl.SpendLedger(path, mode=sl.MODE_OFFLINE_MOCK)   # the kernel released the lock; no stale lock blocks this
    state = ledger.state()
    assert state.committed == Decimal("0.07") and rid in state.open_reservations
    with pytest.raises(sl.BudgetExceeded):
        _reserve(ledger, "0.04", session="next", cumulative_cap="0.10")
    ledger.reconcile(rid, charged="0.002", note="provider console, request req_x")
    state = ledger.state()
    assert (state.spent, state.reserved, state.open_reservations) == (Decimal("0.002"), 0, {})


def test_torn_final_write_is_sealed_and_is_never_treated_as_a_charge_or_a_refund(tmp_path):
    ledger = _ledger(tmp_path)
    rid = _reserve(ledger, "0.05")
    with open(ledger.path, "ab") as f:
        f.write(b'{"event":"settle","reservation":"' + rid.encode() + b'","charged_us')   # the crash, mid-write
    reopened = _ledger(tmp_path)
    assert reopened.state().committed == Decimal("0.05"), "the half-written settle changes nothing"
    reopened.settle(rid, charged="0.01", basis="provider_usage")
    assert reopened.state().spent == Decimal("0.01")
    assert b"torn_write_sealed" in ledger.path.read_bytes()
    _ledger(tmp_path).state()   # stays valid on every later read


@pytest.mark.parametrize("edit", ["lower_a_charge", "delete_a_middle_record", "damage_a_middle_record"])
def test_tampering_fails_closed(tmp_path, edit):
    ledger = _ledger(tmp_path)
    rid = _reserve(ledger, "0.05")
    ledger.settle(rid, charged="0.05", basis="provider_usage")
    _reserve(ledger, "0.01", call=2)
    lines = ledger.path.read_bytes().split(b"\n")
    if edit == "lower_a_charge":
        lines[2] = lines[2].replace(b'"charged_usd":"0.050000000"', b'"charged_usd":"0.000000000"')
    elif edit == "delete_a_middle_record":
        del lines[2]
    else:
        lines[2] = lines[2][:20]
    ledger.path.write_bytes(b"\n".join(lines))
    with pytest.raises(sl.LedgerCorrupt):
        ledger.state()
    with pytest.raises(sl.LedgerCorrupt):
        _reserve(ledger, "0.01", call=3)
    with pytest.raises(sl.LedgerCorrupt):
        _ledger(tmp_path)


def test_mock_and_live_money_never_share_a_ledger(tmp_path):
    _ledger(tmp_path)
    with pytest.raises(sl.LedgerCorrupt, match="offline-mock"):
        _ledger(tmp_path, mode=sl.MODE_LIVE)
    with pytest.raises(ValueError):
        _ledger(tmp_path, "x.jsonl", mode="free-money")


@pytest.mark.parametrize("bad", [0.1, True, "NaN", "Infinity", "-1"])
def test_money_must_be_exact_finite_and_non_negative(bad):
    with pytest.raises((ValueError, ArithmeticError)):
        sl.usd(bad)


def test_money_rounds_up_never_down():
    assert sl.usd("0.0000000001") == Decimal("0.000000001")


def test_settling_twice_or_settling_nothing_is_refused(tmp_path):
    ledger = _ledger(tmp_path)
    rid = _reserve(ledger)
    ledger.settle(rid, charged="0", basis="not_billed")
    with pytest.raises(sl.LedgerCorrupt):
        ledger.settle(rid, charged="0", basis="not_billed")
    with pytest.raises(sl.LedgerCorrupt):
        ledger.settle("nope", charged="0", basis="not_billed")


def test_reconcile_needs_a_note_and_keeps_the_earlier_entries(tmp_path):
    ledger = _ledger(tmp_path)
    rid = _reserve(ledger, "0.05")
    ledger.settle(rid, charged="0.05", basis="timeout:worst_case_unverified")
    with pytest.raises(ValueError):
        ledger.reconcile(rid, charged="0.01", note="  ")
    ledger.reconcile(rid, charged="0.01", note="invoice line 3")
    assert ledger.state().spent == Decimal("0.01") and ledger.state().session_total["s1"] == Decimal("0.01")
    events = [json.loads(x)["event"] for x in ledger.path.read_text(encoding="utf-8").splitlines()]
    assert events == ["ledger_created", "reserve", "settle", "reconcile"]


def test_opening_balance_counts_and_only_goes_into_a_new_ledger(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.record_opening_balance("0.106019", "Missions 006-012, docs/assets/research-results/RESULTS.md")
    assert ledger.state().spent == Decimal("0.106019")
    with pytest.raises(sl.BudgetExceeded):
        _reserve(ledger, "0.1", cumulative_cap="0.2")
    _reserve(ledger, "0.01", cumulative_cap="0.2")
    with pytest.raises(ValueError):
        ledger.record_opening_balance("1", "again")


def test_concurrent_sessions_cannot_jointly_exceed_the_cumulative_cap(tmp_path):
    ledger = _ledger(tmp_path)
    accepted, errors = [], []

    def worker(n):
        for call in range(10):
            try:
                accepted.append(sl.SpendLedger(ledger.path, mode=sl.MODE_OFFLINE_MOCK).reserve(
                    session=f"s{n}", call=call, worst_case="0.01", session_cap="1", cumulative_cap="0.25"))
            except sl.BudgetExceeded:
                pass
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(accepted) == 25 and ledger.state().committed == Decimal("0.25")
