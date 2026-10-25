"""Command-line entry for offline mock and authorized live experiments.

Examples
--------
# Offline infrastructure test (default; no API keys; not LLM learning)
python -m rewardbench.run --config configs/apollolander_offline_development_numerical.yaml --mode mock

# First authorized paid call only (one model request, zero retries)
python -m rewardbench.run \\
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \\
  --mode live \\
  --i-authorize-paid-api-calls

# Separately approved continuation for the next revision (resume; no repeat of call 1)
python -m rewardbench.run \\
  --config configs/apollolander_pilot_openai_gpt54mini.yaml \\
  --mode live \\
  --i-authorize-paid-api-calls \\
  --authorize-continuation

Mock mode drives a scripted feedback-responsive model against real simulator
physics. Live mode uses ``build_model_client`` only after explicit acknowledgment.
A paused one-call pilot is never labeled a completed learning experiment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Callable

from rewardbench.contracts import (
    ConfigError,
    ExperimentAborted,
    ExperimentStatus,
    ResumeError,
    RewardBenchError,
    Split,
)
from rewardbench.core.ids import experiment_id, reject_legacy_restart
from rewardbench.core.runner import ExperimentRunner
from rewardbench.run.factory import build_environment, build_model, prepare_config
from rewardbench.run.prompt_log import PromptRecorder
from rewardbench.run.live import ACK_CONTINUATION_FLAG, ACK_PAID_FLAG, is_session_pause
from rewardbench.storage import SqliteStore

_SUCCESS = {ExperimentStatus.COMPLETED}
_RUN_FAILED = {
    ExperimentStatus.FAILED,
    ExperimentStatus.BUDGET_EXHAUSTED,
    ExperimentStatus.INTERRUPTED,
}


def main(
    argv: list[str] | None = None,
    *,
    _transport: object | None = None,
    _api_key: str | None = None,
    _sleeper: object | None = None,
    _progress: Callable[[str], None] | None = None,
) -> int:
    """CLI entry. ``_transport`` / ``_api_key`` / ``_sleeper`` are test-only hooks."""

    parser = argparse.ArgumentParser(
        prog="rewardbench.run",
        description=(
            "Run or resume one RewardBench experiment from a YAML/JSON config. "
            "Default --mode mock uses a scripted offline model (infrastructure test only). "
            "Live mode requires explicit paid-call acknowledgment and never defaults on."
        ),
    )
    parser.add_argument("--config", required=True, type=Path, help="path to experiment YAML or JSON")
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="mock",
        help="mock: scripted offline model (default). live: real ModelClient after acknowledgment",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="optional SQLite path override (not part of the experiment id)",
    )
    parser.add_argument(
        ACK_PAID_FLAG,
        action="store_true",
        dest="authorize_paid",
        help="required for --mode live; acknowledges that propose() may spend money",
    )
    parser.add_argument(
        ACK_CONTINUATION_FLAG,
        action="store_true",
        dest="authorize_continuation",
        help="required to authorize another paid revision after reviewing stored results",
    )
    parser.add_argument(
        "--max-new-paid-calls",
        type=int,
        default=1,
        help="new paid propose() calls allowed in this CLI process (live pilot default: 1)",
    )
    parser.add_argument(
        "--prompt-log",
        type=Path,
        default=None,
        help="directory that receives the exact system/user prompt sent for every model call",
    )
    args = parser.parse_args(argv)

    store: SqliteStore | None = None
    environment = None
    try:
        config = prepare_config(args.config, database_path=args.database)
        if config.split is not Split.DEVELOPMENT:
            raise ConfigError("adaptation requires split=development; use rewardbench.heldout")
        database = Path(config.database_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        exp_id = experiment_id(config)
        store = SqliteStore(database)
        store.initialize()
        reject_legacy_restart(config, store)
        overrides = _flight_adapter_overrides(config, experiment_id=exp_id, database=database)
        if config.environment_id.lower() in {"apollolander", "apollo-lander", "apollo"}:
            overrides.update(
                split=config.split.value,
                origin="deterministic_mock" if args.mode == "mock" else "model_generated",
            )
        environment = build_environment(config, adapter_overrides=overrides)

        existing = store.get_experiment(exp_id)
        resume_selected = 0
        if existing is not None:
            resume_selected = sum(1 for item in store.fetch_attempts(exp_id) if item.selected)

        model = build_model(
            config,
            mode=args.mode,
            authorize_paid=args.authorize_paid,
            authorize_continuation=args.authorize_continuation,
            resume_selected_attempts=resume_selected,
            max_new_paid_calls=args.max_new_paid_calls,
            environment=environment,
            api_key=_api_key,
            transport=_transport,
            sleeper=_sleeper,
        )
        if args.prompt_log is not None or _progress is not None:
            model = PromptRecorder(model, args.prompt_log, _progress)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _safe_close(environment, store)
        return 2
    except RewardBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        _safe_close(environment, store)
        return 2

    print("rewardbench.run")
    print(f"  mode: {args.mode}")
    print(f"  config: {args.config}")
    print(f"  experiment_id: {exp_id}")
    print(f"  environment_id: {config.environment_id}")
    print(f"  feedback_condition: {config.feedback_condition.value}")
    print(f"  split: {config.split.value}")
    print(f"  provider/model: {config.provider}/{config.model_id}")
    print(f"  database: {database.resolve()}")
    adapter_kwargs = dict(config.metadata.get("adapter_kwargs") or {})
    if adapter_kwargs.get("research_mode") or overrides.get("research_mode"):
        print(f"  research_mode: {overrides.get('research_mode', adapter_kwargs.get('research_mode'))}")
        print(
            "  start_schedule_version: "
            f"{adapter_kwargs.get('start_schedule_version', 'apollolander.starts.v1')}"
        )
    if overrides.get("record_dir") or adapter_kwargs.get("record_dir"):
        print(f"  flight_records: {overrides.get('record_dir', adapter_kwargs.get('record_dir'))}")
    if getattr(environment, "research_mode", False):
        print(f"  adapter.research_mode: {environment.research_mode}")
        print(f"  adapter.start_schedule_version: {environment.start_schedule_version}")
    if args.mode == "mock":
        print(
            "  note: scripted mock model — infrastructure test only; "
            "not evidence of LLM learning"
        )
    else:
        print(f"  paid_authorization: {ACK_PAID_FLAG}")
        if args.authorize_continuation:
            print(f"  continuation_authorization: {ACK_CONTINUATION_FLAG}")
        print(f"  max_new_paid_calls: {args.max_new_paid_calls}")
        print("  note: live mode may spend money inside propose(); review SQLite after each call")

    try:
        runner = ExperimentRunner(config, model, environment, store)
        summary = runner.run()
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ResumeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except ExperimentAborted as exc:
        _print_summary(exc.summary, database, config_num_revisions=config.num_revisions)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    except RewardBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        close = getattr(environment, "close", None)
        if callable(close):
            close()
        if store is not None:
            store.close()

    run_state = _print_summary(summary, database, config_num_revisions=config.num_revisions)
    if run_state == "completed":
        return 0
    if run_state == "paused":
        return 0
    return 1


def _safe_close(environment: object | None, store: SqliteStore | None) -> None:
    close = getattr(environment, "close", None) if environment is not None else None
    if callable(close):
        close()
    if store is not None:
        store.close()


def _flight_adapter_overrides(config, *, experiment_id: str, database: Path) -> dict[str, Any]:
    """Runtime-only adapter kwargs that must not alter the hashed experiment id."""

    overrides: dict[str, Any] = {"experiment_id": experiment_id}
    metadata = dict(config.metadata or {})
    raw_kwargs = metadata.get("adapter_kwargs") or {}
    adapter_kwargs = dict(raw_kwargs)
    if metadata.get("record_flights") and "record_dir" not in adapter_kwargs:
        flights = database.parent / "flights" / experiment_id
        flights.mkdir(parents=True, exist_ok=True)
        overrides["record_dir"] = str(flights)
        overrides.setdefault("record_video", False)
    return overrides


def _print_summary(summary, database: Path, *, config_num_revisions: int) -> str:
    paused = is_session_pause(summary.error, status_value=summary.status.value)
    incomplete = summary.revisions_completed < config_num_revisions
    if paused and incomplete:
        run_state = "paused"
    elif summary.status is ExperimentStatus.COMPLETED:
        run_state = "completed"
    elif summary.status is ExperimentStatus.BUDGET_EXHAUSTED:
        run_state = "budget-exhausted"
    elif summary.status is ExperimentStatus.INTERRUPTED:
        run_state = "interrupted" if not paused else "paused"
    elif summary.status is ExperimentStatus.FAILED:
        run_state = "failed"
    else:
        run_state = summary.status.value

    print("result")
    print(f"  experiment_id: {summary.experiment_id}")
    print(f"  session_id: {summary.session_id}")
    print(f"  status: {summary.status.value}")
    print(f"  run_state: {run_state}")
    print(f"  revisions_completed: {summary.revisions_completed}")
    print(f"  episodes_recorded: {summary.episodes_recorded}")
    print(f"  invalid_revisions: {summary.invalid_revisions}")
    print(f"  model_calls: {summary.model_calls}")
    print(f"  total_tokens: {summary.total_tokens}")
    print(f"  total_cost_usd: {summary.total_cost_usd}")
    print(f"  mean_reward: {summary.mean_reward}")
    print(f"  best_reward: {summary.best_reward}")
    if summary.error:
        print(f"  error: {summary.error}")
    if run_state == "paused":
        print(
            "  note: paused one-call/live-session pilot — not a completed learning experiment. "
            f"Review SQLite, then continue with {ACK_PAID_FLAG} {ACK_CONTINUATION_FLAG}."
        )
    print(f"  database: {database.resolve()}")
    print(
        "  analysis: "
        f"python -m rewardbench.analysis report --logs {database} --out reports/{summary.experiment_id}"
    )
    return run_state


if __name__ == "__main__":
    raise SystemExit(main())
