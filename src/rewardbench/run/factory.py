"""Build validated experiment pieces for the CLI without rewriting the runner."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

from rewardbench.config import load_config
from rewardbench.contracts import ConfigError, EnvironmentAdapter, ExperimentConfig, ModelClient
from rewardbench.run.mock_model import SCRIPTED_MODEL_ID, SCRIPTED_PROVIDER, ScriptedFeedbackModel

# Forward-compatible ApolloLander constructor keys owned by Agent 2.
# When the adapter accepts them, metadata.adapter_kwargs values are passed through.
AGENT2_APOLLO_KWARGS = (
    "research_mode",
    "max_steps",
    "locked_camera",
    "record_dir",
    "record_video",
    "start_schedule_version",
    "vary_fuel",
    "experiment_id",
)


def prepare_config(
    path: str | Path,
    *,
    database_path: str | Path | None = None,
) -> ExperimentConfig:
    """Load YAML/JSON, validate budget fields, and optionally override the database path."""

    config = load_config(path)
    _validate_budget(config)
    _validate_metadata(config.metadata)
    if database_path is not None:
        config = replace(config, database_path=str(database_path))
    return config


def build_environment(
    config: ExperimentConfig,
    *,
    adapter_overrides: Mapping[str, Any] | None = None,
) -> EnvironmentAdapter:
    """Construct the configured adapter, applying validated ``metadata.adapter_kwargs``.

    ``adapter_overrides`` are runtime-only (for example ``experiment_id`` and an
    absolute ``record_dir``). They are not written back into the hashed config.
    """

    from rewardbench.environments import make_environment

    kwargs = adapter_kwargs_from_metadata(config.metadata)
    if adapter_overrides:
        for key, value in adapter_overrides.items():
            if not isinstance(key, str) or not key or key.startswith("_"):
                raise ConfigError(f"invalid adapter override key {key!r}")
            _reject_non_jsonable(value, path=f"adapter_overrides.{key}")
            kwargs[key] = value
    if (
        config.max_episode_steps is not None
        and "max_steps" not in kwargs
        and _is_apollo(config.environment_id)
    ):
        # ApolloLander constructor takes max_steps; episode calls still honor max_episode_steps.
        kwargs["max_steps"] = config.max_episode_steps
    accepted, dropped = _filter_adapter_kwargs(config.environment_id, kwargs)
    if dropped:
        # Fail closed: never silently downgrade a research YAML to fixed-start physics.
        raise ConfigError(
            f"adapter for {config.environment_id!r} does not accept metadata.adapter_kwargs "
            f"{sorted(dropped)}. Refusing to run with silently ignored settings. "
            f"Known ApolloLander forward-compatible keys include {list(AGENT2_APOLLO_KWARGS)}."
        )
    try:
        return make_environment(config.environment_id, **accepted)
    except TypeError as exc:
        raise ConfigError(f"failed to construct environment {config.environment_id!r}: {exc}") from exc
    except KeyError as exc:
        raise ConfigError(str(exc)) from exc


def build_model(
    config: ExperimentConfig,
    *,
    mode: str,
    authorize_paid: bool = False,
    authorize_continuation: bool = False,
    resume_selected_attempts: int = 0,
    max_new_paid_calls: int = 1,
    api_key: str | None = None,
    transport: object | None = None,
    sleeper: object | None = None,
    environment: EnvironmentAdapter | None = None,
) -> ModelClient:
    """Bind the offline scripted model, or an authorized live provider client.

    Live mode uses ``rewardbench.providers.build_model_client`` and never runs
    unless ``authorize_paid`` is true. Tests may inject ``transport`` and
    ``api_key`` so no real network or credentials are required.
    """

    normalized = mode.strip().lower()
    if normalized == "mock":
        return ScriptedFeedbackModel(
            provider=config.provider if config.provider == SCRIPTED_PROVIDER else SCRIPTED_PROVIDER,
            model_id=config.model_id or SCRIPTED_MODEL_ID,
        )
    if normalized == "live":
        from rewardbench.run.live import (
            build_live_model,
            preflight_live,
            validate_live_authorization,
        )

        validate_live_authorization(
            authorize_paid=authorize_paid,
            authorize_continuation=authorize_continuation,
            resume_selected_attempts=resume_selected_attempts,
        )
        if environment is None:
            raise ConfigError("live mode requires an environment for preflight schema checks")
        preflight_live(
            config,
            environment,
            max_new_paid_calls=max_new_paid_calls,
            api_key=api_key,
        )
        return build_live_model(
            config,
            max_new_paid_calls=max_new_paid_calls,
            api_key=api_key,
            transport=transport,
            sleeper=sleeper,
        )
    raise ConfigError(f"unknown run mode {mode!r}; expected 'mock' or 'live'")


def adapter_kwargs_from_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    raw = metadata.get("adapter_kwargs", {})
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ConfigError("metadata.adapter_kwargs must be a mapping")
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key:
            raise ConfigError("metadata.adapter_kwargs keys must be non-empty strings")
        if key.startswith("_"):
            raise ConfigError(f"metadata.adapter_kwargs forbids private key {key!r}")
        _reject_non_jsonable(value, path=f"metadata.adapter_kwargs.{key}")
        clean[key] = value
    return clean


def _filter_adapter_kwargs(
    environment_id: str,
    kwargs: Mapping[str, Any],
) -> tuple[dict[str, Any], set[str]]:
    from rewardbench.environments import ApolloLanderAdapter, LunarLanderAdapter, make_environment

    normalized = environment_id.strip().lower().replace("_", "-")
    if normalized in {"apollolander", "apollo-lander", "apollo"}:
        target = ApolloLanderAdapter
    elif normalized in {"lunarlander-v3", "lunarlander", "lunar-lander", "lunar-lander-v3"}:
        target = LunarLanderAdapter
    else:
        # Fall back to probing make_environment without kwargs, then constructor of the result.
        probe = make_environment(environment_id)
        target = type(probe)
        close = getattr(probe, "close", None)
        if callable(close):
            close()

    signature = inspect.signature(target.__init__)
    accepts_var_kw = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    accepted: dict[str, Any] = {}
    dropped: set[str] = set()
    for key, value in kwargs.items():
        if accepts_var_kw or key in signature.parameters:
            accepted[key] = value
        else:
            dropped.add(key)
    return accepted, dropped


def _validate_budget(config: ExperimentConfig) -> None:
    budget = config.budget
    for name in (
        "max_cost_usd",
        "max_tokens",
        "max_wall_seconds",
        "max_revisions",
        "max_episodes",
        "max_model_calls",
    ):
        value = getattr(budget, name)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"budget.{name} must be a positive number when set")
        if float(value) <= 0:
            raise ConfigError(f"budget.{name} must be positive when set")
    if config.budget.max_revisions is not None and config.budget.max_revisions < config.num_revisions:
        raise ConfigError("budget.max_revisions is lower than num_revisions")
    if (
        config.budget.max_episodes is not None
        and config.budget.max_episodes < config.num_revisions * config.episodes_per_revision
    ):
        # Allowed as a deliberate early stop, but reject impossible zero already handled above.
        pass


def _validate_metadata(metadata: Mapping[str, Any]) -> None:
    if not isinstance(metadata, Mapping):
        raise ConfigError("metadata must be a mapping")
    adapter_kwargs_from_metadata(metadata)


def _is_apollo(environment_id: str) -> bool:
    normalized = environment_id.strip().lower().replace("_", "-")
    return normalized in {"apollolander", "apollo-lander", "apollo"}


def _reject_non_jsonable(value: Any, *, path: str) -> None:
    if value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and value != value:
            raise ConfigError(f"{path} must be JSON-serializable")
        return
    if isinstance(value, Mapping):
        for key, inner in value.items():
            if not isinstance(key, str):
                raise ConfigError(f"{path} keys must be strings")
            _reject_non_jsonable(inner, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, inner in enumerate(value):
            _reject_non_jsonable(inner, path=f"{path}[{index}]")
        return
    raise ConfigError(f"{path} must be JSON-serializable")
