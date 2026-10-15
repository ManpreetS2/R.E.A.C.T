"""Contract 1.0.0 adapter tests for both lander environments."""

from __future__ import annotations

import math

import pytest

from rewardbench.contracts import CONTRACT_VERSION, CandidatePolicy, EnvironmentAdapter
from rewardbench.environments import make_environment
from rewardbench.environments.apollolander import constant_controller, demonstration_guidance_controller
from rewardbench.environments.lunarlander.schema import reference_controller


def _policy(parameters: dict, revision: int = 0) -> CandidatePolicy:
    return CandidatePolicy(
        revision_index=revision,
        parameters=parameters,
        raw_response="{}",
        valid=True,
        validation_error=None,
        model_id="hand-specified",
        provider="none",
    )


def test_contract_version_is_published() -> None:
    assert CONTRACT_VERSION == "1.0.0"


def test_both_adapters_match_the_runner_protocol() -> None:
    gym = make_environment("lunarlander-v3")
    apollo = make_environment("apollolander")
    assert isinstance(gym, EnvironmentAdapter)
    assert isinstance(apollo, EnvironmentAdapter)
    assert gym.describe().environment_id == "lunarlander-v3"
    assert apollo.describe().environment_id == "apollolander"
    assert "apollo" in apollo.describe().environment_id
    assert gym.describe().controller_schema["schema"] == "rewardbench.lunarlander.controller.v1"
    assert apollo.describe().controller_schema["schema"] == "rewardbench.apollolander.controller.v1"


def test_apollo_rejects_javascript_before_physics() -> None:
    adapter = make_environment("apollolander")
    result = adapter.validate_policy(
        {
            "schema": "rewardbench.apollolander.controller.v1",
            "policy": "constant",
            "thrust": 0,
            "rotation": -90,
            "javascript": "reset()",
        }
    )
    assert result.valid is False
    with pytest.raises(Exception, match="forbidden"):
        adapter.run_episode(
            _policy(
                {
                    "schema": "rewardbench.apollolander.controller.v1",
                    "policy": "constant",
                    "thrust": 0,
                    "rotation": -90,
                    "javascript": "reset()",
                }
            ),
            seed=0,
            episode_index=0,
            revision_index=0,
        )


def test_apollo_contract_episode_is_deterministic_and_verified() -> None:
    adapter = make_environment("apollolander")
    crash = adapter.run_episode(
        _policy(constant_controller(0, -90), revision=0),
        seed=4,
        episode_index=1,
        revision_index=0,
    )
    repeat = adapter.run_episode(
        _policy(constant_controller(0, -90), revision=0),
        seed=11,
        episode_index=2,
        revision_index=0,
    )
    assert crash.seed == 4
    assert crash.episode_index == 1
    assert crash.revision_index == 0
    assert crash.success is False
    assert crash.crashed is True
    assert crash.terminated is True
    assert crash.truncated is False
    assert math.isfinite(crash.total_reward)
    assert crash.total_reward == repeat.total_reward
    assert crash.metrics["seed_affects_physics"] == 0.0
    assert crash.metrics["fuel_used"] == 0.0
    assert crash.metrics["zone_x1"] < crash.metrics["zone_x2"]
    assert all(isinstance(value, float) for value in crash.metrics.values())

    landing = adapter.run_episode(
        _policy(demonstration_guidance_controller(), revision=1),
        seed=0,
        episode_index=0,
        revision_index=1,
    )
    assert landing.success is True
    assert landing.crashed is False
    assert landing.metrics["in_landing_zone"] == 1.0
    assert landing.metrics["vertical_speed"] < 0.075
    assert landing.seed == 0
    assert math.isfinite(landing.total_reward)


def test_gym_contract_episode_uses_verified_landing() -> None:
    adapter = make_environment("LunarLander-v3")
    result = adapter.run_episode(
        _policy(reference_controller(), revision=0),
        seed=0,
        episode_index=0,
        revision_index=0,
    )
    assert result.success is True
    assert result.crashed is False
    assert result.metrics["in_landing_zone"] == 1.0
    assert result.metrics["fuel_used"] > 0
    assert result.seed == 0
    assert math.isfinite(result.total_reward)
    rejected = adapter.validate_policy({"schema": "rewardbench.lunarlander.controller.v1", "code": "x = 1"})
    assert rejected.valid is False
