# A/B/C/D reward-scale audit

**PASSED:** True

Diagnostic seeds only (`ABCD_AUDIT_SEEDS`). Held-out **not** consumed. No training.

## Gates

- PASS: `abcd_a_land_beats_crash` — `{'passed': True, 'land': 101.94573176383972, 'crash': -100.13784145832062}`
- PASS: `abcd_c_land_beats_crash` — `{'passed': True, 'land': 102.56365461081266, 'crash': -98.63895524859429}`
- PASS: `abcd_d_land_beats_crash` — `{'passed': True, 'land': 100.0, 'crash': -100.0}`
- PASS: `abcd_d_intermediate_zero` — `{'passed': True, 'terminal': -100.0}`
- PASS: `abcd_b_hover_bait_vs_a` — `{'passed': True, 'A': 103.43711520373822, 'B': 135.43711520373822, 'B_minus_A': 32.0, 'hover_steps_B': 33}`
- PASS: `abcd_c_distinct_from_a_dense` — `{'passed': True, 'A_dense': 1.9457317638397216, 'C_dense': 2.5636546108126645}`
- PASS: `shared_perfect_terminal_100` — `{'passed': True, 'terminals': {'abcd_a': 100.0, 'abcd_b': 100.0, 'abcd_c': 100.0, 'abcd_d': 100.0}}`
- PASS: `upstream_engine` — `{'passed': True}`
- PASS: `physics_outcome_match` — `{'passed': True}`
- PASS: `numerical_stability` — `{'passed': True}`
- PASS: `heldout_untouched` — `{'passed': True, 'heldout_pool': [800000, 800001, 800002, '...'], 'audit_pool': [55000, 55001, 55002, 55003, 55004, '...']}`

## Undiscounted returns by scenario × mode

| Scenario | abcd_a | abcd_b | abcd_c | abcd_d |
|----------|------:|------:|------:|------:|
| crash | -100.1 | -100.1 | -98.6 | -100.0 |
| hard_landing | 101.9 | 150.9 | 102.6 | 100.0 |
| perfect_landing | 101.9 | 150.9 | 102.6 | 100.0 |
| post_approach_reascent | -171.3 | -171.3 | -45.9 | -100.0 |
| timeout | -171.3 | -171.3 | -45.9 | -100.0 |
| unsafe_high_speed_descent | -100.1 | -100.1 | -98.6 | -100.0 |
| upright_hover | 103.4 | 135.4 | 104.8 | 100.0 |

## Discounted (γ=0.99)

| Scenario | abcd_a | abcd_b | abcd_c | abcd_d |
|----------|------:|------:|------:|------:|
| crash | -78.8 | -78.8 | -77.4 | -78.6 |
| hard_landing | 62.9 | 101.8 | 63.5 | 61.1 |
| perfect_landing | 62.9 | 101.8 | 63.5 | 61.1 |
| post_approach_reascent | -4.8 | -4.8 | 3.7 | -0.7 |
| timeout | -4.8 | -4.8 | 3.7 | -0.7 |
| unsafe_high_speed_descent | -78.8 | -78.8 | -77.4 | -78.6 |
| upright_hover | 75.9 | 103.4 | 77.2 | 72.5 |

## Hover bait (B)

Max cumulative +1 occupancy over ≤500 Gym steps = **+500**.

## Notes

- Terminals shared: +100/+40/−100/−100 from native perfect/hard/crash/timeout.
- C uses γ-corrected Φ_C (excess-vy only); not B-minus-hover.
- Legacy `sparse_d` (±1) is out of scope for primary D.

Full JSON: `/Users/manpreetsingh/Projects/R.E.A.C.T/experiments/apollo_gymnasium/outputs/abcd_preflight/ABCD_REWARD_AUDIT.json`
