"""Load experiment YAML or JSON into :class:`ExperimentConfig`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from rewardbench.contracts import (
    BudgetLimits,
    ConfigError,
    ExperimentConfig,
    FailurePolicy,
    FeedbackCondition,
    Split,
)

_REQUIRED = (
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
)

_OPTIONAL = (
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
)

_BUDGET_FIELDS = (
    "max_cost_usd",
    "max_tokens",
    "max_wall_seconds",
    "max_revisions",
    "max_episodes",
    "max_model_calls",
)


def load_config(path: str | Path) -> ExperimentConfig:
    source = Path(path)
    if not source.is_file():
        raise ConfigError(f"config file not found: {source}")
    text = source.read_text(encoding="utf-8")
    suffix = source.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text)
    elif suffix == ".json":
        loaded = json.loads(text)
    else:
        raise ConfigError("config file must end in .yaml, .yml, or .json")
    if not isinstance(loaded, dict):
        raise ConfigError("config root must be a mapping")
    return config_from_mapping(loaded)


def config_from_mapping(data: Mapping[str, Any]) -> ExperimentConfig:
    if not isinstance(data, Mapping):
        raise ConfigError("config root must be a mapping")
    unknown = sorted(set(data) - set(_REQUIRED) - set(_OPTIONAL))
    if unknown:
        raise ConfigError(f"unknown config fields: {unknown}")
    missing = [key for key in _REQUIRED if key not in data]
    if missing:
        raise ConfigError(f"missing config fields: {missing}")
    budget = _budget(data.get("budget", {}))
    kwargs: dict[str, Any] = {
        "experiment_name": data["experiment_name"],
        "environment_id": data["environment_id"],
        "provider": data["provider"],
        "model_id": data["model_id"],
        "feedback_condition": _enum(FeedbackCondition, "feedback_condition", data["feedback_condition"]),
        "split": _enum(Split, "split", data["split"]),
        "seed": data["seed"],
        "num_revisions": data["num_revisions"],
        "episodes_per_revision": data["episodes_per_revision"],
        "history_window": data["history_window"],
        "development_seeds": tuple(data["development_seeds"]),
        "held_out_seeds": tuple(data["held_out_seeds"]),
        "budget": budget,
    }
    for name in (
        "max_episode_steps",
        "max_model_retries",
        "checkpoint_every",
        "database_path",
        "notes",
    ):
        if name in data:
            kwargs[name] = data[name]
    for name in ("on_invalid_policy", "on_model_failure", "on_episode_failure"):
        if name in data:
            kwargs[name] = _enum(FailurePolicy, name, data[name])
    for name in ("model_settings", "metadata"):
        if name in data:
            if not isinstance(data[name], Mapping):
                raise ConfigError(f"{name} must be a mapping")
            kwargs[name] = dict(data[name])
    return ExperimentConfig(**kwargs)


def _budget(raw: Any) -> BudgetLimits:
    if raw is None:
        return BudgetLimits()
    if not isinstance(raw, Mapping):
        raise ConfigError("budget must be a mapping")
    unknown = sorted(set(raw) - set(_BUDGET_FIELDS))
    if unknown:
        raise ConfigError(f"unknown budget fields: {unknown}")
    return BudgetLimits(**{key: raw[key] for key in _BUDGET_FIELDS if key in raw})


def _enum(kind: type[Any], name: str, value: Any) -> Any:
    if isinstance(value, kind):
        return value
    if isinstance(value, str):
        try:
            return kind(value)
        except ValueError as exc:
            allowed = [item.value for item in kind]
            raise ConfigError(f"{name} must be one of {allowed}") from exc
    raise ConfigError(f"{name} must be a string")
