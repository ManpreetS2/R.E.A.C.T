"""Clean init must have no output-layer priors or head-gain tweaks."""

from __future__ import annotations

import torch

from rewardbench.rl.continuous_policy import ContinuousThrustActorCritic


def test_reset_parameters_clean_orthogonal_zero_bias() -> None:
    torch.manual_seed(0)
    pol = ContinuousThrustActorCritic(
        hidden=32, rotation_mode="delta", soft_thrust_prior=False, hold_attitude_prior=False
    )
    pol.reset_parameters_clean()
    assert float(pol.thrust_mean.bias) == 0.0
    assert torch.all(pol.rotation_head.bias == 0).item()
    assert float(pol.thrust_log_std) == 0.0
    # Weights are finite / non-zero (orthogonal).
    assert pol.thrust_mean.weight.abs().sum().item() > 0
    assert pol.rotation_head.weight.abs().sum().item() > 0


def test_reset_parameters_clean_rejects_priors() -> None:
    pol = ContinuousThrustActorCritic(
        hidden=16, rotation_mode="delta", soft_thrust_prior=True, hold_attitude_prior=False
    )
    try:
        pol.reset_parameters_clean()
        raised = False
    except ValueError:
        raised = True
    assert raised
