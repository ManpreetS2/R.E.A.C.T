# V3 pilot results — `ppo_pilot_v3_contact_Aprime`

**Preflight:** PASSED (`outputs/preflight_v3/preflight_report.json`)  
**Physics budget:** 200 003 actual engine frames (hard cap 200 000)  
**Config:** `sh_contact` seed-varied · A′ (α=10, c=0.005) · ar=4 · timeout=`terminated` · seed 0  

Prior pilots (v1 hover, v2 crash) unchanged.

---

## Milestone claims (separate)

### 1. First genuinely trained landing on nontrivial `sh_contact` — **YES**

- Deterministic final PPO landed on held-out seeds with native `LANDED` / perfect.
- No-input does **not** land on those starts (`noop_also_lands=false`).
- Evidence package: `landing_evidence/` (model SHA-256, seed 300001, start state, action trace, native score 50, original-renderer MP4).

### 2. Improvement over untrained baselines — **YES**

| Policy (held-out, n=20) | Land rate | Perfect | Hard | Crash | Timeout |
|-------------------------|----------:|--------:|-----:|------:|--------:|
| No-input | 0.00 | 0 | 0 | 1.00 | 0 |
| Random | 0.00 | 0 | 0 | 1.00 | 0 |
| Step-0 PPO (dev) | 0.00 | 0 | 0 | 1.00 | 0 |
| **Final PPO deterministic** | **0.40** | **0.35** | **0.05** | **0** | **0.60** |
| Final PPO stochastic | 0.00 | 0 | 0 | 0.50 | 0.50 |
| Legal reference (feasibility) | 0.90 | 0.90 | 0 | 0.10 | 0 |

### 3. Generalization to unseen starts — **PARTIAL / CAUTION**

- Held-out land rate **40%** (unseen seeds 300000–300019).
- Dev-eval final was only **10%** land / **90%** timeout (n=20) — high variance; do not over-claim robustness.
- Stochastic policy **0%** land on both pools — policy is brittle; deterministic mode matters.
- Dominant failure mode remains **timeout** (hover/delay), not crash.

---

## Dev checkpoint trajectory

| Checkpoint | Land | Crash | Timeout | Mean frames |
|------------|-----:|------:|--------:|------------:|
| step0 | 0.00 | 1.00 | 0.00 | 92 |
| 25k gym steps | 0.00 | 0.60 | 0.40 | 867 |
| final (det) | 0.10 | 0.00 | 0.90 | 1810 |

Training lengthened episodes (survival) then produced some landings; timeout rate rose.

---

## What we are **not** claiming

- Not solved original_fixed / full game start.
- Not ready for A/B/C/D.
- Not that stochastic or “always” lands.
- Not more training without approval.

## Next justified change (if continuing)

Timeout still dominates (60% held-out). Investigate denser late-phase landing bonus or slightly stronger time cost under A′, **or** select best-of-checkpoint by **native land rate** on DEV (not train return) before another budget — only with approval.
