# A/B/C/D readiness report — research freeze

**Date:** 2026-10-19  
**PR:** [#11](https://github.com/ManpreetS2/R.E.A.C.T/pull/11) (draft — **do not merge**)  
**Training of 12 PPO runs:** **NOT AUTHORIZED / NOT STARTED**  
**Held-out `ABCD_HELD_OUT_SEEDS`:** **untouched**

---

## Preflight results

| Gate | Result |
|------|--------|
| Reward freeze (`ABCD_REWARD_FREEZE.md`) | **PASS** — A/B/C/D formulas locked |
| Unit tests (`tests/test_abcd_rewards.py`) | **PASS** |
| Fairness / leakage (`ABCD_FAIRNESS.json`) | **PASS** |
| Reward-scale audit (`ABCD_REWARD_AUDIT.md`) | **PASS** |
| Physics budget guard | **PASS** (stops when frames+ar > 200k) |
| V3–V5 negative pilots preserved | **PASS** |
| Experimental train budget consumed | **0 / 2.4M frames** |

### Audit highlights (diagnostic seeds only)

| Check | Result |
|-------|--------|
| Shared terminals +100/+40/−100/−100 | Yes (all four) |
| D intermediate rewards = 0 | Yes |
| A/C/D: land ≫ crash (undiscounted) | Yes |
| B hover bait vs A | **+32** on forced-hover traj (33 hover steps); max bait **+500**/ep documented |
| C dense ≠ A dense | Yes (γ-corrected Φ_C) |
| Upstream native outcomes | Confirmed |
| Numerical \|r\| < 1e4 | Yes |

No coefficient retune after audit.

---

## Fair experiment checklist

- [x] Identical original physics  
- [x] Identical 10-D observations (no V5 latch)  
- [x] Identical MultiDiscrete + ar=4  
- [x] Identical `sh_contact` / `short_horizon.v1`  
- [x] Identical PPO hyperparams (γ=0.99, lr=3e-4, …)  
- [x] Seeds 0,1,2 · independent init · 12 disjoint train bases  
- [x] 200k frame cap / run · 2.4M study cap  
- [x] DEV n=50 select · held-out n=100 reserved  
- [x] V3-40k kept as historical reference only  

---

## GO / NO-GO

| Decision | Recommendation |
|----------|----------------|
| Merge PR #11 | **NO-GO** |
| Launch 12 PPO runs now | **NO-GO** — await explicit approval |
| Consume held-out / tune on DEV | **NO-GO** |
| Further V-series commitment tuning | **NO-GO** |
| Treat freeze + audit as complete preflight | **GO** |
| Next action after human GO | Execute manifest commands only; no mid-study retunes |

### Overall: **YELLOW → GREEN for documentation/preflight; RED for training until approved**

The study is **scientifically ready to run** under the frozen protocol. It is **not** cleared to spend the 2.4M-frame budget without a separate GO.

**Objective reminder:** evaluate whether reward structure changes learned landing behavior — not engineer a predetermined winner.
