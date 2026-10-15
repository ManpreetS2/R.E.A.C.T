"""Optional bridge to the core contract, used only when that module exists.

Developer 1 owns ``rewardbench.contracts`` and ``docs/INTERFACES.md``. This
helper does not declare those types. If the core module is importable and
``EpisodeResult`` can be constructed from the flight fields it already
understands, the scored flight is also returned in that form.
"""

from __future__ import annotations

import inspect
from typing import Any

from rewardbench.environments.lunarlander.types import FlightEpisode


def try_to_shared_episode(episode: FlightEpisode) -> Any | None:
    """Return a core ``EpisodeResult`` when its constructor accepts known fields."""
    try:
        from rewardbench import contracts
    except ImportError:
        return None

    episode_cls = getattr(contracts, "EpisodeResult", None)
    if episode_cls is None or not callable(episode_cls):
        return None

    available = {
        "reward": episode.reward,
        "total_reward": episode.reward,
        "seed": episode.seed,
        "episode_seed": episode.seed,
        "steps": episode.steps,
        "duration": episode.duration_seconds,
        "duration_seconds": episode.duration_seconds,
        "success": episode.landed,
        "landed": episode.landed,
        "crashed": episode.crashed,
        "terminated": episode.terminated,
        "truncated": episode.truncated,
        "environment": episode.environment_id,
        "environment_id": episode.environment_id,
        "valid": episode.controller_valid,
        "controller_valid": episode.controller_valid,
        "metrics": episode.to_dict(),
        "info": episode.to_dict(),
    }
    try:
        signature = inspect.signature(episode_cls)
    except (TypeError, ValueError):
        return None

    kwargs = {
        name: available[name]
        for name, parameter in signature.parameters.items()
        if name in available and parameter.kind in (
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
    }
    try:
        return episode_cls(**kwargs)
    except (TypeError, ValueError):
        return None
