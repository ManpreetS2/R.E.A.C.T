"""One-command operator for the existing run -> held-out -> report workflow.

Examples
--------
# Free, offline, scripted model (infrastructure demonstration, not an LLM)
python -m rewardbench.operate run \\
  --config configs/apollolander_offline_development_nofeedback.yaml \\
  --config configs/apollolander_offline_development_numerical.yaml

# Re-run with the same --out to resume; or just look at what exists
python -m rewardbench.operate status --out runs/operate-<stamp>

Live mode passes the existing paid-call flags straight to ``rewardbench.run``.
Without them (and valid credentials, a priced model and budget) it refuses.
This module adds no new simulation, storage or provider logic.
"""

from __future__ import annotations

import argparse
import contextlib
import builtins
import io
import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from rewardbench.analysis.__main__ import main as analysis_main
from rewardbench.contracts import ConfigError
from rewardbench.core.ids import experiment_id
from rewardbench.heldout.cli import main as heldout_main
from rewardbench.run.cli import main as run_main
from rewardbench.run.factory import prepare_config
from rewardbench.run.live import ACK_CONTINUATION_FLAG, ACK_PAID_FLAG

RESERVED_FINAL_SEEDS = range(2_000_000, 2_000_016)  # docs/FINAL_EVALUATION_PROTOCOL.md
MOCK_BANNER = "MOCK MODE: scripted model + real physics. Infrastructure demonstration, NOT an LLM result."
LIVE_BANNER = "LIVE MODE: real provider; propose() may spend real money. Existing safeguards apply."


_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def print(*args: Any, **kwargs: Any) -> None:  # noqa: A001 - a closed pipe must not abort a run
    try:
        builtins.print(*args, **kwargs)
    except (OSError, ValueError):
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rewardbench.operate",
        description="Operate the existing R.E.A.C.T. workflow from one command.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run (or resume) experiments, then held-out eval and reports")
    run.add_argument("--config", action="append", required=True, type=Path, help="repeatable")
    run.add_argument("--mode", choices=("mock", "live"), default="mock")
    run.add_argument("--out", type=Path, default=None, help="output directory (reuse it to resume)")
    run.add_argument("--heldout", action="store_true", help="freeze + score on the config's held-out seeds")
    run.add_argument("--no-report", action="store_true")
    run.add_argument(ACK_PAID_FLAG, action="store_true", dest="authorize_paid")
    run.add_argument(ACK_CONTINUATION_FLAG, action="store_true", dest="authorize_continuation")
    run.add_argument("--max-new-paid-calls", type=int, default=1)

    status = sub.add_parser("status", help="print revisions, rewards and artifacts found in --out")
    status.add_argument("--out", required=True, type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "status":
            return 0 if _print_status(args.out) else 1
        return _run(args)
    except KeyboardInterrupt:
        print("error: interrupted; re-run with the same --out to resume", file=sys.stderr)
        return 130


def _run(args: argparse.Namespace) -> int:
    live = args.mode == "live"
    if not live and (args.authorize_paid or args.authorize_continuation):
        print("error: paid-call flags are only meaningful with --mode live", file=sys.stderr)
        return 2
    out = (args.out or Path("runs") / f"operate-{datetime.now():%Y%m%d-%H%M%S}").resolve()
    out.mkdir(parents=True, exist_ok=True)
    print(LIVE_BANNER if live else MOCK_BANNER)
    print(f"output: {out}\n")

    exit_code = 0
    names: list[str] = []
    for path in args.config:
        try:
            config = prepare_config(path)
        except ConfigError as exc:
            print(f"error: {path}: {exc}", file=sys.stderr)
            return 2
        name = config.experiment_name
        if not _SAFE_NAME.match(name):
            print(f"error: experiment_name {name!r} is not usable as a file name", file=sys.stderr)
            return 2
        if name in names:
            print(f"error: duplicate experiment_name {name!r}", file=sys.stderr)
            return 2
        names.append(name)
        database = out / f"{name}.sqlite"
        print(f"== {name} [{config.feedback_condition.value}] {config.provider}/{config.model_id}")
        if live and (config.provider == "mock"):
            print("error: mock provider config cannot run in live mode", file=sys.stderr)
            return 2
        if not live and config.provider != "mock":
            print(
                f"error: {config.provider}/{config.model_id} is a real provider; "
                "use --mode live (mock mode would substitute a scripted model)",
                file=sys.stderr,
            )
            return 2

        argv = ["--config", str(path), "--mode", args.mode, "--database", str(database),
                "--prompt-log", str(out / "prompts" / name)]
        if live:
            argv += ["--max-new-paid-calls", str(args.max_new_paid_calls)]
            if args.authorize_paid:
                argv.append(ACK_PAID_FLAG)
            if args.authorize_continuation:
                argv.append(ACK_CONTINUATION_FLAG)
        code = _stage(out, name, "run", lambda: run_main(argv, _progress=_announcer(sys.stdout)))
        _print_experiment(database, config.num_revisions)
        if code != 0:
            print(f"   run did not complete (exit {code}); see {out / 'logs' / (name + '.run.log')}")
            print("   note: 'failed' and 'budget_exhausted' are terminal; start over with a new --out. "
                  "Interrupted/paused runs resume when you re-run with the same --out.")
            exit_code = max(exit_code, code)
            print()
            if code == 130:
                break
            continue

        if args.heldout and _experiment_status(database) != "completed":
            print(f"   held-out skipped: development is '{_experiment_status(database)}', not completed "
                  "(paused or partial runs must finish first)")
        elif args.heldout:
            held = {int(s) for s in config.held_out_seeds}
            if held & set(RESERVED_FINAL_SEEDS):
                print("   refusing held-out: config lists reserved final-evaluation seeds", file=sys.stderr)
                exit_code = max(exit_code, 2)
            elif _heldout_done(database):
                print("   held-out already completed for this database; not re-running")
                _print_heldout(database)
            else:
                hargs = ["--database", str(database), "--source-config", str(path),
                         "--record-dir", str(out / "heldout-flights" / name)]
                hcode = _stage(out, name, "heldout", lambda: heldout_main(hargs))
                _print_heldout(database)
                exit_code = max(exit_code, hcode)
        if not args.no_report:
            rcode = _stage(out, name, "report", lambda: analysis_main(
                ["report", "--logs", str(database), "--out", str(out / "reports" / name)]))
            print(f"   report: {out / 'reports' / name / 'report.md'}" if rcode == 0
                  else f"   report failed; see {out / 'logs' / (name + '.report.log')}")
            exit_code = max(exit_code, rcode)
        print()

    _print_status(out, header=False)
    return exit_code


def _announcer(stream):
    """Progress printer that bypasses stage capture and never lets display errors fail a run."""

    def say(message: str) -> None:
        try:
            print(f"   {message}", file=stream, flush=True)
        except (OSError, ValueError):  # closed pipe or terminal; the run must continue
            pass

    return say


def _stage(out: Path, name: str, stage: str, call) -> int:
    """Run an existing CLI in-process; keep its full output in logs/ and show errors."""

    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        try:
            code = int(call())
        except SystemExit as exc:  # argparse errors
            code = int(exc.code or 2)
    logs = out / "logs"
    logs.mkdir(exist_ok=True)
    (logs / f"{name}.{stage}.log").write_text(buffer.getvalue(), encoding="utf-8")
    for line in buffer.getvalue().splitlines():
        if line.strip().startswith("error:"):
            print(f"   {line.strip()}")
    return code


def _rows(database: Path, query: str) -> list[sqlite3.Row]:
    """Read-only query; a missing table (database not fully initialised) reads as no rows."""

    try:
        with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            return connection.execute(query).fetchall()
    except sqlite3.OperationalError:
        return []


def _experiment_status(database: Path) -> str:
    rows = _rows(database, "SELECT status FROM experiments") if database.exists() else []
    return rows[0]["status"] if rows else "missing"


def _print_experiment(database: Path, num_revisions: int) -> None:
    if not database.exists():
        print("   (no database yet)")
        return
    experiments = _rows(database, "SELECT status, completed_revisions, error FROM experiments")
    if experiments:
        e = experiments[0]
        print(f"   status={e['status']} revisions={e['completed_revisions']}/{num_revisions}"
              + (f" error={e['error']}" if e["error"] else ""))
    attempts = _rows(database, "SELECT revision_index, parameters_json, valid, selected, total_tokens, "
                               "estimated_cost_usd FROM attempts ORDER BY revision_index, call_index")
    episodes = _rows(database, "SELECT revision_index, seed, total_reward, success, crashed, error "
                               "FROM episodes ORDER BY revision_index, episode_index")
    previous: dict[str, Any] = {}
    for attempt in attempts:
        revision = attempt["revision_index"]
        params = json.loads(attempt["parameters_json"])
        change = _diff(previous, params) if previous else "initial controller"
        flights = [e for e in episodes if e["revision_index"] == revision]
        result = ", ".join(
            f"seed {e['seed']}: reward {e['total_reward']:.2f} "
            f"({'landed' if e['success'] else 'crashed' if e['crashed'] else 'no landing'})"
            if e["total_reward"] is not None else f"seed {e['seed']}: error {e['error']}"
            for e in flights
        ) or "not flown"
        flag = "" if attempt["valid"] else " INVALID"
        print(f"   rev {revision}{flag}: {change} | {result} | tokens={attempt['total_tokens']} "
              f"cost=${attempt['estimated_cost_usd']}")
        if attempt["valid"]:
            previous = params


def _diff(old: dict[str, Any], new: dict[str, Any]) -> str:
    changes = [f"{k}: {old.get(k)} -> {new.get(k)}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
    return "changed " + "; ".join(changes) if changes else "controller unchanged"


def _heldout_done(database: Path) -> bool:
    return any(r["status"] == "completed" for r in _rows(database, "SELECT status FROM heldout_evaluations"))


def _print_heldout(database: Path) -> None:
    rows = _rows(database, "SELECT status, completed_episodes, held_out_seeds_json FROM heldout_evaluations")
    if not rows:
        print("   held-out: none recorded")
        return
    r = rows[0]
    results = _rows(database, "SELECT total_reward, success FROM heldout_episodes")
    wins = sum(1 for x in results if x["success"])
    mean = sum(x["total_reward"] for x in results if x["total_reward"] is not None) / max(1, len(results))
    print(f"   held-out (frozen controller, no model calls): {r['status']} "
          f"{wins}/{len(results)} landed, mean reward {mean:.2f}, seeds {r['held_out_seeds_json']}")


def _print_status(out: Path, header: bool = True) -> bool:
    databases = sorted(out.glob("*.sqlite")) if out.is_dir() else []
    if not databases:
        print(f"error: no *.sqlite databases under {out}", file=sys.stderr)
        return False
    if header:
        print(f"status for {out}\n")
    print("summary")
    for database in databases:
        info = _rows(database, "SELECT feedback_condition, provider, model_id, status, completed_revisions "
                               "FROM experiments")
        if not info:
            continue
        i = info[0]
        rewards = [r["total_reward"] for r in _rows(
            database, "SELECT total_reward FROM episodes WHERE total_reward IS NOT NULL ORDER BY revision_index, episode_index")]
        series = " -> ".join(f"{x:.1f}" for x in rewards) or "-"
        label = "MOCK" if i["provider"] == "mock" else "LIVE"
        print(f"  [{label}] {database.stem}: {i['feedback_condition']}, {i['status']}, "
              f"{i['completed_revisions']} revisions, dev rewards {series}")
        if header:
            _print_experiment(database, i["completed_revisions"])
            _print_heldout(database)
    print("\nartifacts")
    for sub in ("prompts", "reports", "flights", "heldout-flights", "logs"):
        if (out / sub).exists():
            print(f"  {sub}: {out / sub}")
    for report in sorted(out.glob("reports/*/report.md")):
        print(f"  report: {report}")
    return True


if __name__ == "__main__":
    raise SystemExit(main())
