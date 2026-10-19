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
# V3 inspected these; do not reuse for V4 claims.
HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(300_000, 300_020))

# V4 held-out — completely new; reserve until after V4 DEV checkpoint selection.
# Contaminated ranges: V3 held-out 300k, diagnostics <100k.
V4_HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(400_000, 400_020))

# Sanity: pools disjoint
assert not set(DEV_EVAL_SEEDS) & set(HELD_OUT_SEEDS)
assert not set(DEV_EVAL_SEEDS) & set(V4_HELD_OUT_SEEDS)
assert not set(HELD_OUT_SEEDS) & set(V4_HELD_OUT_SEEDS)
assert TRAIN_SEED_BASE < min(DEV_EVAL_SEEDS)
assert max(DEV_EVAL_SEEDS) < min(HELD_OUT_SEEDS)
assert max(HELD_OUT_SEEDS) < min(V4_HELD_OUT_SEEDS)
