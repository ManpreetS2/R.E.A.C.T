"""Simulation environments for reward-driven controller adaptation.

Both adapters implement contract 1.0.0 through ``describe``, ``validate_policy``,
and ``run_episode``. Runner ids are ``lunarlander-v3`` and ``apollolander``.
"""

from __future__ import annotations

from rewardbench.environments.apollolander.adapter import ApolloLanderAdapter
from rewardbench.environments.lunarlander.adapter import LunarLanderAdapter
from rewardbench.environments.lunarlander.types import EnvironmentAdapter

__all__ = ["ApolloLanderAdapter", "EnvironmentAdapter", "LunarLanderAdapter", "make_environment"]


def make_environment(name: str, **kwargs: object):
    normalized = name.strip().lower().replace("_", "-")
    if normalized in {"lunarlander-v3", "lunarlander", "lunar-lander", "lunar-lander-v3"}:
        return LunarLanderAdapter(**kwargs)  # type: ignore[arg-type]
    if normalized in {"apollolander", "apollo-lander", "apollo"}:
        return ApolloLanderAdapter(**kwargs)  # type: ignore[arg-type]
    raise KeyError(
        f"unknown environment {name!r}. Available now: LunarLander-v3, ApolloLander."
    )
