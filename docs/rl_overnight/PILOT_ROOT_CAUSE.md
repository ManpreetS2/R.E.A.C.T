# Pilot root-cause analysis (ppo_pilot_v1, 5.005M env steps)

Sources: `examples/apollolander/rl_pilot/results/ppo_pilot_v1/`,
`docs/RL_PILOT_REPORT.md`, `src/rewardbench/rl/{ppo,env,physics_python}.py`,
`config.yaml` vs `train_summary.json` / `throughput.json`.

## Proven defects (confirmed from code + logs)

### 1. Inflated continued-phase throughput (32,425 vs 12,949 steps/s)

**Proven.** `train_summary.json` records:

- `total_env_steps`: 5,005,312
- `continued_phase_wall_seconds`: ~154.37
- `steps_per_sec_effective`: **32,425** = `5005312 / 154.37` (total steps ÷ continued wall only)
- `combined_steps_per_sec`: **12,949** = total steps ÷ combined wall (~386.5 s)

The 32k figure is an arithmetic bug in how the continued phase reported
“effective” throughput. The honest aggregate is ~12.9k env-steps/s.

### 2. Action-repeat disagreement (2 vs 4)

**Proven.** Frozen training config and `run_metadata.json` set
`action_repeat: 2`. Pre-train throughput block used `"action_repeat": 4` for the
vectorized Python benchmark. So:

- Training / global_step accounting used **repeat=2**
- The vectorized throughput number is **not** comparable to the training config

`5,005,312` counts **physics frames** (each policy decision × action_repeat),
because `collect_rollout` does `global_step += action_repeat * n_envs`.
With repeat=2, that is ~2.50M policy decisions.

### 3. Timeout truncation is not bootstrapped in GAE

**Proven.** `env.py` correctly marks timeouts as `truncated=True`,
`terminated=False`. `ppo.collect_rollout` then collapses both into
`dones = terminated | truncated` and GAE uses
`next_non_terminal = 1 - dones[t]` for every done, including timeouts.

So timeout episodes get **hard zeros** instead of value bootstrap. That biases
value targets for long hover/timeout trajectories and interacts with the
shaped reward (below).

### 4. Reward encourages hovering / delaying crash

**Proven from reward definition + episode mix.** Repo reward includes:

- progress/potential shaping `0.5 * Δpotential`
- fuel penalty `-0.05` per fuel unit
- timeout `-25` vs crash `-100`

Timeout is **much less punitive** than crash. Early windows show ~32% timeouts
with returns ≈ −55…−60 (better than crash ≈ −105). Later windows oscillate
between crash-heavy (~100% crash, R≈−105…−112) and timeout-heavy (~64–82%
timeout, R≈−70…−79). That is exactly the pattern expected if the policy learns
to avoid the crash penalty by staying aloft until `max_steps`.

### 5. Dev eval seeds 0–31 do **not** overlap the training pool

**Proven.** Training pool is `train_seed_start=10000`, `train_seed_count=200000`
→ seeds `[10000, 210000)`. Dev eval uses `[0..31]`. Held-out uses
`[1000000..1000031]`. No overlap with train. (They are fine as a development
set; they were simply never a train-set leak.)

### 6. Action scaling / rotation bins are valid player controls

**Proven.** Discrete(95) = 5 thrust bins × 19 rotations (−90…90 / 10°) maps to
`lander.thrust` / `setRotation` capabilities (touch path allows continuous
thrust; keyboard is binary). No out-of-range actions. Observation normalization
uses fixed scales (`OBS_SCALE`); scales are coarse but finite and consistent.

## Supported by logs but not a single-line code bug

### Oscillation between crashes and timeouts

Learning-curve windows alternate crash-dominated and timeout-dominated regimes
while **landing_success stays 0/1345**. Entropy remains high (~4.1–4.55;
`ln(95)≈4.55`), so this is **not** entropy collapse to a single action. It is
mode-switching under a reward that ranks timeout ≫ crash and never rewards a
true landing often enough to reinforce it.

### Missing KL / clipfrac / grad-norm in early phase

Update stats for the first ~367 updates lack `approx_kl`, `clipfrac`,
`grad_norm`, `value_loss`. Continued phase still only logs loss/entropy. We
**cannot** prove PPO clipping instability from logged fields; we can only say
diagnostics were incomplete.

### Entropy did not collapse

Entropy stayed near the uniform-prior ceiling. Instability here is behavioral
(crash↔timeout), not silent deterministic collapse.

## Hypotheses (not proven)

1. **Potential shaping** may reinforce “point toward pad while high” without
   teaching the final upright/slow contact — plausible, not isolated by an
   ablation in the pilot itself.
2. **Value function** may be poorly calibrated on 8000-step timeouts because of
   the truncation bootstrap bug — consistent with the code defect, but we did
   not re-train the pilot with a fix to A/B it.
3. **Action repeat = 2** may be too reactive or too coarse; the v2_ar1 sweep
   (repeat=1) also failed to land, so repeat alone is not a sufficient cause.
4. **Discrete 95-way** exploration makes exact pad contact rare under random
   init within 5M frames — consistent with zero landings, not uniquely proven
   vs reward design.

## Fixes applied for overnight runs (confirmed bugs only)

1. Report throughput as combined wall / physics frames (no continued-only
   inflation).
2. Log `action_repeat`, physics frames, and policy decisions separately.
3. GAE: bootstrap on **truncation** (timeout), hard-stop on **termination**
   (crash/land).
4. Log entropy, approx KL, clipfrac, grad norm, value loss every update.
5. Keep action mapping / obs scales unless an ablation explicitly changes them.
6. Treat hovering hypothesis via **Family C** reward ablations (documented),
   judged by native landings — not by shaped return alone.

## What the pilot did **not** show

- Any verified landing on train, dev, or held-out seeds.
- Upstream-game parity (pilot used custom `physics.js` / Python port only).
- That 5M frames is a hard impossibility bound — only that this config failed.
