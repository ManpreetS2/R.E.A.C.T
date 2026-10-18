# ApolloLander RL pilot report

**Verdict:** A genuine CPU-only PPO pilot was run from randomly initialized weights on the documented ApolloLander research-mode task. **The policy did not learn to land within the CPU budget.** Frozen final policy held-out **landing success rate = 0.000** (0/32; Wald 95% CI **[0.000, 0.000]**), crash rate **1.000**, timeout rate **0.000**. Curves were not edited; the reference/guidance controller was never substituted into training.

**Disclosure (mandatory):** The policy uses **numerical state observations** and the **unchanged repo reward**, which includes **shaped terms** (progress/potential shaping + fuel penalty). This is **NOT** screenshot / pixel / visual learning.

**Simulator label (mandatory):** All physics here are the **custom Node ApolloLander simulator** (`frontend/apollolander/experiment/physics.js`) via `ApolloLanderAdapter` / `session.js`. Do **not** call this the original browser game’s exact physics. The Python-port equivalence test proves **port vs Node** parity only — **not** parity with the original upstream browser game. There is no Playwright bridge to the live upstream game in this repo.

## Setup

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-pilot-2f7b` |
| Algorithm | PyTorch PPO, device=`cpu` only |
| Weight init | Orthogonal random init at step 0 (`step0.pt`); real weights saved |
| Imitation / demos | **None** in training. `demonstration_guidance_controller()` is REFERENCE ONLY in eval |
| Train physics | Python port of the **custom Node** simulator (`physics.js`) |
| Eval / footage | **Custom Node** `ApolloLanderAdapter` (same `physics.js`) |
| Optional deps | `pip install -e '.[rl,environments,analysis,dev]'` (`torch` not core) |

### Frozen environment config

- `max_steps=8000`, `research_mode=true`, `start_schedule_version=apollolander.starts.v1`, `vary_fuel=false`, `bonuses=false`
- `action_repeat=2` (each policy action = 2 unmodified custom-Node physics steps)
- `env_config_hash`: `33f72bf37844c9d11c07b18f99371024f1cb547a75e48ea311a2618180ce9fc1`

### Reserved seeds (sealed)

Seeds **2000000 through 2000015 inclusive** are never trained on, evaluated on, rendered, reset with, or inspected. Code guard: `rewardbench.rl.reserved_seeds` (raises `ReservedSeedError`). Held-out eval uses `1000000…1000031` only. Test: `tests/rl/test_reserved_seeds.py`.

## Observation / action / reward

### Observation — numerical state (NOT screenshots)

`x, y, vx, vy, rotation, fuel, altitude, dx, dy, thrust_build` (scaled). Explicitly: **state-observation RL pilot, not visual learning**.

### Action

`Discrete(95)` = 5 thrust bins × 19 rotations (−90…90 / 10°). Action repeat = 2 underlying physics steps.

### Reward — unchanged repo table (includes shaping)

| Event | Value |
| --- | --- |
| Perfect designated landing | +100 |
| Hard designated landing | +40 |
| Safe landing outside pad | 0 (`landed` false) |
| Crash | −100 |
| Timeout | −25 |
| Fuel | −0.05 per fuel unit burned that step |
| Progress (shaped) | 0.5 × Δ potential |

**Shaped rewards disclosure:** training signal includes the progress/potential term and fuel penalty, not only sparse terminal landing/crash/timeout.

## Throughput and actual env steps achieved

The **1–5M target is aspirational, not required.** Actual measured values:

| Metric | Value |
| --- | --- |
| Pre-train Python port (single) | **~16.7k** env steps/s |
| Pre-train Python port (vectorized) | **~15.1k** env steps/s |
| Pre-train Node JSON IPC (single) | **~24.7k** env steps/s |
| **Actual total env steps (primary)** | **5,005,312** |
| Combined wall (phase1 + continued) | **~386.5 s** |
| Combined effective steps/s | **~12.9k** |
| Continued-phase wall / steps/s | ~154.4 s / ~12.9k |

Sources: `examples/apollolander/rl_pilot/results/throughput.json`, `…/ppo_pilot_v1/logs/train_summary.json`.

## PPO optimization step counts (logged)

| Counter | Value |
| --- | --- |
| PPO updates | **611** |
| Update epochs per update | 4 |
| Minibatch size | 1024 |
| Rollout batch (`rollout_steps × n_envs`) | 256 × 16 = 4096 |
| Minibatch gradient steps / update | 16 |
| Estimated total minibatch grad steps | **9776** (prior 367×16 estimated + continued 3904 logged) |
| Continued-phase logged grad steps | **3904** |

Raw per-update JSON: `results/ppo_pilot_v1/logs/update_stats.json` (includes `minibatch_grad_steps` from the continued phase onward). Real model weights: `checkpoints/*.pt` (`real_weights: true`).

## Runs performed (all reported; none cherry-picked)

| Run | Env steps | Wall | Train landings | Mean return |
| --- | --- | --- | --- | --- |
| `ppo_pilot_v1` phase 1 | 3,006,464 | 232.2 s | 0 / 934 | −100.38 |
| `ppo_pilot_v1` continued | → **5,005,312** | +154.4 s | 0 / 1345 total | −100.93 |
| `ppo_pilot_v2_ar1` (sweep) | 2,007,040 | 193.4 s | 0 / 373 | −83.98 |
| `ppo_pilot_v3_lowent` (sweep) | 1,507,328 | 122.3 s | 0 / 708 | −103.50 |

Preserved: random-policy baseline logs, `step0.pt` random init, periodic checkpoints (`step1000000`, `step2000000`, `step3500000`…`step5000000`, `final.pt`).

## Learning curves

Raw CSV (failures not omitted): `results/ppo_pilot_v1/logs/learning_curve.csv`.

Plots: `v1_curves.png`, `v1_fuel.png` (also under `/opt/cursor/artifacts/`).

## Frozen-policy evaluation (custom Node simulator)

Eval mode: **frozen deterministic argmax** — no further weight updates. Seeds fixed before outcomes; reserved range excluded.

### Held-out (≥1_000_000, n=32) — success rate with CI

| Policy | Landing success (CI95) | Crash | Timeout | Mean return |
| --- | --- | --- | --- | --- |
| Random open-loop baseline | 0.000 **[0.000, 0.000]** | 0.000 | 1.000 | −95.34 |
| Untrained MLP (random init) | 0.000 **[0.000, 0.000]** | 1.000 | 0.000 | −99.92 |
| PPO `step0` (frozen) | 0.000 **[0.000, 0.000]** | 1.000 | 0.000 | −99.92 |
| PPO `final` (frozen) | **0.000 [0.000, 0.000]** | **1.000** | **0.000** | −106.23 |
| Hand-tuned guidance (**REFERENCE ONLY**) | 1.000 **[1.000, 1.000]** | 0.000 | 0.000 | +82.97 |

### Development (n=32, not used as training seed pool)

| Policy | Land (CI95) | Crash | Timeout | Mean R |
| --- | --- | --- | --- | --- |
| Random open-loop | 0.000 [0,0] | 0.000 | 1.000 | −95.39 |
| PPO `final` (frozen) | 0.000 [0,0] | 1.000 | 0.000 | −106.23 |
| Hand-tuned guidance (REFERENCE ONLY) | 1.000 [1,1] | 0.000 | 0.000 | +82.99 |

## Footage

Custom Node path; flight records replay-matched. Footage seeds = first three held-out seeds `1000000…1000002` (chosen before outcomes; not reserved).

`/opt/cursor/artifacts/`: `apollolander_rl_{step0,final}_heldout_seed{1000000,1000001,1000002}.mp4` (+ earlier intermediate renders), manifests, curve PNGs, throughput/train_summary/eval JSON.

Committed flight JSONs: `results/ppo_pilot_v1/footage/*.flight.json`.

## Equivalence scope

`tests/rl/test_physics_equivalence.py`: Python port ↔ **custom Node session** within 1e-9. **Does not** prove parity with the original upstream browser game.

## Honest limitations

1. PPO failed to land within the achieved CPU budget (~5.0M env steps, ~6.4 minutes combined wall).
2. Never blended/substituted the guidance controller into training or curves.
3. Shaped reward + discrete 95-way actions make sparse exact landings hard from scratch.
4. Adapter manifests still set `autonomous_learning=false` by environment policy; this report labels the PPO runs as genuine RL from random weights.

## Proposed next step (visual)

Keep the same custom-Node reward/verifier; add downscaled pixel stacks; CNN+PPO. Cost: CPU overnight–days ($0); single consumer GPU ~2–12 h (~$1–5 spot). Prefer proving a state policy can land before pixels.

## Reproduce

See `examples/apollolander/rl_pilot/README.md`.
