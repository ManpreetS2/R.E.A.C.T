# V4 results — `ppo_pilot_v4_timecost` (NEGATIVE vs V3-40k)

**Preflight:** PASSED (`outputs/preflight_v4/preflight_report.json`)  
**Physics budget:** **199 997** actual frames (cap 200 000; under-budget guard fired)  
**Sole change vs V3:** A′ time cost `c` **0.005 → 0.02**  
**Unavoidable impl diff:** physics budget callback refuses next Gym step when `frames + ar > cap`

V3-40k incumbent untouched (`models/.../ppo_apollo_40000_steps.zip`, SHA `4a1f2c85…`).

---

## Selected checkpoint (DEV only)

| Rule | max native land rate → min timeout rate → min mean flight duration |
|------|---------------------------------------------------------------------|
| **Selected** | `ppo_apollo_25000_steps` |
| SHA-256 | `7c785d8a7f3c10dfa97ac847bb5461d0c9e2a2dc50ae0943943c64f5822f495c` |
| DEV land | **2/20 = 10%** (Wilson 95%: 2.8–30.1%) |
| DEV timeout | 17/20 = 85% (all classified `timeout_post_approach_reascent`) |
| Beats V3-40k on DEV (60%)? | **No** |

Other V4 checkpoints never exceeded 10% DEV land; final/50k = 0%.

---

## One-shot held-out (`400000–400019`, n=20)

| Policy | Land | Perfect | Hard | Crash | Timeout | Mean frames | Mean fuel | Mean native score |
|--------|-----:|--------:|-----:|------:|--------:|------------:|----------:|------------------:|
| **V4 selected det** | **3/20 (15%)** | 0 | 3 | 2 | 15 | 1520 | 809 | 2.25 |
| V4 selected stoch (secondary) | 1/20 (5%) | 0 | 1 | 15 | 4 | 491 | 740 | 0.75 |
| **V3-40k det (incumbent)** | **10/20 (50%)** | 5 | 5 | 0 | 10 | 1054 | 855 | 16.25 |
| V4 step-0 | 0/20 | 0 | 0 | 20 | 0 | 90 | 699 | 0 |
| No-op | 0/20 | 0 | 0 | 20 | 0 | 86 | 688 | 0 |
| Random | 0/20 | 0 | 0 | 20 | 0 | 114 | 692 | 0 |
| Legal reference | 18/20 (90%) | 14 | 4 | 2 | 0 | 169 | 981 | 38 |

**Wilson 95% land intervals:** V4 det 5.2–36.0%; V3-40k 29.9–70.1%.

**Δ land rate (V4 − V3-40k) = −35 percentage points. V4 did not improve.**

DEV vs held-out: V4 selected 10% DEV / 15% held-out (both poor); V3-40k was 60% DEV / 50% held-out on this new pool.

---

## Failure analysis (V4 selected, held-out)

- **15/20** `timeout_post_approach_reascent` — reach `min_alt ≈ 0.4–10`, then climb to ~830–1040 and burn 2000 frames  
- **2/20** crash near surface  
- **3/20** hard landings (no perfect)  
- Stronger `c` did **not** eliminate abort-then-hover; timeouts remain the dominant mode

## Video evidence (original renderer)

- Success: `evidence/success_400006/native.mp4` (hard landing)  
- Failure: `evidence/failure_400000/native.mp4` (post-approach re-ascent timeout)

---

## Claims we are **not** making

- Not that `c=0.02` helps landing reliability  
- Not ready for A/B/C/D  
- Not that original_fixed / full-game start is solved  
- Not merging PR #11 on this result

## Recommendation (next research milestone)

**Preserve V3-40k as the incumbent.** Treat V4 `c=0.02` as a completed negative experiment.

Next single intervention (awaiting approval) should target **post-approach commitment**, e.g. late-phase altitude/descent shaping or an ascent penalty when `alt` has already been low — **not** another global time-cost multiply, and **not** A/B/C/D yet.
