# Phase 4 — Reward shaping experiments (Hari tutorial)

**Branch:** `experiment/simple-gym-lunarlander`  
**Guide:** *Training an AI to land a rocket with reward shaping* — Hari (@harixganesh)  
**Env:** Gymnasium `LunarLander-v3` · **Algo:** SB3 PPO `MlpPolicy` 64×64 · **Budget:** 1e6 steps each  

Exact equations: [`REWARD_DEFINITIONS.md`](REWARD_DEFINITIONS.md)

---

## Setup consistency

| Item | A | B | C |
|------|---|---|---|
| Physics / actions / obs | LunarLander-v3 defaults | same | same |
| PPO / net | MlpPolicy 64×64 | same | same |
| Seed | 0 | 0 | 0 |
| n_envs | 4 | 4 | 4 |
| Timesteps | 1e6 | 1e6 | 1e6 |
| Train reward | native | native + hover bonus | native + ΔΦ − 0.05 |
| EvalCallback (best.zip) | **native** | **native** | **native** |
| Dev-val seeds | 10000+ | 10000+ | 10000+ |
| Held-out test | **50000–50049** (50 eps), native only | same | same |

Experiment A was **not retrained**; frozen checkpoints from Phase 2.

**B thresholds (pre-registered):** upright `|angle| < 0.2` rad; slow `√(vx²+vy²) < 0.5`.

**C potential:** `Φ = −100√(x²+y²) − 100√(vx²+vy²) − 100|θ| + 10(ℓL+ℓR)`; time cost `0.05`.

---

## A/B/C comparison table (primary: `best` checkpoints, native scoring)

| Metric | A native | B hover+ | C progress |
|--------|---------:|---------:|-----------:|
| Mean native reward | **232.3** | 132.2 | **222.5** |
| Median | 243.5 | 177.8 | 242.7 |
| Std | 44.8 | 96.4 | 74.0 |
| 95% CI (mean) | ±12.4 | ±26.7 | ±20.5 |
| Episodes ≥200 | **44/50 (88%)** | 10/50 (20%) | **44/50 (88%)** |
| Mean episode length | 382 | **639** | 333 |
| Median length | 317 | **615** | 303 |
| Timeouts (1000 steps) | 3 | 2 | 1 |
| Episodes ≥800 steps | 4 | **15** | 1 |
| Mean “upright+slow” frame fraction* | 0.92 | 0.94 | 0.89 |
| Mean main-engine steps | 150 | **~** (B final 289) | ~147 |

\*This diagnostic fires during normal soft approaches too; **length / long-episode counts** are the clearer hover/delay signal.

### Final checkpoints (same held-out set)

| | A final | B final | C final |
|--|--------:|--------:|--------:|
| Mean native | 244.9 | 136.1 | 220.1 |
| ≥200 rate | 48/50 | 17/50 | 42/50 |
| Mean steps | 344 | 550 | 380 |

Fuel is infinite in LunarLander-v3; engine firings are reported instead.

Landing/crash labels use heuristics (`land_heuristic` / `crash_likely` / `timeout`); **≥200 is not treated as proof of a specific native landing animation**, only as Gymnasium’s “solved” score band.

---

## Did reward hacking happen?

**Yes, in a practical sense for B — without fabricating a “never lands” cartoon.**

Evidence (held-out, native scoring):

1. **Training signal inflated:** B’s shaped `ep_rew_mean` reached ~**714** with mean length ~**615**, while native EvalCallback best was only ~**184**.
2. **Native performance collapsed:** mean **132** vs A’s **232**; solved rate **20%** vs **88%**.
3. **Delayed touchdown:** mean length **639** vs **382**; **15/50** episodes ≥800 steps vs **4/50**.
4. **Authentic long/timeout clips:** seed `50019` ran **1000** steps with hover-fraction ≈1.0 and native reward **40.5** (video below).

B still often reaches the pad eventually (`land_heuristic` counts remain high) — the failure mode is **delay / inefficient soft approach**, not pure eternal floating every episode. That matches the guide’s mechanism (bonus stops when the episode ends) without overselling.

**C did not clearly beat A** on this single seed: mean 222.5 vs 232.3, same 88% solved rate, slightly shorter episodes. The correction **avoided B’s failure mode** and matched A’s competence; it did not show a large upside over the already-strong native baseline in this run.

---

## Why the original reward works

Gymnasium’s built-in reward already pays for **improvement** in a potential (closer, slower, flatter, legs down) and taxes thrust. Landing (+100) / crash (−100) dominate the end. That aligns credit with “get to the pad and stop,” so PPO learns to finish.

## What B changes

Adding **+1 every frame** while upright and slow pays for **remaining** in a pleasant state. Truncation at 1000 frames can bank up to +1000 from the bonus; finishing early stops the meter. The agent therefore has an incentive to **linger**.

## What C changes

Paying `ΔΦ − 0.05` restores “get better each frame” + a small clock cost, so hovering is not a free ATM. Native terminal conditions stay untouched.

---

## Charts

| Chart | Path |
|-------|------|
| Native mean ± CI | `outputs/phase4/charts/native_mean_reward.png` |
| ≥200 solved rate | `outputs/phase4/charts/solved_rate.png` |
| Episode duration | `outputs/phase4/charts/episode_duration.png` |
| Timeouts / long eps | `outputs/phase4/charts/timeouts_long.png` |
| Native EvalCallback curves | `outputs/phase4/charts/native_eval_curves.png` |
| Per-episode scatter | `outputs/phase4/charts/reward_scatter.png` |
| Training returns (shaped for B/C) | `outputs/ppo_*/learning_curve.png` |

## Videos (Gymnasium `rgb_array` + `RecordVideo`)

| Role | Path |
|------|------|
| A success | `videos/phase4_A_success/phase4_A_success_ep0-episode-0.mp4` (R≈287) |
| B delayed / timeout hover | `videos/phase4_B_seed50019/B_hover_seed50019-episode-0.mp4` (1000 steps, R≈40) |
| B typical longer approach | `videos/phase4_B_seed50018/B_hover_seed50018-episode-0.mp4` (R≈194) |
| C success | `videos/phase4_C_success/C_seed50009-episode-0.mp4` (R≈292) |

---

## Limitations

- **Single training seed (0)** per condition — do not over-generalize.
- Hover-fraction alone is a weak discriminator; length metrics matter more.
- Built-in LunarLander reward already includes shaping; C doubles some potential-like terms (additive on top of native), which may explain “C ≈ A” rather than “C ≫ A.”
- Outcome classes are heuristics; trust native scores and lengths most.
- No multi-seed statistical test across independent trainings.

---

## Recommended GitHub / LinkedIn presentation

**Title:** *Reward shaping can teach a rocket to hover: LunarLander PPO A/B/C*

**One-liner:** Same PPO, same game — change only the points, and the policy’s native score drops from ~232 to ~132 while episodes get ~70% longer.

**Storyboard:** random crash → A lands (88% ≥200) → B farms upright-and-slow time (long episodes, weak native score) → C restores progress+time-cost and matches A.

**Assets to pin:** `native_mean_reward.png`, `episode_duration.png`, A success mp4, B timeout mp4, this report.

**Honesty line:** “On one seed, the bad bonus caused delayed landings and worse native scores; the corrected reward avoided that failure but did not beat the strong built-in baseline.”
