# Research readiness report — post V5 reset

**Date:** 2026-10-19  
**PR:** [#11](https://github.com/ManpreetS2/R.E.A.C.T/pull/11) (draft; **do not merge**)  
**Training launched this reset:** **none** (V6 forbidden; A/B/C/D not started)

---

## 1. V5 finalized (negative)

| Item | Status |
|------|--------|
| Actual physics frames | **199 999** / 200 000 |
| Freeze manifest | `outputs/ppo_pilot_v5_commitment/v5_freeze_manifest.json` |
| Selected checkpoint | **step0** (SHA `f98153e1…`) — all DEV land rates were 0% |
| Trained final held-out | **0/20 land** (crash) |
| Trained 25k held-out | **0/20 land** (15/20 reascent) |
| Failure footage | `evidence/failure_500000/native.mp4` preserved |
| Failure autopsy | `failure_autopsy/FAILURE_AUTOPSY.md` |

**Selected ≠ “best trained.”** Reporting now separates step0/selected from trained mid/final.

**Autopsy headline:** Undiscounted V5 returns make long soft reascent far worse than early crash (Σ commit ≈ −261 on V3-style ascents). Under PPO γ=0.99, distant penalties dilute so discounted reascent can beat crash — late crash collapse is **not** solely “return prefers crash.” Obs 11-D vs reward penalty remain confounded.

---

## 2. Champion validation (evaluation only)

Frozen V3-40k SHA `4a1f2c85…` on preregistered **`CHAMPION_VAL_SEEDS` n=100** (`600000–600099`), **`sh_contact` only**.

| Policy | Land | Wilson 95% | Crash | Timeout | Reascent |
|--------|-----:|-----------:|------:|--------:|---------:|
| **V3-40k det** | **53/100 (53%)** | [43.3%, 62.5%] | 0 | 47 | 47 |
| V3 step-0 | 0% | [0%, 3.7%] | 100 | 0 | 0 |
| No-op / random | 0% | [0%, 3.7%] | 100 | 0 | 0 |
| Legal reference | 85% | [76.7%, 90.7%] | 15 | 0 | 0 |

**Not** original full-game performance. **Not** an unbiased estimate of a fresh A′ training run (DEV-selected checkpoint from one seed-0 pilot).

Dominant V3 failure remains **post-approach reascent** (47/100).

Artifacts: `outputs/champion_validation_v3_40k/`.

---

## 3. A/B/C/D study — designed, not launched

See `ABCD_STUDY_PLAN.md`.

| | Spec |
|--|------|
| Conditions | A baseline A′ · B hover bait · C corrected (freeze after audit) · D sparse ±1 |
| Obs/actions | **Identical 10-D** / MultiDiscrete for all four |
| Seeds | ≥3 train seeds × 4 = 12 runs |
| Budget | 200 000 physics frames / run → **2.4 M** frames total |
| Eval | DEV n=50 select; held-out n=100 one-shot |
| Compute | ~1–1.5 h train + ~2–4 h eval on 1 CPU laptop + Chromium |
| Paid infra | Not required |

Differs from V3–V5: parallel matched protocol, multi-seed, fixed obs, preregistered pools — not sequential one-off pilots.

---

## 4. Resource estimate (A/B/C/D)

| Resource | Estimate |
|----------|----------|
| Physics frames | 2.4 M train + ~0.5–1 M eval |
| Wall-clock | ~4–6 hours total on current laptop |
| Disk | ~1 GB |
| Human | Preflight audits + report writing ~0.5–1 day |

---

## 5. Go / no-go

| Decision | Recommendation | Rationale |
|----------|----------------|-----------|
| Merge PR #11 | **NO-GO** | Draft research log; landing not solved |
| Launch V6 / more commitment tuning | **NO-GO** | V5 negative; confound (obs+reward); goal ≠ tune until pretty |
| Launch A/B/C/D now | **NO-GO (conditional)** | Design ready, but freeze Condition C after a reward-scale audit document first; ensure CI/disk for 12 runs |
| Treat V3-40k as champion on `sh_contact` | **GO (qualified)** | 53% [43–63%] on n=100 vs 0% baselines / 85% reference; still ~half reascent failures |
| Claim original-game solved | **NO-GO** | `sh_contact` ≠ full spawn |
| Next scientific step | **GO: preflight A/B/C/D only** | Write `ABCD_REWARD_FREEZE.md` + scale audits; **then** seek explicit approval to train |

### Overall readiness: **YELLOW**

Credible comparative reward study is **design-ready**. Execution should wait for (1) frozen C after audit, (2) explicit budget approval for 12×200k frames, (3) no further exploratory V-series pilots that contaminate the narrative.

**Goal reminder:** test whether reward design changes learning — not keep tuning until one model looks good.
