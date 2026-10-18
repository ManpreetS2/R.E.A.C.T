# ApolloLander RL pilot report

**Verdict:** A genuine CPU-only PPO pilot was run from randomly initialized weights on the documented ApolloLander research-mode task. **The policy did not learn to land within budget.** Held-out landing rate for the final checkpoint is **0%** (32/32 crashes). The hand-tuned guidance controller (reference only) lands **100%** on the same seeds, so the task is solvable; this PPO setup did not solve it.

Observation mode (explicit): **state-observation RL pilot, not visual learning**.

There is **no Playwright bridge** to the live original browser game in this repo. Training and evaluation use the experiment physics / adapter, not the upstream play page.

## Setup

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-pilot-2f7b` |
| Algorithm | PyTorch PPO, device=`cpu` only |
| Weight init | Orthogonal random init at step 0 (checkpoint `step0.pt`); no pretrained weights |
| Imitation / demos | **None.** `demonstration_guidance_controller()` used only as a separately labeled eval baseline |
| Train physics | Verified Python port of `frontend/apollolander/experiment/physics.js` |
| Eval / footage physics | **Original Node** `ApolloLanderAdapter` / `session.js` |
| Optional deps | `pip install -e '.[rl,environments,analysis,dev]'` (`torch` is **not** a core dependency) |

### Frozen environment config (unchanged during training)

From `examples/apollolander/rl_pilot/config.yaml` (primary run `ppo_pilot_v1`):

- `max_steps=8000`, `research_mode=true`, `start_schedule_version=apollolander.starts.v1`, `vary_fuel=false`, `bonuses=false`
- `action_repeat=2` (each policy action applied for 2 **unmodified** physics steps)
- Config hash (SHA-256 of frozen env dict): recorded in `runs/ppo_pilot_v1/run_metadata.json` as `env_config_hash`

Primary run hash: `33f72bf37844c9d11c07b18f99371024f1cb547a75e48ea311a2618180ce9fc1`

## Observation / action / reward

### Observation (state vector, not pixels)

Labels: `x, y, vx, vy, rotation, fuel, altitude, dx, dy, thrust_build`, then divided by fixed scales. Clearly **not** visual / pixel learning.

### Action

Flat `Discrete(95)` = 5 thrust bins `{0, 0.25, 0.5, 0.75, 1}` × 19 rotations `{-90…90}` step 10°. Documented action repeat: 2 underlying physics steps per policy action (primary run).

### Reward (unmodified repo reward)

| Event | Value |
| --- | --- |
| Perfect designated landing | +100 |
| Hard designated landing | +40 |
| Safe landing outside pad | 0 (`landed` false) |
| Crash | −100 |
| Timeout | −25 |
| Fuel | −0.05 per fuel unit burned |
| Progress | 0.5 × Δ potential |

## Hyperparameters (primary `ppo_pilot_v1`)

`n_envs=16`, `rollout_steps=256`, `lr=3e-4`, `γ=0.99`, `λ_GAE=0.95`, `clip=0.2`, `ent_coef=0.02`, `vf_coef=0.5`, `epochs=4`, `minibatch=1024`, `hidden=128`, `seed=0`, train seeds `10000…209999` (development pool only).

## Throughput (before training)

From `examples/apollolander/rl_pilot/results/throughput.json`:

| Backend | Steps/sec |
| --- | --- |
| Python port (single) | ~16.7k |
| Python port (16 envs, action_repeat=4 measurement) | ~15.1k |
| Node JSON IPC (single persistent session) | ~24.7k |

## Runs performed (all reported)

| Run | Physics steps | Wall time | Effective steps/s | Train landings | Mean episodic return |
| --- | --- | --- | --- | --- | --- |
| `ppo_pilot_v1` (primary) | 3,006,464 | 232.2 s | ~12.9k | **0 / 934** | −100.38 |
| `ppo_pilot_v2_ar1` (sweep: AR=1, hidden=256, lr=5e-4, ent=0.05) | 2,007,040 | 193.4 s | ~10.4k | **0 / 373** | −83.98 |
| `ppo_pilot_v3_lowent` (sweep: low entropy, more epochs) | 1,507,328 | 122.3 s | ~12.3k | **0 / 708** | −103.50 |

No run produced a verified designated landing during training. Env physics / reward / starts were **not** retuned to make landing easier.

## Learning curves

Raw CSV: `examples/apollolander/rl_pilot/results/ppo_pilot_v1/logs/learning_curve.csv` (and sweep siblings).

Plots (also copied under `/opt/cursor/artifacts/`):

- `v1_curves.png`, `v1_fuel.png`
- `v2_curves.png`, `v2_fuel.png`

Curves show crash-dominated episodes; rolling means are overlays only — raw points are plotted and failures are not omitted.

## Evaluation (original Node adapter)

Seeds fixed in config **before** looking at outcomes:

- Development eval: `0…31` (disjoint from train pool `≥10000`)
- Held-out: `1000000…1000031`
- Footage held-out: first 3 held-out seeds `1000000…1000002` (chosen before outcomes)

Sample size **n=32** per cell. Wald 95% CIs in `evaluation_results.json`.

### Baseline vs final (development)

| Policy | Land | Crash | Timeout | Mean return |
| --- | --- | --- | --- | --- |
| Random open-loop (`random_controller`) | 0.000 | 0.000 | 1.000 | −95.39 |
| Untrained MLP (random init) | 0.000 | 1.000 | 0.000 | −100.24 |
| PPO `step0` | 0.000 | 1.000 | 0.000 | −100.24 |
| PPO `final` (`ppo_pilot_v1`) | 0.000 | 1.000 | 0.000 | −106.18 |
| Hand-tuned guidance (**REFERENCE ONLY**) | **1.000** | 0.000 | 0.000 | **+82.99** |

### Baseline vs final (held-out ≥ 1_000_000)

| Policy | Land | Crash | Timeout | Mean return |
| --- | --- | --- | --- | --- |
| Random open-loop | 0.000 | 0.000 | 1.000 | −95.34 |
| Untrained MLP | 0.000 | 1.000 | 0.000 | −99.92 |
| PPO `step0` | 0.000 | 1.000 | 0.000 | −99.92 |
| PPO `final` (`ppo_pilot_v1`) | 0.000 | 1.000 | 0.000 | −105.80 |
| Hand-tuned guidance (**REFERENCE ONLY**) | **1.000** | 0.000 | 0.000 | **+82.97** |

`ppo_pilot_v2_ar1` final (Node eval): held-out land=0.000, crash=1.000, mean_r≈−102.4 — still no landings.

## Footage

Rendered via `record_video=True` / flight records on the **Node** path; each flight record replay-matched (`verify_flight_record` → `matched=true`). Seeds were the pre-chosen first three held-out seeds (no cherry-picking).

Artifacts under `/opt/cursor/artifacts/`:

- `apollolander_rl_step0_heldout_seed{1000000,1000001,1000002}.mp4`
- `apollolander_rl_step1500000_heldout_seed{1000000,1000001,1000002}.mp4`
- `apollolander_rl_final_heldout_seed{1000000,1000001,1000002}.mp4`
- `apollolander_rl_footage_manifest.json`
- Learning-curve PNGs and `apollolander_rl_throughput.json`, `apollolander_rl_evaluation_v1.json`

## Equivalence (Python port)

`tests/rl/test_physics_equivalence.py` replays random-action trajectories on many development seeds against the live Node session. Per-step state and reward match within `1e-9`; terminal outcomes identical. **If this test fails, training must fall back to Node.** Final evaluation and footage always use Node regardless.

## Honest limitations

1. **No landings learned.** Sparse terminal success (+40/+100) vs easy crash (−100); upright landing requires `rotation == 0` exactly and `vy < 0.15` on the designated segment.
2. Discrete 95-way actions + short budget (~3M steps, ~4 minutes wall) are likely insufficient for this precision task from scratch.
3. Deterministic eval (argmax) crashed on every seed; stochastic training still recorded zero successful landings.
4. Adapter flight manifests still set `autonomous_learning=false` by environment policy; this report labels the PPO runs as genuine RL from random weights.
5. Not trained on pixel observations; not the live upstream browser game.

## Proposed next step: visual (pixel) learning

1. Keep the same reward, starts, and Node verifier.
2. Add a stacked grayscale or RGB observation from the existing 1920×1080 recorder (downscale to e.g. 84×84 or 128×128).
3. Replace the MLP with a small CNN encoder + PPO (or DQN) on GPU.

**Rough cost estimate (order-of-magnitude):**

| Path | Compute | Wall time for ~10–50M frames | $ |
| --- | --- | --- | --- |
| CPU only (this machine class) | CNN forward is ~10–50× slower than state MLP | Many hours to days | ~$0 on free/CPU |
| Single consumer GPU (e.g. 8–12 GB) | Typical Atari-scale PPO | ~2–12 hours | ~$1–5 spot / free Colab-class |
| Larger pixel stack + domain randomization | Multi-GPU | Overnight+ | tens of $ |

Recommended: prove a **state** policy can land first (longer CPU PPO, factored MultiDiscrete heads, or SAC on continuous thrust), then freeze the reward and move to pixels without changing the verifier.

## How to reproduce

See `examples/apollolander/rl_pilot/README.md`.
