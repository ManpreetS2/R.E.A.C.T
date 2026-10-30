"""Durable, fail-closed spending ledger for model calls.

TRUSTED HOST SIDE. An append-only JSON-lines file, hash-chained, fsynced, and re-read under an OS file lock on every
operation, so concurrent or resumed sessions share one cumulative total.

The rule that makes the caps safe: **a reservation for the call's worst-case cost is durable before the call is made,
and it counts as spent until it is settled.** A crash at any moment therefore overstates spending, never understates it.
An unsettled reservation stays charged at its worst case until the owner records the invoice with ``reconcile``.

A ledger is bound at creation to a ``mode``. Offline mock money and real money can never share a file.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from typing import Any, Iterator

SCHEMA = "react.blindplay.spend-ledger.v1"
MODE_OFFLINE_MOCK = "offline-mock"
MODE_LIVE = "live"
_GENESIS = "0" * 64
_MICRO = Decimal("0.000000001")


class BudgetExceeded(RuntimeError):
    """The call was not made: its worst-case cost does not fit under a cap."""

    def __init__(self, scope: str, detail: str) -> None:
        super().__init__(f"{scope} cap: {detail}")
        self.scope = scope


class LedgerCorrupt(RuntimeError):
    """The ledger cannot be trusted. Nothing may be spent until a human has looked at it; it is never auto-repaired."""


def usd(value: Any) -> Decimal:
    """A non-negative finite USD amount, rounded up to 1e-9. Floats are refused: they cannot represent money exactly."""
    if isinstance(value, (float, bool)):
        raise ValueError("money must be a str, int or Decimal, not a float")
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"not a valid USD amount: {value!r}")
    return amount.quantize(_MICRO, rounding=ROUND_CEILING)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")


@contextmanager
def _locked(path: Path, *, timeout: float = 30.0) -> Iterator[None]:
    """An OS lock, released by the kernel if this process dies. A stale lock can therefore never block recovery."""
    lock = open(path.with_name(path.name + ".lock"), "a+b")
    deadline = time.monotonic() + timeout
    try:
        if sys.platform == "win32":
            import msvcrt
            lock.seek(0)
            while True:
                try:
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerCorrupt(f"could not lock {path.name} within {timeout} s") from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            while True:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() > deadline:
                        raise LedgerCorrupt(f"could not lock {path.name} within {timeout} s") from None
                    time.sleep(0.02)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    finally:
        lock.close()


@dataclass
class LedgerState:
    spent: Decimal = Decimal(0)                     # settled, reconciled and opening balance
    reserved: Decimal = Decimal(0)                  # open reservations at their worst case
    session_total: dict[str, Decimal] = field(default_factory=dict)   # settled + open, per session
    open_reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    settled_reservations: dict[str, dict[str, Any]] = field(default_factory=dict)
    records: int = 0

    @property
    def committed(self) -> Decimal:
        return self.spent + self.reserved


class SpendLedger:
    def __init__(self, path: Path, *, mode: str) -> None:
        if mode not in (MODE_OFFLINE_MOCK, MODE_LIVE):
            raise ValueError(f"unknown ledger mode {mode!r}")
        self.path = Path(path)
        self.mode = mode
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _locked(self.path):
            records, tip, torn = self._read()
            if not records:
                self._append({"event": "ledger_created", "schema": SCHEMA, "mode": mode}, tip, torn)
            elif records[0].get("mode") != mode or records[0].get("schema") != SCHEMA:
                raise LedgerCorrupt(f"{self.path.name} belongs to mode {records[0].get('mode')!r}, not {mode!r}")

    # ------------------------------------------------------------------ file
    def _read(self) -> tuple[list[dict[str, Any]], str, bool]:
        """Verified records, the chain tip, and whether a torn final line (a crash mid-write) must be sealed off."""
        if not self.path.exists():
            return [], _GENESIS, False
        data = self.path.read_bytes()
        lines = data.split(b"\n")
        trailing = lines.pop()              # b"" when the file ends in a newline
        torn = bool(trailing)
        records: list[dict[str, Any]] = []
        tip = _GENESIS
        previous_invalid = False
        for number, line in enumerate(lines, 1):
            try:
                entry = json.loads(line)
                body = {k: v for k, v in entry.items() if k != "sha256"}
                if entry["prev_sha256"] != tip or hashlib.sha256(_canonical(body)).hexdigest() != entry["sha256"]:
                    raise ValueError("hash chain broken")
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                # The only tolerated damage: one unterminated fragment that a later append sealed off with a marker.
                if number == len(lines) or previous_invalid:
                    raise LedgerCorrupt(f"{self.path.name} line {number}: {exc}") from None
                previous_invalid = True
                continue
            if previous_invalid and entry.get("event") != "torn_write_sealed":
                raise LedgerCorrupt(f"{self.path.name} line {number - 1} is damaged")
            previous_invalid = False
            tip = entry["sha256"]
            records.append(entry)
        return records, tip, torn

    def _append(self, record: dict[str, Any], tip: str, torn: bool) -> str:
        if torn:   # the fragment's write never finished, so what it described never happened (see reserve)
            tip = self._write_line({"event": "torn_write_sealed"}, tip, prefix=b"\n")
        return self._write_line(record, tip)

    def _write_line(self, record: dict[str, Any], tip: str, prefix: bytes = b"") -> str:
        body = dict(record, utc=_now(), prev_sha256=tip)
        digest = hashlib.sha256(_canonical(body)).hexdigest()
        with open(self.path, "ab") as f:
            f.write(prefix + _canonical(dict(body, sha256=digest)) + b"\n")
            f.flush()
            os.fsync(f.fileno())
        return digest

    @staticmethod
    def _state(records: list[dict[str, Any]]) -> LedgerState:
        state = LedgerState(records=len(records))
        for r in records:
            event = r["event"]
            if event == "opening_balance":
                state.spent += Decimal(r["amount_usd"])
            elif event == "reserve":
                state.open_reservations[r["reservation"]] = r
                state.reserved += Decimal(r["worst_case_usd"])
                state.session_total[r["session"]] = state.session_total.get(r["session"], Decimal(0)) + Decimal(r["worst_case_usd"])
            elif event in ("settle", "reconcile"):
                reservation = r["reservation"]
                opened = state.open_reservations.pop(reservation, None) or state.settled_reservations.get(reservation)
                if opened is None:
                    raise LedgerCorrupt(f"{event} of unknown reservation {reservation}")
                previous = Decimal(state.settled_reservations[reservation]["charged_usd"]) \
                    if reservation in state.settled_reservations else None
                charged = Decimal(r["charged_usd"])
                if previous is None:
                    state.reserved -= Decimal(opened["worst_case_usd"])
                    state.spent += charged
                    delta = charged - Decimal(opened["worst_case_usd"])
                else:
                    if event == "settle":
                        raise LedgerCorrupt(f"reservation {reservation} settled twice")
                    state.spent += charged - previous
                    delta = charged - previous
                session = opened["session"]
                state.session_total[session] = state.session_total.get(session, Decimal(0)) + delta
                state.settled_reservations[reservation] = {**opened, "charged_usd": r["charged_usd"]}
        return state

    # ------------------------------------------------------------------ operations
    def state(self) -> LedgerState:
        with _locked(self.path):
            return self._state(self._read()[0])

    def record_opening_balance(self, amount: Any, note: str) -> None:
        """Spending recorded elsewhere that counts toward the cumulative cap. Only into an unused ledger."""
        with _locked(self.path):
            records, tip, torn = self._read()
            if len(records) != 1:
                raise ValueError("an opening balance can only be recorded in a new ledger")
            self._append({"event": "opening_balance", "amount_usd": str(usd(amount)), "note": note}, tip, torn)

    def reserve(self, *, session: str, call: int, worst_case: Any, session_cap: Any, cumulative_cap: Any,
                detail: dict[str, Any] | None = None) -> str:
        """Durably reserve ``worst_case`` or raise ``BudgetExceeded``. Must return before the provider is contacted."""
        worst, session_limit, cumulative_limit = usd(worst_case), usd(session_cap), usd(cumulative_cap)
        with _locked(self.path):
            records, tip, torn = self._read()
            state = self._state(records)
            total = state.session_total.get(session, Decimal(0))
            if total + worst > session_limit:
                raise BudgetExceeded("session", f"{total} committed + {worst} worst case > {session_limit}")
            if state.committed + worst > cumulative_limit:
                raise BudgetExceeded("cumulative", f"{state.committed} committed + {worst} worst case > {cumulative_limit}")
            reservation = hashlib.sha256(f"{tip}:{session}:{call}".encode()).hexdigest()[:24]
            self._append({"event": "reserve", "reservation": reservation, "session": session, "call": call,
                          "worst_case_usd": str(worst), "session_cap_usd": str(session_limit),
                          "cumulative_cap_usd": str(cumulative_limit), "detail": detail or {}}, tip, torn)
            return reservation

    def settle(self, reservation: str, *, charged: Any, basis: str, detail: dict[str, Any] | None = None) -> None:
        """Replace a reservation with what the call is believed to have cost. ``basis`` says why that is the number."""
        amount = usd(charged)
        with _locked(self.path):
            records, tip, torn = self._read()
            state = self._state(records)
            if reservation not in state.open_reservations:
                raise LedgerCorrupt(f"reservation {reservation} is not open")
            self._append({"event": "settle", "reservation": reservation, "charged_usd": str(amount), "basis": basis,
                          "detail": detail or {}}, tip, torn)

    def reconcile(self, reservation: str, *, charged: Any, note: str) -> None:
        """Owner action: correct a charge from the provider's own record. The earlier entries stay in the chain."""
        amount = usd(charged)
        if not note.strip():
            raise ValueError("a reconciliation needs a note saying where the number came from")
        with _locked(self.path):
            records, tip, torn = self._read()
            state = self._state(records)
            if reservation not in state.open_reservations and reservation not in state.settled_reservations:
                raise LedgerCorrupt(f"unknown reservation {reservation}")
            self._append({"event": "reconcile", "reservation": reservation, "charged_usd": str(amount), "note": note},
                         tip, torn)
