"""Reproducible experiment identifiers."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from rewardbench.contracts import CONTRACT_VERSION, ConfigError, ExperimentConfig

_HASH_EXCLUDED = ("database_path", "notes")


def canonical_config(config: ExperimentConfig) -> dict[str, Any]:
    """JSON-ready payload. ``database_path`` and ``notes`` are omitted."""

    payload: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "experiment_name": config.experiment_name,
        "environment_id": config.environment_id,
        "provider": config.provider,
        "model_id": config.model_id,
        "feedback_condition": config.feedback_condition.value,
        "split": config.split.value,
        "seed": config.seed,
        "num_revisions": config.num_revisions,
        "episodes_per_revision": config.episodes_per_revision,
        "history_window": config.history_window,
        "max_episode_steps": config.max_episode_steps,
        "max_model_retries": config.max_model_retries,
        "checkpoint_every": config.checkpoint_every,
        "on_invalid_policy": config.on_invalid_policy.value,
        "on_model_failure": config.on_model_failure.value,
        "on_episode_failure": config.on_episode_failure.value,
        "development_seeds": list(config.development_seeds),
        "held_out_seeds": list(config.held_out_seeds),
        "budget": {
            "max_cost_usd": config.budget.max_cost_usd,
            "max_tokens": config.budget.max_tokens,
            "max_wall_seconds": config.budget.max_wall_seconds,
            "max_revisions": config.budget.max_revisions,
            "max_episodes": config.budget.max_episodes,
            "max_model_calls": config.budget.max_model_calls,
        },
        "model_settings": dict(config.model_settings),
        "metadata": dict(config.metadata),
    }
    for field_name in _HASH_EXCLUDED:
        payload.pop(field_name, None)
    try:
        json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ConfigError("experiment config must be JSON-serializable") from exc
    return payload


def config_hash(config: ExperimentConfig) -> str:
    """Full SHA-256 hex digest of :func:`canonical_config`."""

    encoded = json.dumps(
        canonical_config(config),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def experiment_id(config: ExperimentConfig) -> str:
    """Stable id, ``exp_`` plus the first 20 hex characters of the config hash."""

    return f"exp_{config_hash(config)[:20]}"


def new_session_id() -> str:
    """Unique id for one process invocation. Not reproducible across resumes."""

    return f"ses_{uuid.uuid4().hex}"
