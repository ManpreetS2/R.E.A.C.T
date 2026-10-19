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

# V5 held-out — fresh after V4 contamination of 400k.
V5_HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(500_000, 500_020))

# Champion validation only (V3-40k freeze). Evaluation-only; never use for selection/tuning.
# n=100 sh_contact starts, disjoint from train/dev/held-out pilots.
CHAMPION_VAL_SEEDS: tuple[int, ...] = tuple(range(600_000, 600_100))

# A/B/C/D study pools (preregistered; unused until study launch is approved).
ABCD_DEV_SEEDS: tuple[int, ...] = tuple(range(700_000, 700_050))
ABCD_HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(800_000, 800_100))

# Sanity: pools disjoint
assert not set(DEV_EVAL_SEEDS) & set(HELD_OUT_SEEDS)
assert not set(DEV_EVAL_SEEDS) & set(V4_HELD_OUT_SEEDS)
assert not set(DEV_EVAL_SEEDS) & set(V5_HELD_OUT_SEEDS)
assert not set(DEV_EVAL_SEEDS) & set(CHAMPION_VAL_SEEDS)
assert not set(HELD_OUT_SEEDS) & set(V4_HELD_OUT_SEEDS)
assert not set(HELD_OUT_SEEDS) & set(V5_HELD_OUT_SEEDS)
assert not set(V4_HELD_OUT_SEEDS) & set(V5_HELD_OUT_SEEDS)
assert not set(CHAMPION_VAL_SEEDS) & set(V5_HELD_OUT_SEEDS)
assert not set(CHAMPION_VAL_SEEDS) & set(ABCD_DEV_SEEDS)
assert not set(CHAMPION_VAL_SEEDS) & set(ABCD_HELD_OUT_SEEDS)
assert not set(ABCD_DEV_SEEDS) & set(ABCD_HELD_OUT_SEEDS)
assert TRAIN_SEED_BASE < min(DEV_EVAL_SEEDS)
assert max(DEV_EVAL_SEEDS) < min(HELD_OUT_SEEDS)
assert max(HELD_OUT_SEEDS) < min(V4_HELD_OUT_SEEDS)
assert max(V4_HELD_OUT_SEEDS) < min(V5_HELD_OUT_SEEDS)
assert max(V5_HELD_OUT_SEEDS) < min(CHAMPION_VAL_SEEDS)
assert max(CHAMPION_VAL_SEEDS) < min(ABCD_DEV_SEEDS)
assert max(ABCD_DEV_SEEDS) < min(ABCD_HELD_OUT_SEEDS)
assert len(CHAMPION_VAL_SEEDS) >= 100
