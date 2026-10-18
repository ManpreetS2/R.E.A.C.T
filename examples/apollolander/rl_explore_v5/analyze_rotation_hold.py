#!/usr/bin/env python3
"""Analytical + offline Monte Carlo: holding rotation==0 under per-frame delta actions.

Zero physics frames. Documents keyboard rate-limit vs RL per-frame delta.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent / "results" / "EXPLORE_v5"
OUT.mkdir(parents=True, exist_ok=True)


def stationary_mass_at_zero() -> dict:
    """Symmetric random walk on bins {-9..9} (units of 10°), steps {-1,0,+1} w.p. 1/3.

    Reflecting barriers at ±9. Stationary distribution is uniform on interior
    for this lazy walk with reflection — compute by power iteration.
    """
    bins = list(range(-9, 10))  # -90..90
    idx = {b: i for i, b in enumerate(bins)}
    n = len(bins)
    P = np.zeros((n, n))
    for b in bins:
        for db, p in ((-1, 1 / 3), (0, 1 / 3), (1, 1 / 3)):
            nb = b + db
            if nb < -9:
                nb = -9
            if nb > 9:
                nb = 9
            P[idx[b], idx[nb]] += p
    pi = np.ones(n) / n
    for _ in range(10_000):
        pi = pi @ P
    return {
        "bins_10deg": bins,
        "P_at_0": float(pi[idx[0]]),
        "P_at_0_closed_form_uniform_approx": 1 / 19,
        "note": (
            "Lazy reflecting walk on 19 bins; stationary P(θ=0)≈1/19≈0.0526 "
            "if nearly uniform. Exact via power iteration."
        ),
        "exact_stationary_P0": float(pi[idx[0]]),
    }


def prob_still_zero_after_t(t: int, p_hold: float = 1 / 3) -> float:
    """Start at 0; each step stay with p_hold, else ±1 with equal share of remainder.

    Exact recurrence for mass at 0 (unbounded would be Bessel; with barriers we MC).
    For short T before barriers matter, P(at 0 after t) for lazy SSRW.
    """
    # Unbounded lazy walk: each step X in {-1,0,1}; after t steps at 0 iff
    # #right - #left = 0 and any holds. Closed form via trinomial.
    # P(S_t=0) = sum_{k=0}^{floor(t/2)} C(t; k,k,t-2k) * (p_m)^k (p_p)^k (p_h)^{t-2k}
    p_h = p_hold
    p_m = p_p = (1 - p_hold) / 2
    total = 0.0
    for k in range(t // 2 + 1):
        holds = t - 2 * k
        # multinomial coeff
        coeff = math.factorial(t) / (
            math.factorial(k) * math.factorial(k) * math.factorial(holds)
        )
        total += coeff * (p_m**k) * (p_p**k) * (p_h**holds)
    return total


def mc_fraction_at_zero_at_contact(
    *,
    n_episodes: int = 5000,
    contact_steps: int = 180,
    p_hold: float = 1 / 3,
    seed: int = 0,
) -> dict:
    rng = np.random.default_rng(seed)
    at0 = 0
    for _ in range(n_episodes):
        theta = 0
        for _ in range(contact_steps):
            u = rng.random()
            if u < p_hold:
                d = 0
            elif u < p_hold + (1 - p_hold) / 2:
                d = -1
            else:
                d = 1
            theta = int(np.clip(theta + d, -9, 9))
        if theta == 0:
            at0 += 1
    return {
        "n_episodes": n_episodes,
        "contact_steps": contact_steps,
        "p_hold": p_hold,
        "fraction_at_0": at0 / n_episodes,
        "count_at_0": at0,
    }


def keyboard_vs_rl() -> dict:
    """Upstream keyboard: rotate ±15° at most once per 80ms; game at 60fps."""
    fps = 60
    rotate_min_ms = 80
    frames_per_rotate = rotate_min_ms / (1000 / fps)  # 4.8 frames
    return {
        "game_fps": fps,
        "keyboard_rotate_min_interval_ms": rotate_min_ms,
        "keyboard_max_rotate_hz": 1000 / rotate_min_ms,
        "physics_frames_per_allowed_rotate": frames_per_rotate,
        "keyboard_step_degrees": 15,
        "setRotation_quantization_deg": 10,
        "rl_delta_per_physics_frame_deg": [-10, 0, 10],
        "implication": (
            "A human holding no arrow key issues zero rotate() calls, so "
            "targetRotation is unchanged and attitude settles to the held angle. "
            "An RL policy that samples {-10,0,+10} every physics frame (60 Hz) "
            "perturbs attitude ~12× more often than the keyboard rate limit allows, "
            "making sustained rotation==0 rare unless hold is sampled repeatedly."
        ),
    }


def main() -> None:
    stat = stationary_mass_at_zero()
    series = {str(t): prob_still_zero_after_t(t) for t in (1, 5, 10, 20, 50, 100, 180)}
    mc180 = mc_fraction_at_zero_at_contact(contact_steps=180)
    mc_hold = {
        str(ph): mc_fraction_at_zero_at_contact(contact_steps=180, p_hold=ph, seed=1)
        for ph in (1 / 3, 0.6, 0.8)
    }
    # action_repeat k: same delta held for k frames → effective decision rate 60/k Hz
    ar = {}
    for k in (1, 4, 8, 16):
        decisions = max(1, 180 // k)
        ar[str(k)] = {
            "decisions_to_contact_approx": decisions,
            "unbounded_P_at_0_after_decisions": prob_still_zero_after_t(decisions),
            "mc": mc_fraction_at_zero_at_contact(
                contact_steps=decisions, p_hold=1 / 3, seed=2 + k
            ),
        }
    out = {
        "stationary": stat,
        "unbounded_P_at_0_after_t_steps_p_hold_1_3": series,
        "mc_at_contact_180_steps": mc180,
        "mc_vs_p_hold": mc_hold,
        "action_repeat_effect_approx": ar,
        "keyboard_vs_rl": keyboard_vs_rl(),
        "root_cause_statement": (
            "Landing requires lander.rotation==0 exactly at contact. "
            "Uniform random delta {-10,0,+10} each physics frame yields "
            f"≈{mc180['fraction_at_0']:.3f} chance of being at 0 after ~180 steps "
            f"(stationary ≈{stat['exact_stationary_P0']:.3f}). "
            "Keyboard play naturally holds attitude by not pressing rotate "
            "(80ms rate limit); per-frame RL delta does not."
        ),
    }
    path = OUT / "rotation_hold_analysis.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
