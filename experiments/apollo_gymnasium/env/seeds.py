"""Preregistered seed pools for Apollo Gymnasium experiments.

Diagnostic probes used seeds in roughly 0–10k and 50_000+. Those ranges are
reserved as contaminated for final claims. Study pools live at ≥100_000 and are
mutually disjoint.
"""

from __future__ import annotations

# Online training (historical V3–V5 pilots): VecEnv auto-reset uses base + episode index.
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
CHAMPION_VAL_SEEDS: tuple[int, ...] = tuple(range(600_000, 600_100))

# A/B/C/D study pools (preregistered; held-out untouched until after selection).
ABCD_DEV_SEEDS: tuple[int, ...] = tuple(range(700_000, 700_050))
ABCD_HELD_OUT_SEEDS: tuple[int, ...] = tuple(range(800_000, 800_100))

# Reward-scale audit only — contaminated diagnostic band; NEVER use for claims / held-out.
ABCD_AUDIT_SEEDS: tuple[int, ...] = tuple(range(55_000, 55_030))

# Per-run training start streams for A/B/C/D (condition × train_seed → auto_seed_base).
# Episode seeds become auto_seed_base + episode_idx (and SB3 init seeds map upward).
ABCD_CONDITIONS: tuple[str, ...] = ("A", "B", "C", "D")
ABCD_TRAIN_SEEDS: tuple[int, ...] = (0, 1, 2)
ABCD_REWARD_MODE: dict[str, str] = {
    "A": "abcd_a",
    "B": "abcd_b",
    "C": "abcd_c",
    "D": "abcd_d",
}


def abcd_train_auto_seed_base(condition: str, train_seed: int) -> int:
    """Disjoint start streams: 900_000 + cond_index*30_000 + train_seed*10_000."""
    if condition not in ABCD_CONDITIONS:
        raise ValueError(condition)
    if train_seed not in ABCD_TRAIN_SEEDS:
        raise ValueError(train_seed)
    ci = ABCD_CONDITIONS.index(condition)
    return int(900_000 + ci * 30_000 + int(train_seed) * 10_000)


ABCD_TRAIN_BASES: dict[tuple[str, int], int] = {
    (c, s): abcd_train_auto_seed_base(c, s)
    for c in ABCD_CONDITIONS
    for s in ABCD_TRAIN_SEEDS
}

# Sanity: pools disjoint
_ALL_CLAIM_POOLS = [
    set(DEV_EVAL_SEEDS),
    set(HELD_OUT_SEEDS),
    set(V4_HELD_OUT_SEEDS),
    set(V5_HELD_OUT_SEEDS),
    set(CHAMPION_VAL_SEEDS),
    set(ABCD_DEV_SEEDS),
    set(ABCD_HELD_OUT_SEEDS),
]
for i, a in enumerate(_ALL_CLAIM_POOLS):
    for b in _ALL_CLAIM_POOLS[i + 1 :]:
        assert not (a & b), "seed pool overlap"

assert not set(ABCD_AUDIT_SEEDS) & set(ABCD_DEV_SEEDS)
assert not set(ABCD_AUDIT_SEEDS) & set(ABCD_HELD_OUT_SEEDS)
assert max(ABCD_AUDIT_SEEDS) < TRAIN_SEED_BASE
assert TRAIN_SEED_BASE < min(DEV_EVAL_SEEDS)
assert max(DEV_EVAL_SEEDS) < min(HELD_OUT_SEEDS)
assert max(HELD_OUT_SEEDS) < min(V4_HELD_OUT_SEEDS)
assert max(V4_HELD_OUT_SEEDS) < min(V5_HELD_OUT_SEEDS)
assert max(V5_HELD_OUT_SEEDS) < min(CHAMPION_VAL_SEEDS)
assert max(CHAMPION_VAL_SEEDS) < min(ABCD_DEV_SEEDS)
assert max(ABCD_DEV_SEEDS) < min(ABCD_HELD_OUT_SEEDS)
assert max(ABCD_HELD_OUT_SEEDS) < min(ABCD_TRAIN_BASES.values())
assert len(CHAMPION_VAL_SEEDS) >= 100
assert len(ABCD_DEV_SEEDS) == 50
assert len(ABCD_HELD_OUT_SEEDS) == 100
assert len(ABCD_TRAIN_BASES) == 12

# Train bases must not collide with eval pools (eval seeds are absolute episode seeds).
_train_base_set = set(ABCD_TRAIN_BASES.values())
assert not _train_base_set & set(ABCD_DEV_SEEDS)
assert not _train_base_set & set(ABCD_HELD_OUT_SEEDS)
# Bases are spaced by ≥10k; 200k frames / ~100 frames/ep ≈ 2k episodes << 10k gap.
