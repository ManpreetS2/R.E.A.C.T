# Champion validation — frozen V3-40k (evaluation only)

**Model SHA-256:** `4a1f2c85e2b87e30e6257bbdde3e4a6a88df9d543f135ed620c3027290a78975`
**Pool:** `CHAMPION_VAL_SEEDS` n=100 (`600000`–`600099`)
**Start:** `sh_contact` only — **not** original full-game start.
**No training / no tuning / no checkpoint selection.**

| Policy | Land | Perfect | Hard | Crash | Timeout | Reascent | Mean frames | Mean fuel | Land Wilson 95% |
|--------|-----:|--------:|-----:|------:|--------:|---------:|------------:|----------:|----------------:|
| V3-40k det | 53/100 (53.0%) | 23 | 30 | 0 | 47 | 47 | 999 | 862 | [43.3%, 62.5%] |
| V3 step-0 | 0/100 (0.0%) | 0 | 0 | 100 | 0 | 0 | 91 | 694 | [0.0%, 3.7%] |
| No-op | 0/100 (0.0%) | 0 | 0 | 100 | 0 | 0 | 87 | 698 | [0.0%, 3.7%] |
| Random | 0/100 (0.0%) | 0 | 0 | 100 | 0 | 0 | 115 | 695 | [0.0%, 3.7%] |
| Legal reference | 85/100 (85.0%) | 79 | 6 | 15 | 0 | 0 | 169 | 972 | [76.7%, 90.7%] |

V3-40k failure modes: `{'timeout_post_approach_reascent': 47}`

## Claims we are not making

- Not that V3-40k solves the original game from arbitrary starts.
- Not an unbiased estimate of a fresh training run (checkpoint was DEV-selected).
- Not license to tune hyperparameters on this pool.
