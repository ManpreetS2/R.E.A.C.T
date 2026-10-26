"""Automatic matched-round revisions under an owner-approved live budget.

    python -m rewardbench.autopilot plan --config A.yaml --config B.yaml --config C.yaml \\
        --out runs/first-llm-study/pilot-p4 --total-usd-ceiling 0.30 --max-total-calls 12
    python -m rewardbench.autopilot run --mode live --i-authorize-paid-api-calls \\
        --authorize-automatic-revisions --total-usd-ceiling 0.30 --max-total-calls 12 \\
        --config A.yaml --config B.yaml --config C.yaml --out runs/first-llm-study/pilot-p4

``plan`` is free: it quotes the next round and says whether it would start. ``run`` makes paid calls
without a manual review between them, so it needs both paid flags, a ceiling and a call limit, all
chosen by the owner. It never raises either.

Every paid call still goes through ``rewardbench.run`` unchanged: one call per invocation, live
preflight, ``AggregateCeilingGate`` over the whole ledger root, the ledger lock, zero retries. This
module only decides whether the next *complete matched round* (one revision for every arm) may start:

* the round starts only if recorded spend under the ledger root plus the exact worst-case quote of
  every arm's next call fits under the ceiling; otherwise it stops before any request;
* arms never advance selectively: all arms sit at the same revision, or a round interrupted part-way
  is completed first (and only if it fits);
* after each call it checks that exactly one attempt was recorded, that its cost is within the
  reservation and that the ledger grew by exactly that cost, and stops on anything else;
* it stops on provider errors, unreadable ledgers, terminal or inconsistent experiment state,
  and (optionally) repeated invalid or unchanged controllers;
* it never runs held-out evaluation, so reserved final seeds are never flown.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from rewardbench.contracts import ConfigError, RewardBenchError
from rewardbench.core.ids import experiment_id
from rewardbench.core.locking import ExperimentBusy, ExperimentRunLock
from rewardbench.prompts import render_messages
from rewardbench.providers.pricing import load_catalog, quote_call
from rewardbench.run.ceiling import ledger_spent_usd
from rewardbench.run.cli import main as run_main
from rewardbench.run.factory import build_environment, prepare_config
from rewardbench.run.live import ACK_CONTINUATION_FLAG, ACK_PAID_FLAG, is_session_pause
from rewardbench.study import RESERVED_FINAL_SEEDS, check_matched

ACK_AUTO_FLAG = "--authorize-automatic-revisions"
JOURNAL = "autopilot.jsonl"
_TERMINAL = {"failed", "budget_exhausted"}
_COST_TOL = 1e-9

# Exit codes: a planned stop (finished, budget or call limit reached, early stop) is 0; a safety stop is 1.
PLANNED, SAFETY = 0, 1


@dataclass(frozen=True)
class Arm:
    path: Path
    name: str
    condition: str
    database: Path
    experiment_id: str
    num_revisions: int
    episodes_per_revision: int


@dataclass(frozen=True)
class Revision:
    index: int
    valid: bool
    controller: str | None  # canonical JSON of the selected controller


@dataclass(frozen=True)
class ArmState:
    status: str | None  # None: no database yet
    error: str | None
    revisions: tuple[Revision, ...]
    attempts: int
    spent_usd: float
    unfinished: tuple[int, ...]  # valid revisions whose episodes are not all recorded

    @property
    def next_revision(self) -> int:
        return len(self.revisions)

    def invalid_streak(self) -> int:
        streak = 0
        for revision in reversed(self.revisions):
            if revision.valid:
                break
            streak += 1
        return streak

    def unchanged_streak(self) -> int:
        streak = 0
        for newer, older in zip(reversed(self.revisions), reversed(self.revisions[:-1])):
            if not (newer.valid and older.valid and newer.controller == older.controller):
                break
            streak += 1
        return streak


@dataclass(frozen=True)
class Settings:
    ceiling_usd: float
    max_total_calls: int
    ledger_root: Path
    out: Path
    stop_after_invalid: int = 2
    stop_after_unchanged: int = 2
    early_stop_scope: str = "all"
    max_rounds: int | None = None
    margin_usd: float = 0.0


@dataclass
class Outcome:
    stop_reason: str
    code: int
    rounds_completed: int = 0
    calls_made: int = 0
    spent_before: float = 0.0
    spent_after: float = 0.0
    journal: bool = True
    events: list[dict[str, Any]] = field(default_factory=list)


class Stop(Exception):
    def __init__(self, reason: str, code: int) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


# ---------------------------------------------------------------- arms and their stored state


def load_arms(paths: list[Path], out: Path) -> list[Arm]:
    if not paths:
        raise ConfigError("at least one --config is required")
    raw: dict[str, dict[str, Any]] = {}
    arms = []
    for path in paths:
        config = prepare_config(path)
        if config.provider == "mock":
            raise ConfigError(f"{path}: autopilot drives real providers only; mock configs run with rewardbench.run")
        if set(config.development_seeds) & set(RESERVED_FINAL_SEEDS):
            raise ConfigError(f"{path}: development seeds include the reserved final-evaluation cohort")
        if config.max_model_retries != 0:
            raise ConfigError(f"{path}: autopilot requires max_model_retries=0")
        name = config.experiment_name
        if name in raw:
            raise ConfigError(f"duplicate experiment_name {name!r}")
        raw[name] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        arms.append(Arm(Path(path), name, config.feedback_condition.value, out / f"{name}.sqlite",
                        experiment_id(config), config.num_revisions, config.episodes_per_revision))
    if len({arm.condition for arm in arms}) != len(arms):
        raise ConfigError("each arm must have a different feedback_condition")
    check_matched(raw)  # arms may differ only in condition and names
    return arms


def read_state(arm: Arm) -> ArmState:
    """Read-only view of one arm's database. Raises ``Stop`` on anything inconsistent."""

    if not arm.database.exists():
        return ArmState(None, None, (), 0, 0.0, ())
    try:
        with closing(sqlite3.connect(f"file:{arm.database}?mode=ro", uri=True)) as db:
            db.row_factory = sqlite3.Row
            experiments = db.execute("SELECT experiment_id, status, error FROM experiments").fetchall()
            attempts = db.execute(
                "SELECT revision_index, selected, valid, parameters_json, estimated_cost_usd, provider "
                "FROM attempts WHERE experiment_id = ? ORDER BY revision_index, call_index",
                (arm.experiment_id,)).fetchall()
            episodes = db.execute(
                "SELECT revision_index, COUNT(*) AS n FROM episodes WHERE experiment_id = ? GROUP BY revision_index",
                (arm.experiment_id,)).fetchall()
            total_attempts = db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]
    except sqlite3.Error as exc:
        raise Stop(f"{arm.name}: cannot read {arm.database}: {exc}", SAFETY) from exc
    if not experiments:
        return ArmState(None, None, (), total_attempts, 0.0, ())
    if len(experiments) != 1 or experiments[0]["experiment_id"] != arm.experiment_id:
        raise Stop(f"{arm.name}: {arm.database} holds a different experiment than this config", SAFETY)
    if total_attempts != len(attempts):
        raise Stop(f"{arm.name}: {arm.database} has attempts from another experiment", SAFETY)
    selected = [a for a in attempts if a["selected"]]
    if [a["revision_index"] for a in selected] != list(range(len(selected))):
        raise Stop(f"{arm.name}: stored revisions are not contiguous", SAFETY)
    revisions = tuple(Revision(a["revision_index"], bool(a["valid"]),
                               _canonical(a["parameters_json"]) if a["valid"] else None) for a in selected)
    flown = {row["revision_index"]: row["n"] for row in episodes}
    unfinished = tuple(r.index for r in revisions if r.valid and flown.get(r.index, 0) < arm.episodes_per_revision)
    costs = [a["estimated_cost_usd"] for a in attempts if a["provider"] != "mock"]
    if any(c is None or not math.isfinite(c) or c < 0 for c in costs):
        raise Stop(f"{arm.name}: invalid cost record", SAFETY)
    return ArmState(experiments[0]["status"], experiments[0]["error"], revisions, len(attempts),
                    float(sum(costs)), unfinished)


def _canonical(parameters_json: str) -> str:
    return json.dumps(json.loads(parameters_json), sort_keys=True, separators=(",", ":"))


class _QuoteOnly:
    """Stands in for the model client so the runner can build (never send) a request."""

    def __init__(self, provider: str, model_id: str) -> None:
        self.provider, self.model_id = provider, model_id

    def propose(self, request):  # pragma: no cover - planning never proposes
        raise RuntimeError("autopilot planning must not call a model")


def quote_next(arm: Arm, revision: int, catalog) -> float:
    """Exact worst-case USD of the arm's next call: the same prompt and rule ``AggregateCeilingGate`` uses."""

    from rewardbench.core.runner import ExperimentRunner
    from rewardbench.storage import SqliteStore

    config = prepare_config(arm.path, database_path=arm.database)
    environment = build_environment(config)
    store = SqliteStore(arm.database if arm.database.exists() else ":memory:")
    try:
        if not arm.database.exists():
            store.initialize()
        runner = ExperimentRunner(config, _QuoteOnly(config.provider, config.model_id), environment, store)
        request = runner.request_for(revision)
        system_text, user_text = render_messages(request)
    finally:
        store.close()
        environment.close()
    quote = quote_call(catalog, config.provider, config.model_id, system_text=system_text, user_text=user_text,
                       settings=dict(request.model_settings), attempts=1)
    if not quote.available:
        raise Stop(f"{arm.name}: the next call cannot be priced ({quote.note})", SAFETY)
    return float(quote.usd)


# ---------------------------------------------------------------- the round loop


def plan_round(arms: list[Arm], states: dict[str, ArmState], settings: Settings, *, spent: float,
               calls_made: int, rounds_started: int, catalog) -> tuple[list[Arm], dict[str, float]]:
    """Return the arms to call next (in order) with their quotes, or raise ``Stop``."""

    for arm in arms:
        state = states[arm.name]
        if state.status in _TERMINAL:
            raise Stop(f"{arm.name} is {state.status} (terminal); a matched round cannot continue", SAFETY)
        if state.status == "running":
            raise Stop(f"{arm.name} is marked running; another process may hold it", SAFETY)
        if state.status == "interrupted" and state.revisions and not is_session_pause(state.error, status_value="interrupted"):
            raise Stop(f"{arm.name} was interrupted ({state.error}); review it before continuing", SAFETY)
        if state.unfinished:
            raise Stop(f"{arm.name} has unflown episodes in revision(s) {list(state.unfinished)}", SAFETY)
    levels = {states[a.name].next_revision for a in arms}
    if max(levels) - min(levels) > 1:
        raise Stop(f"arms are more than one revision apart: {sorted(levels)}", SAFETY)
    target = max(levels)
    lagging = [a for a in arms if states[a.name].next_revision < target]
    if not lagging:
        if target >= arms[0].num_revisions:
            raise Stop(f"all arms completed {target} revisions", PLANNED)
        _early_stop(arms, states, settings)
        if settings.max_rounds is not None and rounds_started >= settings.max_rounds:
            raise Stop(f"--max-rounds {settings.max_rounds} reached", PLANNED)
        due, revision = list(arms), target
    else:
        due, revision = lagging, target - 1  # finish the interrupted round before any new one
    order = _rotate(arms, revision)
    due = [a for a in order if a in due]
    if calls_made + len(due) > settings.max_total_calls:
        raise Stop(f"the next matched round needs {len(due)} call(s); only "
                   f"{settings.max_total_calls - calls_made} of --max-total-calls {settings.max_total_calls} remain",
                   PLANNED)
    quotes = {a.name: quote_next(a, revision, catalog) for a in due}
    needed = sum(quotes.values())
    if spent + needed + settings.margin_usd > settings.ceiling_usd + 1e-12:
        raise Stop(f"the next matched round (revision {revision}, {len(due)} call(s)) needs worst-case "
                   f"${needed:.6f}; recorded spend ${spent:.6f} + margin ${settings.margin_usd:.6f} leaves "
                   f"${max(0.0, settings.ceiling_usd - spent - settings.margin_usd):.6f} under the "
                   f"${settings.ceiling_usd:.6f} ceiling. No request was sent.", PLANNED)
    return due, quotes


def _rotate(arms: list[Arm], revision: int) -> list[Arm]:
    """Rotate arm order every round so provider drift is not confounded with arm."""
    shift = revision % len(arms)
    return arms[shift:] + arms[:shift]


def _early_stop(arms: list[Arm], states: dict[str, ArmState], settings: Settings) -> None:
    def stuck(state: ArmState) -> str | None:
        if settings.stop_after_invalid and state.invalid_streak() >= settings.stop_after_invalid:
            return f"{state.invalid_streak()} invalid controllers in a row"
        if settings.stop_after_unchanged and state.unchanged_streak() >= settings.stop_after_unchanged:
            return f"controller unchanged for {state.unchanged_streak()} revisions"
        return None

    reasons = {a.name: stuck(states[a.name]) for a in arms}
    hit = {name: why for name, why in reasons.items() if why}
    if hit and (settings.early_stop_scope == "any" or len(hit) == len(arms)):
        detail = "; ".join(f"{name}: {why}" for name, why in hit.items())
        raise Stop(f"early stop ({settings.early_stop_scope} arms): {detail}", PLANNED)


def run_autopilot(arms: list[Arm], settings: Settings, *, execute: Callable[[Arm, ArmState], int] | None = None,
                  say: Callable[[str], None] = print, plan_only: bool = False) -> Outcome:
    execute = execute or (lambda arm, state: _execute(arm, state, settings))
    catalog = load_catalog()
    outcome = Outcome("", PLANNED, journal=not plan_only)  # plan writes nothing at all
    lock = None if plan_only else ExperimentRunLock("autopilot", settings.ledger_root)
    if lock is not None:
        try:
            lock.acquire(blocking=False)
        except ExperimentBusy as exc:
            raise ConfigError(f"another autopilot holds {settings.ledger_root}: {exc}") from exc
    try:
        outcome.spent_before = _spent(settings.ledger_root)
        rounds_started = 0
        while True:
            spent = _spent(settings.ledger_root)
            states = {a.name: read_state(a) for a in arms}
            due, quotes = plan_round(arms, states, settings, spent=spent, calls_made=outcome.calls_made,
                                     rounds_started=rounds_started, catalog=catalog)
            revision = states[due[0].name].next_revision
            _log(settings, outcome, say, event="round", revision=revision, arms=[a.name for a in due],
                 quotes_usd=quotes, spent_usd=spent, ceiling_usd=settings.ceiling_usd)
            if plan_only:
                raise Stop(f"plan: revision {revision} for {len(due)} arm(s) fits (worst case "
                           f"${sum(quotes.values()):.6f}); nothing was sent", PLANNED)
            if len(due) == len(arms):
                rounds_started += 1
            for arm in due:
                before = states[arm.name]
                ledger_before = _spent(settings.ledger_root)
                code = execute(arm, before)
                after = read_state(arm)
                ledger_after = _spent(settings.ledger_root)
                new_cost = after.spent_usd - before.spent_usd
                outcome.calls_made += after.attempts - before.attempts
                _log(settings, outcome, say, event="call", arm=arm.name, revision=before.next_revision,
                     exit_code=code, status=after.status, new_attempts=after.attempts - before.attempts,
                     cost_usd=new_cost, quote_usd=quotes[arm.name], ledger_usd=ledger_after)
                _check_call(arm, before, after, code, new_cost, quotes[arm.name], ledger_before, ledger_after)
            outcome.rounds_completed += 1
    except Stop as stop:
        outcome.stop_reason, outcome.code = stop.reason, stop.code
    finally:
        with contextlib.suppress(Stop):
            outcome.spent_after = _spent(settings.ledger_root)
        if lock is not None:
            lock.release()
    _log(settings, outcome, say, event="stop", reason=outcome.stop_reason, code=outcome.code,
         calls_made=outcome.calls_made, rounds_completed=outcome.rounds_completed,
         spent_before_usd=outcome.spent_before, spent_after_usd=outcome.spent_after)
    return outcome


def _check_call(arm: Arm, before: ArmState, after: ArmState, code: int, new_cost: float, quote: float,
                ledger_before: float, ledger_after: float) -> None:
    new_attempts = after.attempts - before.attempts
    if new_attempts != 1:
        raise Stop(f"{arm.name}: expected exactly one new provider attempt, found {new_attempts} "
                   f"(status {after.status}: {after.error})", SAFETY)
    if new_cost > quote + _COST_TOL:
        raise Stop(f"{arm.name}: recorded cost ${new_cost:.6f} exceeded the ${quote:.6f} reservation", SAFETY)
    if abs((ledger_after - ledger_before) - new_cost) > _COST_TOL:
        raise Stop(f"ledger grew by ${ledger_after - ledger_before:.6f} but {arm.name} recorded "
                   f"${new_cost:.6f}; something else is spending under the ledger root", SAFETY)
    if after.status in _TERMINAL:
        raise Stop(f"{arm.name} ended {after.status}: {after.error}", SAFETY)
    finished = after.next_revision >= arm.num_revisions and after.status == "completed"
    paused = after.status == "interrupted" and is_session_pause(after.error, status_value="interrupted")
    if not (finished or paused) or after.next_revision != before.next_revision + 1 or code != 0:
        raise Stop(f"{arm.name}: unexpected state after one call (exit {code}, status {after.status}, "
                   f"revisions {after.next_revision}): {after.error}", SAFETY)


def _execute(arm: Arm, state: ArmState, settings: Settings) -> int:
    """One paid call through the unchanged run CLI and all of its guards."""

    argv = ["--config", str(arm.path), "--mode", "live", "--database", str(arm.database),
            "--prompt-log", str(settings.out / "prompts" / arm.name), "--max-new-paid-calls", "1",
            "--total-usd-ceiling", repr(settings.ceiling_usd), "--ledger-root", str(settings.ledger_root),
            ACK_PAID_FLAG]
    if state.attempts:
        argv.append(ACK_CONTINUATION_FLAG)  # the owner's automatic-revision approval covers continuation
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            code = int(run_main(argv))
        except SystemExit as exc:
            code = int(exc.code or 2)
    logs = settings.out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / f"{arm.name}.autopilot.log").open("a", encoding="utf-8") as handle:
        handle.write(f"### {_now()} revision {state.next_revision}\n{buffer.getvalue()}\n")
    return code


def _spent(root: Path) -> float:
    try:
        return ledger_spent_usd(root)[0]
    except ConfigError as exc:
        raise Stop(f"spending ledger problem: {exc}", SAFETY) from exc


def _log(settings: Settings, outcome: Outcome, say: Callable[[str], None], **event: Any) -> None:
    event = {"at": _now(), **event}
    outcome.events.append(event)
    if not outcome.journal:
        say("autopilot " + " ".join(f"{k}={v}" for k, v in event.items() if k != "at"))
        return
    settings.out.mkdir(parents=True, exist_ok=True)
    with (settings.out / JOURNAL).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
    say("autopilot " + " ".join(f"{k}={v}" for k, v in event.items() if k != "at"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- CLI


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rewardbench.autopilot", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run"):
        p = sub.add_parser(name)
        p.add_argument("--config", action="append", required=True, type=Path, help="one per arm (repeatable)")
        p.add_argument("--out", required=True, type=Path)
        p.add_argument("--total-usd-ceiling", type=float, required=True,
                       help="owner-approved ceiling on recorded spend summed over the ledger root")
        p.add_argument("--max-total-calls", type=int, required=True, help="owner-approved paid calls in this session")
        p.add_argument("--ledger-root", type=Path, default=None, help="default: the parent of --out")
        p.add_argument("--stop-after-invalid", type=int, default=2, help="0 disables")
        p.add_argument("--stop-after-unchanged", type=int, default=2, help="0 disables")
        p.add_argument("--early-stop-scope", choices=("all", "any"), default="all",
                       help="stop when every arm is stuck (default) or when any arm is")
        p.add_argument("--max-rounds", type=int, default=None)
        p.add_argument("--margin-usd", type=float, default=0.0, help="keep this much of the ceiling unspent")
        if name == "run":
            p.add_argument("--mode", choices=("live",), required=True)
            p.add_argument(ACK_PAID_FLAG, action="store_true", dest="authorize_paid")
            p.add_argument(ACK_AUTO_FLAG, action="store_true", dest="authorize_auto")
    args = parser.parse_args(argv)
    if args.command == "run" and not (args.authorize_paid and args.authorize_auto):
        print(f"error: automatic paid revisions need both {ACK_PAID_FLAG} and {ACK_AUTO_FLAG}", file=sys.stderr)
        return 2
    try:
        settings = _settings(args)
        arms = load_arms(args.config, settings.out)
        outcome = run_autopilot(arms, settings, plan_only=args.command == "plan")
    except (ConfigError, RewardBenchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"stopped: {outcome.stop_reason}")
    print(f"  calls made: {outcome.calls_made}; matched rounds completed: {outcome.rounds_completed}")
    print(f"  recorded spend under {settings.ledger_root}: ${outcome.spent_before:.6f} -> ${outcome.spent_after:.6f} "
          "(estimates, not an invoice)")
    return outcome.code


def _settings(args: argparse.Namespace) -> Settings:
    ceiling = args.total_usd_ceiling
    if isinstance(ceiling, bool) or not math.isfinite(ceiling) or ceiling <= 0:
        raise ConfigError("--total-usd-ceiling must be a positive number")
    if args.max_total_calls < 1:
        raise ConfigError("--max-total-calls must be >= 1")
    for flag, value in (("--stop-after-invalid", args.stop_after_invalid),
                        ("--stop-after-unchanged", args.stop_after_unchanged)):
        if value < 0:
            raise ConfigError(f"{flag} must be >= 0")
    if args.max_rounds is not None and args.max_rounds < 1:
        raise ConfigError("--max-rounds must be >= 1")
    if not math.isfinite(args.margin_usd) or args.margin_usd < 0:
        raise ConfigError("--margin-usd must be >= 0")
    out = args.out.resolve()
    root = (args.ledger_root or out.parent).resolve()
    if not root.is_dir():
        raise ConfigError(f"ledger root does not exist: {root}")
    if out != root and root not in out.parents:
        raise ConfigError("--out must be inside --ledger-root so its spend is counted")
    return Settings(ceiling, args.max_total_calls, root, out, args.stop_after_invalid, args.stop_after_unchanged,
                    args.early_stop_scope, args.max_rounds, args.margin_usd)


if __name__ == "__main__":
    raise SystemExit(main())
