"""Adapter checks that do not need Box2D."""

from __future__ import annotations

import pytest

from rewardbench.environments.lunarlander.adapter import LunarLanderAdapter
from rewardbench.environments.lunarlander.schema import reference_controller


def test_development_split_refuses_held_out_seeds() -> None:
    adapter = LunarLanderAdapter()
    with pytest.raises(ValueError, match="held-out"):
        adapter.evaluate(reference_controller(), [1_000_000], split="development")


def test_held_out_split_refuses_development_seeds() -> None:
    adapter = LunarLanderAdapter()
    with pytest.raises(ValueError, match="development"):
        adapter.evaluate(reference_controller(), [0], split="held_out")


def test_make_environment_rejects_unknown_names() -> None:
    from rewardbench.environments import make_environment

    assert make_environment("LunarLander-v3").environment_id == "LunarLander-v3"
    with pytest.raises(KeyError, match="Minecraft"):
        make_environment("Minecraft")
