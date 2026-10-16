"""Command-line entry for offline (and future live) experiments.

Examples
--------
python -m rewardbench.run --config configs/apollolander_offline_development_numerical.yaml --mode mock
python -m rewardbench.run --config configs/apollolander_offline_development_nofeedback.yaml --mode mock

Mock mode drives a scripted feedback-responsive model against real simulator
physics. It is an infrastructure test, not an LLM learning result. Live mode
is prepared but disabled and performs no provider API calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from rewardbench.contracts import (
    ConfigError,
    ExperimentAborted,
    ExperimentStatus,
    ResumeError,
    RewardBenchError,
)
from rewardbench.core.ids import experiment_id
from rewardbench.core.runner import ExperimentRunner
from rewardbench.run.factory import build_environment, build_model, prepare_config
from rewardbench.storage import SqliteStore

_SUCCESS = {ExperimentStatus.COMPLETED}
_RUN_FAILED = {
    ExperimentStatus.FAILED,
    ExperimentStatus.BUDGET_EXHAUSTED,
    ExperimentStatus.INTERRUPTED,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rewardbench.run",
        description=(
            "Run or resume one RewardBench experiment from a YAML/JSON config. "
            "Default --mode mock uses a scripted offline model (infrastructure test only)."
        ),
    )
    parser.add_argument("--config", required=True, type=Path, help="path to experiment YAML or JSON")
    parser.add_argument(
        "--mode",
        choices=("mock", "live"),
        default="mock",
        help="mock: scripted offline model (default). live: disabled; refuses without API calls",
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="optional SQLite path override (not part of the experiment id)",
    )
    args = parser.parse_args(argv)

    try:
        config = prepare_config(args.config, database_path=args.database)
        database = Path(config.database_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        exp_id = experiment_id(config)
        overrides = _flight_adapter_overrides(config, experiment_id=exp_id, database=database)
        model = build_model(config, mode=args.mode)
        environment = build_environment(config, adapter_overrides=overrides)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RewardBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
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

    store = SqliteStore(database)
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
        _print_summary(exc.summary, database)
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
        store.close()

    _print_summary(summary, database)
    if summary.status in _SUCCESS:
        return 0
    if summary.status in _RUN_FAILED:
        return 1
    return 1


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


def _print_summary(summary, database: Path) -> None:
    print("result")
    print(f"  experiment_id: {summary.experiment_id}")
    print(f"  session_id: {summary.session_id}")
    print(f"  status: {summary.status.value}")
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
    print(f"  database: {database.resolve()}")
    print(
        "  analysis: "
        f"python -m rewardbench.analysis report --logs {database} --out reports/{summary.experiment_id}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
