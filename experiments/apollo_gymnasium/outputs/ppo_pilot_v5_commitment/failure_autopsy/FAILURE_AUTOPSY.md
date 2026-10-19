# V5 failure autopsy (offline; no training)

**γ (PPO)** = 0.99

## Crash vs reascent return preference

MIXED — UNDISCOUNTED V5 returns: early crash ≫ reascent timeout (commitment ≈ −261 on V3-style ascents makes long aborts very costly). PPO-DISCOUNTED (γ=0.99): distant timeout/commit is diluted, so mid-reascent discounted return can EXCEED crash (−12.9 > −78.3). Late crash collapse is therefore not fully explained by γ-return preferring crash; the 11-D obs change and optimization dynamics remain confounded with the penalty. Land still best (+103).

| Group | n | Mean undiscounted V5 | Mean discounted V5 | Mean Σ commit | Mean A′ (same acts) |
|-------|--:|---------------------:|-------------------:|--------------:|--------------------:|
| V5 final crashes | 4 | -97.6 | -78.3 | 0.0 | -97.6 |
| V5 mid reascent | 4 | -218.1 | -12.9 | -17.1 | -197.6 |
| V3-40k reascent acts @ V5 R | 4 | -400.9 | -11.9 | -261.0 | -144.9 |
| Reference lands | 3 | 103.1 | 69.9 | 0.0 | 103.1 |

## Reward penalty vs 11th observation

Action-conditional replay under commitment ON vs OFF isolates the **penalty** (obs unused at replay time).

| Trajectory class | Mean (V5 − A′) undiscounted |
|------------------|----------------------------:|
| Crash | 0.0 |
| V5 mid reascent | -20.5 |
| V3-style reascent | -256.0 |
| Reference land | 0.0 |

- V5 policies are 11-D (cannot load in 10-D); V3-40k is 10-D (cannot load in 11-D).
- Selected model SHA equals step0: **True**
- Lands/crashes accumulate **~0** commitment; V3-style reascent accumulates **≈ −261**.

## Implications for V5 learning failure

1. Commitment successfully taxes long soft ascents (reward-only).
2. Under γ=0.99, that tax is mostly in the far future → weak PPO target vs immediate crash −100.
3. Changing obs dimensionality confounds attribution: we cannot say the penalty alone caused the crash collapse.
4. A/B/C/D must keep **identical observations** and avoid stateful hidden rewards.

Full JSON: `experiments/apollo_gymnasium/outputs/ppo_pilot_v5_commitment/failure_autopsy/failure_autopsy.json`
