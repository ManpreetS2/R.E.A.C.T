# A/B/C/D reward study — frozen plan (training not launched)

**Status:** Preflight complete. Formulas in `ABCD_REWARD_FREEZE.md`.  
**Do not train** the 12 runs until a separate explicit GO.

This study asks whether **different reward structures** produce different learned
landing behavior on original ApolloLander `sh_contact` starts — not whether we can
tune until one model looks good.

---

## How this differs from V3–V5 pilots

| | V3–V5 exploratory pilots | A/B/C/D study |
|--|--------------------------|---------------|
| Goal | Find any landing; sequential one-offs | Compare four rewards under matched protocol |
| Design | V3 A′ → V4 time-cost → V5 commitment | Parallel A/B/C/D |
| Seeds | One train seed (0); n=20 held-outs | 3 train seeds × 4; DEV n=50; held-out n=100 |
| Obs | V5 used 11-D | **Identical 10-D for all four** |
| D terminals | Older ±1 sketch | **Same +100/+40/−100/−100 as A/B/C** |
| V3-40k | Often misread as “A′ works” | Historical feasibility reference **only** — not Condition A’s expected outcome |

---

## Conditions (identical env except reward)

Shared: upstream physics · 10-D obs · MultiDiscrete[5,3] · ar=4 · `sh_contact` ·
timeout=`terminated` · PPO hyperparams · 200k physics frames · independent random init.

| Cond | Mode | Dense reward |
|------|------|----------------|
| **A** | `abcd_a` | α ΔΦ_A − c (α=10, c=0.005) |
| **B** | `abcd_b` | A + upright+slow **+1**/Gym step (hover bait ≤ +500/ep) |
| **C** | `abcd_c` | α (γ Φ_C′ − Φ_C) − c ; Φ_C = safe-touchdown potential (excess-vy only) |
| **D** | `abcd_d` | 0 dense; **same** native terminals as A/B/C |

C is a **redesigned** alternative (new Φ + γ-correction), not B-minus-bonus.

Legacy `sparse_d` (±1) is a possible future experiment — not primary D.

---

## Protocol

| Item | Spec |
|------|------|
| Train seeds | 0, 1, 2 per condition → **12 runs** |
| Train start bases | `abcd_train_auto_seed_base` (900k+) |
| Physics budget | ≤ 200 000 / run; ≤ 2.4 M total |
| DEV selection | `ABCD_DEV_SEEDS` n=50 |
| Held-out | `ABCD_HELD_OUT_SEEDS` n=100 — one-shot after selection |
| Metrics | Native perfect/hard/crash/timeout/reascent, frames, fuel, Wilson / seed-level uncertainty |
| Reporting | Every train seed; selected **and** final; honest 0% |

Full paths/commands: `ABCD_EXECUTION_MANIFEST.md`.

---

## Resources

| Quantity | Estimate |
|----------|----------|
| Train frames | 2.4 M |
| Wall-clock train | ~1–1.5 h (laptop CPU + Chromium) |
| Eval | ~2–4 h |
| Disk | ~1 GB |
| Paid cloud | Not required |

---

## Preflight status

| Gate | Doc / test |
|------|------------|
| Reward freeze | `ABCD_REWARD_FREEZE.md` |
| Scale audit | `outputs/abcd_preflight/ABCD_REWARD_AUDIT.md` |
| Fairness / leakage | `outputs/abcd_preflight/ABCD_FAIRNESS.json` |
| Unit tests | `tests/test_abcd_rewards.py` |
| Readiness | `ABCD_READINESS.md` |

**Experimental training budget: unused.**
