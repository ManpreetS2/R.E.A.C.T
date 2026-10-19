"""Preregistered seed pools for Apollo Gymnasium V3 (disjoint from diagnostic seeds).

Diagnostic probes used seeds in roughly 0–10k and 50_000+. Those ranges are
reserved as contaminated for final claims. V3 pools live at ≥100_000.
"""

from __future__ import annotations

# Online training: VecEnv auto-reset uses base + episode index (see ApolloLanderGym).
TRAIN_SEED_BASE = 100_000

# Development evaluation / checkpoint selection (do not use for final claims).
DEV_EVAL_SEEDS: tuple[int, ...] = tuple(range(200_000, 200_020))

# Final held-out — untouched until after checkpoint selection.
HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(300_000, 300_020))

# Sanity: pools disjoint
assert not set(DEV_EVAL_SEEDS) & set(HELD_OUT_SEEDS)
assert TRAIN_SEED_BASE < min(DEV_EVAL_SEEDS)
assert max(DEV_EVAL_SEEDS) < min(HELD_OUT_SEEDS)
