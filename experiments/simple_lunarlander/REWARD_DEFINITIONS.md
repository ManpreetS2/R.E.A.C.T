# Phase 4 — reward definitions (fixed before training)

Physics, Discrete(4) actions, 8-dim observations, and Gymnasium termination
(crash / rest / out-of-bounds / 1000-step truncate) are **unchanged** in all runs.

Let \(r_t^{\text{native}}\) be the built-in LunarLander-v3 step reward.

## Experiment A — Original (baseline, already trained)

\[
R_t = r_t^{\text{native}}
\]

No wrapper. Run name: `ppo_baseline`. Seed `0`, 1e6 steps, 4 envs.

## Experiment B — Problematic hover bonus

**Thresholds (documented before training):**

| Symbol | Meaning | Value |
|--------|---------|-------|
| \(\theta_{\max}\) | upright if \(\lvert \text{angle}\rvert < \theta_{\max}\) | `0.2` rad |
| \(v_{\max}\) | slow if \(\sqrt{v_x^2 + v_y^2} < v_{\max}\) | `0.5` |

\[
b_t = \begin{cases}
1 & \text{if } \lvert\text{angle}_t\rvert < 0.2 \text{ and } \sqrt{v_x^2+v_y^2} < 0.5 \\
0 & \text{otherwise}
\end{cases}
\qquad
R_t = r_t^{\text{native}} + b_t
\]

An episode truncated at 1000 frames can collect up to **+1000** from \(b_t\) while landing
ends the bonus stream — the tutorial’s hovering incentive.

## Experiment C — Corrected progress + time cost

Potential (same structure as the guide’s “how good is this position” idea):

\[
\Phi(s) = -100\sqrt{x^2+y^2} - 100\sqrt{v_x^2+v_y^2} - 100\lvert\theta\rvert + 10\,(\ell_L+\ell_R)
\]

\[
R_t = r_t^{\text{native}} + \big(\Phi(s_t) - \Phi(s_{t-1})\big) - 0.05
\]

Time cost \(c = 0.05\) per frame. Reward the **change** in potential, not a static “looks good” payment.

## Checkpoint & eval protocol

| Role | Seeds | Reward |
|------|-------|--------|
| Training | seed `0` (+ env ranks) | A native / B shaped / C shaped |
| Dev-val (EvalCallback / best.zip) | `10000+` (same as baseline) | **Native only** (wrappers off) |
| Held-out test | `50000 .. 50049` (50 eps) | **Native only** |

Primary reported models: each run’s `best/best_model.zip` under native EvalCallback, plus `ppo_lunar_final.zip`.
