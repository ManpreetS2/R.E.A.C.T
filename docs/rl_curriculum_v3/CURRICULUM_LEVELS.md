# Curriculum levels (v3)

All starts are physically legitimate in-world states of the original game:
`scale=0.25`, `fuel≤1000`, rotation on the 10° grid, positions above terrain /
within the locked camera arena. Derived via `derive_start(seed, version=…)`.

Pad geometry (fixed landscape): mid-x `6963.2`, pad y `679.4358077547447`.

| Level | Schedule version | Intent | dx from pad | y (pos) | approx altitude | vx | vy | rotations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| L0 | `curriculum_l0_v3` | Few px above pad, upright, near-zero vel | [−8, 8] | padY−18…padY−12 | ~9–15 px | [−0.01, 0.01] | [0.01, 0.035] | {0} |
| L1 | `curriculum_l1_v3` | Low altitude, small offsets | [−40, 40] | padY−80…padY−40 | ~37–77 | [−0.04, 0.04] | [0, 0.05] | {−10,0,10} |
| L2 | `curriculum_l2_v3` | Medium height / tilt | [−100, 20] | padY−200…padY−100 | ~97–197 | [−0.05, 0.12] | [−0.02, 0.06] | {−30…20} |
| L3 | `curriculum_l3_v3` | High, faster, more tilt | [−180, −40] | padY−400…padY−220 | ~217–397 | [0.05, 0.35] | [−0.03, 0.06] | {−60…0} |
| L4 | `curriculum_l4_v3` | = research `apollolander.starts.v1` | [−240, −80] | [90, 210] | high | [0.20, 0.63] | [−0.04, 0.06] | {−90…−30} |

## Why Family D (`curriculum_easy_v1`) got zero landings

See Phase 2 diagnosis in `REPORT.md`. Summary of the easy_v1 schedule vs L0:

- D “easy” still starts at y∈[500,620] (~60–180 px altitude) with rotations often
  ≠ 0, while native landing requires **exact** `rotation == 0`.
- Reward (`step_cost`) did not give a large enough landing bonus relative to
  surviving; discrete 95-way actions + action-repeat made precise upright contact rare.
- No gated progression from a near-certain-success start distribution.

## Gating (frozen before training)

Advance from level L→L+1 only when a **frozen** policy on a **fixed validation
seed set** (disjoint from training seeds) reaches **≥ 50% native landings**
(perfect+hard). Training-episode stats alone never advance the curriculum.
