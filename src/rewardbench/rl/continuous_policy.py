"""Hybrid continuous-thrust + categorical-rotation actor-critic.

Thrust uses a squashed Gaussian in [0, 1] (upstream ``lander.thrust(power)``
supports continuous power via the touch path). Rotation is categorical over
the player-legal 10° ``setRotation`` bins in [-90, 90].

This module is for curriculum-v3 training only. It does not load guidance
parameters or traces.
"""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.distributions import Categorical, Normal

from rewardbench.rl.physics_python import N_ROTATION, OBS_DIM, ROTATION_BINS

# Player-legal relative setRotation steps (still commanded via absolute setRotation).
ROTATION_DELTAS = (-10, 0, 10)
N_ROTATION_DELTAS = len(ROTATION_DELTAS)


class ContinuousThrustActorCritic(nn.Module):
    """Randomly initialized hybrid policy/value network."""

    def __init__(
        self,
        obs_dim: int = OBS_DIM,
        n_rotations: int = N_ROTATION,
        hidden: int = 128,
        rotation_mode: str = "absolute",
        soft_thrust_prior: bool = False,
        hold_attitude_prior: bool = False,
    ) -> None:
        super().__init__()
        self.obs_dim = obs_dim
        self.rotation_mode = rotation_mode
        self.soft_thrust_prior = soft_thrust_prior
        self.hold_attitude_prior = hold_attitude_prior
        if rotation_mode == "delta":
            n_rotations = N_ROTATION_DELTAS
            self.rotation_bins = torch.as_tensor(ROTATION_DELTAS, dtype=torch.float32)
        else:
            self.rotation_bins = torch.as_tensor(ROTATION_BINS, dtype=torch.float32)
        self.n_rotations = n_rotations
        self.trunk = nn.Sequential(
            nn.Linear(obs_dim, hidden),
            nn.Tanh(),
            nn.Linear(hidden, hidden),
            nn.Tanh(),
        )
        self.thrust_mean = nn.Linear(hidden, 1)
        self.thrust_log_std = nn.Parameter(torch.zeros(1))
        self.rotation_head = nn.Linear(hidden, n_rotations)
        self.value_head = nn.Linear(hidden, 1)
        self.reset_parameters()

    def reset_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.orthogonal_(module.weight, gain=1.0)
                nn.init.constant_(module.bias, 0.0)
        nn.init.orthogonal_(self.thrust_mean.weight, gain=0.01)
        nn.init.orthogonal_(self.rotation_head.weight, gain=0.01)
        # Documented random-init priors (NOT guidance parameters / traces):
        # soft thrust ~0.22 and hold-attitude (delta 0) so L0 episodes can
        # occasionally contact upright before the policy collapses to hover.
        # Clean-learning experiments must leave both prior flags False and call
        # ``reset_parameters_clean`` instead (orthogonal + zero bias, no head gain tweak).
        if self.soft_thrust_prior:
            nn.init.constant_(self.thrust_mean.bias, -1.25)  # sigmoid ≈ 0.22
            with torch.no_grad():
                self.thrust_log_std.fill_(-0.5)
        if self.hold_attitude_prior and self.rotation_mode == "delta":
            # ROTATION_DELTAS = (-10, 0, 10) → index 1 is hold.
            with torch.no_grad():
                self.rotation_head.bias.zero_()
                self.rotation_head.bias[1] = 2.5

    def reset_parameters_clean(self) -> None:
        """Orthogonal weights (gain=1.0), zero biases, thrust_log_std=0.

        No output-layer priors, no head gain shrink, no maneuver bias.
        Requires ``soft_thrust_prior`` and ``hold_attitude_prior`` to be False.
        """
        if self.soft_thrust_prior or self.hold_attitude_prior:
            raise ValueError(
                "reset_parameters_clean forbids soft_thrust_prior/hold_attitude_prior"
            )
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.orthogonal_(module.weight, gain=1.0)
                nn.init.constant_(module.bias, 0.0)
        with torch.no_grad():
            self.thrust_log_std.zero_()

    def forward(
        self, obs: torch.Tensor
    ) -> tuple[Normal, Categorical, torch.Tensor]:
        features = self.trunk(obs)
        # Pre-squash mean in R; sample then sigmoid → [0, 1].
        mean = self.thrust_mean(features).squeeze(-1)
        std = self.thrust_log_std.exp().expand_as(mean)
        thrust_dist = Normal(mean, std)
        rot_dist = Categorical(logits=self.rotation_head(features))
        value = self.value_head(features).squeeze(-1)
        return thrust_dist, rot_dist, value

    @staticmethod
    def squash_thrust(raw: torch.Tensor) -> torch.Tensor:
        return torch.sigmoid(raw)

    @staticmethod
    def thrust_log_prob(dist: Normal, raw: torch.Tensor, thrust: torch.Tensor) -> torch.Tensor:
        # Change-of-variables: sigmoid'(x) = s(1-s).
        log_prob = dist.log_prob(raw)
        eps = 1e-6
        thrust_clamped = thrust.clamp(eps, 1.0 - eps)
        log_prob = log_prob - torch.log(thrust_clamped * (1.0 - thrust_clamped) + eps)
        return log_prob

    def act(
        self, obs: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        thrust_dist, rot_dist, value = self.forward(obs)
        raw = thrust_dist.rsample() if False else thrust_dist.sample()
        thrust = self.squash_thrust(raw)
        rotation_idx = rot_dist.sample()
        log_prob = self.thrust_log_prob(thrust_dist, raw, thrust) + rot_dist.log_prob(rotation_idx)
        return thrust, rotation_idx, raw, log_prob, value

    def act_deterministic(
        self, obs: torch.Tensor
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        thrust_dist, rot_dist, value = self.forward(obs)
        raw = thrust_dist.mean
        thrust = self.squash_thrust(raw)
        rotation_idx = torch.argmax(rot_dist.logits, dim=-1)
        return thrust, rotation_idx, value

    def evaluate_actions(
        self,
        obs: torch.Tensor,
        raw_thrust: torch.Tensor,
        rotation_idx: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        thrust_dist, rot_dist, value = self.forward(obs)
        thrust = self.squash_thrust(raw_thrust)
        log_prob = self.thrust_log_prob(thrust_dist, raw_thrust, thrust) + rot_dist.log_prob(
            rotation_idx
        )
        # Entropy of pre-squash Gaussian + categorical (approximation for thrust).
        entropy = thrust_dist.entropy() + rot_dist.entropy()
        return log_prob, entropy, value

    def decode_rotation(self, rotation_idx: torch.Tensor) -> torch.Tensor:
        bins = self.rotation_bins.to(rotation_idx.device)
        return bins[rotation_idx.long()]


def rotation_index_to_degrees(index: int) -> int:
    return int(ROTATION_BINS[int(index)])


def degrees_to_rotation_index(degrees: float) -> int:
    bins = ROTATION_BINS
    return int(min(range(len(bins)), key=lambda i: abs(float(bins[i]) - float(degrees))))


# Silence unused import lint in some environments.
_ = math
