"""Aggregate USD ceiling across every live experiment under a directory tree.

Each experiment config carries its own software budget, and the three study arms
are separate experiments, so nothing else sums them. ``AggregateCeilingGate`` checks,
before every paid call, that (recorded spend of all live databases under the ledger
root) + (that call's worst-case price) fits under one owner-approved ceiling. When it
does not, the call is refused before any network use and the experiment is paused
(resumable), not failed.

Limits: recorded spend is the client's token-based estimate from the pricing catalog,
not an invoice; a billed call that returned no usable usage is recorded as $0; copying a
database out of the ledger root hides its spend. This is a software guard. The
provider-side hard limit is the control that survives a bug here.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from rewardbench.contracts import BudgetExceeded, ConfigError, ModelRequest
from rewardbench.prompts import render_messages
from rewardbench.providers.pricing import load_catalog, quote_call

AGGREGATE_RESOURCE = "aggregate_usd_ceiling"


def ledger_spent_usd(root: str | Path) -> tuple[float, int]:
    """(recorded estimated USD across all non-mock attempts, databases read) under ``root``."""

    total, databases = 0.0, 0
    for path in sorted(Path(root).rglob("*.sqlite")):
        try:
            with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
                row = db.execute(
                    "SELECT COALESCE(SUM(estimated_cost_usd), 0.0) FROM attempts WHERE provider != 'mock'"
                ).fetchone()
        except sqlite3.Error:
            continue  # not an experiment database
        total += float(row[0])
        databases += 1
    return total, databases


class AggregateCeilingGate:
    """``ModelClient`` wrapper that refuses a call that could push total spend over the ceiling."""

    def __init__(self, inner, *, ceiling_usd: float, ledger_root: str | Path, catalog=None) -> None:
        if isinstance(ceiling_usd, bool) or not isinstance(ceiling_usd, (int, float)) or not ceiling_usd > 0:
            raise ConfigError("total USD ceiling must be a positive number")
        self._inner = inner
        self.ceiling_usd = float(ceiling_usd)
        self.ledger_root = Path(ledger_root)
        self._catalog = catalog or load_catalog()

    @property
    def provider(self) -> str:
        return self._inner.provider

    @property
    def model_id(self) -> str:
        return self._inner.model_id

    def __getattr__(self, name: str):
        return getattr(self._inner, name)

    def propose(self, request: ModelRequest):
        system_text, user_text = render_messages(request)
        quote = quote_call(
            self._catalog, self.provider, self.model_id,
            system_text=system_text, user_text=user_text,
            settings=dict(request.model_settings), attempts=1,
        )
        spent, _ = ledger_spent_usd(self.ledger_root)
        if not quote.available or spent + quote.usd > self.ceiling_usd + 1e-12:
            reason = quote.note if not quote.available else (
                f"recorded spend ${spent:.6f} + worst-case ${quote.usd:.6f} for this call would exceed"
            )
            raise BudgetExceeded(
                f"aggregate USD ceiling: {reason} the ${self.ceiling_usd:.6f} ceiling. No request was sent. "
                "The experiment is paused; raise the ceiling only with the owner's written approval, then "
                "resume with --authorize-continuation.",
                resource=AGGREGATE_RESOURCE, spent=spent, limit=self.ceiling_usd,
            )
        return self._inner.propose(request)
