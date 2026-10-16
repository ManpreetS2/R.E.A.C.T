"""CLI: freeze a development controller and score it on sealed held-out starts.

Examples
--------
# After a completed offline development run:
python -m rewardbench.run --config configs/apollolander_offline_development_numerical.yaml --mode mock

python -m rewardbench.heldout \\
  --database runs/apollolander_offline_numerical.sqlite \\
  --source-config configs/apollolander_offline_development_numerical.yaml \\
  --selection-rule last_valid_selected

Held-out evaluation never calls a model. It is not an LLM learning result.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from rewardbench.config import config_from_mapping
from rewardbench.contracts import ConfigError, FeedbackCondition, RewardBenchError, Split
from rewardbench.core.heldout import (
    SELECTION_LAST_VALID_SELECTED,
    SELECTION_RULES,
    adapter_settings_from_source_config,
    evaluate_frozen_controller,
    freeze_controller_from_experiment,
    load_source_config,
)
from rewardbench.core.ids import experiment_id
from rewardbench.environments.apollolander import ENVIRONMENT_VERSION
from rewardbench.run.factory import build_environment, prepare_config
from rewardbench.storage import SqliteStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="rewardbench.heldout",
        description=(
            "Freeze the final valid selected controller from a COMPLETED development "
            "experiment and evaluate it on sealed held-out research starts. "
            "No ModelClient.propose. No paid API calls."
        ),
    )
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="SQLite path containing the completed development experiment",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--source-experiment-id",
        help="development experiment id (exp_...) to freeze from",
    )
    source.add_argument(
        "--source-config",
        type=Path,
        help="development YAML/JSON used to derive the experiment id",
    )
    parser.add_argument(
        "--selection-rule",
        default=SELECTION_LAST_VALID_SELECTED,
        choices=SELECTION_RULES,
        help="controller selection rule (default: last_valid_selected; never best held-out score)",
    )
    parser.add_argument(
        "--max-episode-steps",
        type=int,
        default=None,
        help="optional step cap override for held-out flights",
    )
    parser.add_argument(
        "--record-dir",
        type=Path,
        default=None,
        help="optional directory for flight-record provenance pointers",
    )
    args = parser.parse_args(argv)

    store: SqliteStore | None = None
    environment: Any = None
    try:
        store = SqliteStore(args.database)
        store.initialize()
        if args.source_experiment_id:
            source_id = args.source_experiment_id
        else:
            config = prepare_config(args.source_config, database_path=args.database)
            source_id = experiment_id(config)

        print("rewardbench.heldout")
        print(f"  database: {Path(args.database).resolve()}")
        print(f"  source_experiment_id: {source_id}")
        print(f"  selection_rule: {args.selection_rule}")
        print("  note: no model calls; frozen-controller scoring only")

        frozen = freeze_controller_from_experiment(
            store,
            source_id,
            selection_rule=args.selection_rule,
        )
        print("frozen_controller")
        print(f"  freeze_id: {frozen.freeze_id}")
        print(f"  controller_hash: {frozen.controller_hash}")
        print(f"  source_attempt_id: {frozen.source_attempt_id}")
        print(f"  source_revision_index: {frozen.source_revision_index}")
        print(f"  model_id: {frozen.model_id}")
        print(f"  provider: {frozen.provider}")
        print(f"  feedback_condition: {frozen.feedback_condition.value}")

        payload = load_source_config(store, source_id)
        held_out_seeds = tuple(payload.get("held_out_seeds") or ())
        development_seeds = tuple(payload.get("development_seeds") or ())
        if not held_out_seeds or not development_seeds:
            raise ConfigError("source config must include development_seeds and held_out_seeds")
        adapter = adapter_settings_from_source_config(payload)
        max_steps = args.max_episode_steps
        if max_steps is None:
            raw = adapter.get("max_steps")
            max_steps = int(raw) if raw is not None else None

        env_config = _environment_config_from_source(payload, database=args.database, max_steps=max_steps)
        if env_config.split is not Split.DEVELOPMENT:
            raise ConfigError("source config split must be development")
        if not isinstance(env_config.feedback_condition, FeedbackCondition):
            raise ConfigError("source feedback_condition is invalid")

        overrides: dict[str, Any] = {"experiment_id": source_id}
        if args.record_dir is not None:
            args.record_dir.mkdir(parents=True, exist_ok=True)
            overrides["record_dir"] = str(args.record_dir)
            overrides["record_video"] = False
        if max_steps is not None:
            env_config = replace(env_config, max_episode_steps=max_steps)

        environment = build_environment(env_config, adapter_overrides=overrides)
        summary = evaluate_frozen_controller(
            store,
            frozen,
            environment,
            held_out_seeds=held_out_seeds,
            development_seeds=development_seeds,
            start_schedule_version=str(adapter["start_schedule_version"]),
            vary_fuel=bool(adapter["vary_fuel"]),
            max_episode_steps=max_steps,
            environment_version=ENVIRONMENT_VERSION,
            record_dir=args.record_dir,
        )
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except RewardBenchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        close = getattr(environment, "close", None) if environment is not None else None
        if callable(close):
            close()
        if store is not None:
            store.close()

    print("heldout_evaluation")
    print(f"  evaluation_id: {summary.evaluation_id}")
    print(f"  status: {summary.status}")
    print(f"  run_state: {'completed' if summary.status == 'completed' else summary.status}")
    print(f"  episodes_recorded: {summary.episodes_recorded}")
    print(f"  held_out_seeds: {list(summary.held_out_seeds)}")
    print(f"  start_schedule_version: {summary.start_schedule_version}")
    print(f"  environment_version: {summary.environment_version}")
    print(f"  mean_reward: {summary.mean_reward}")
    print(f"  best_reward: {summary.best_reward}")
    print(f"  success_count: {summary.success_count}")
    print(f"  controller_hash: {summary.controller_hash}")
    print(
        "  note: held-out scores are sealed evaluation evidence; "
        "they must not enter development history or model prompts"
    )
    return 0 if summary.status == "completed" else 1


def _environment_config_from_source(
    payload: dict[str, Any],
    *,
    database: Path,
    max_steps: int | None,
) -> Any:
    """Rebuild an ExperimentConfig for adapter construction only."""

    allowed = {
        "experiment_name",
        "environment_id",
        "provider",
        "model_id",
        "feedback_condition",
        "split",
        "seed",
        "num_revisions",
        "episodes_per_revision",
        "history_window",
        "development_seeds",
        "held_out_seeds",
        "budget",
        "max_episode_steps",
        "max_model_retries",
        "checkpoint_every",
        "on_invalid_policy",
        "on_model_failure",
        "on_episode_failure",
        "database_path",
        "model_settings",
        "metadata",
        "notes",
    }
    cleaned = {key: value for key, value in payload.items() if key in allowed}
    cleaned["database_path"] = str(database)
    metadata = dict(cleaned.get("metadata") or {})
    adapter_kwargs = dict(metadata.get("adapter_kwargs") or {})
    adapter_kwargs["research_mode"] = True
    if max_steps is not None:
        adapter_kwargs["max_steps"] = max_steps
        cleaned["max_episode_steps"] = max_steps
    metadata["adapter_kwargs"] = adapter_kwargs
    metadata["heldout_evaluation"] = True
    metadata["not_llm_learning"] = True
    cleaned["metadata"] = metadata
    return config_from_mapping(cleaned)


if __name__ == "__main__":
    raise SystemExit(main())
