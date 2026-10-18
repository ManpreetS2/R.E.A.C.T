# ApolloLander R.E.A.C.T. V7 — Demonstration-Assisted Imitation + Optional PPO

**Label:** `demonstration-assisted` (expert demos for TRAINING ONLY; never at evaluation).

This is NOT a reward-only / from-scratch discovery claim.

## Preregistration

- Seeds file: `examples/apollolander/rl_v7/preregistered/seeds.json`
- SHA256: `5a9f330be4d55473bbe77f5d3fa739f7a92e7225d31add5725decfe5d3ea6134`
- Committed before demo generation.

## Phase 0 — Translation feasibility

- Learner space: continuous thrust, delta {-10,0,+10}, action_repeat=8
- max_steps_v1=8000 (expert needs ~6k frames)
- V1 translated expert landings: 12/12 (rate=1.000, Wilson95=[0.7574992425007574, 1.0])
- Raw expert landings (fidelity subset): 4/4
- Fidelity (mean over n=4): thrust MAE=0.004582998635431882, rotation MAE deg=0.18561086432000581, rotation exact agreement=0.9841556438272661
- Replay bit-exact: 12/12
- Pass ≥80%: True
- L0-near probe landings: 10/10
- Demo/feas/replay frames spent after Phase 0: 163272
- Fallback representation used: False

## Phase 1 — Demonstrations

- Attempts: 37
- Failures: 2
- Kept (native landings, replay-verified): 35 (train=35, val=0)
- Include L0-near demos: True
- Demo seed list sha256: `9ae7aa086d4a7bbbec163a1405d934aa7a3581147d19a3d26cf43fef55b0c164`
- Demo budget spent: 299757 / 300000

## Phase 2 — Behavioral cloning

- Train pairs: 7364 (from 28 trajectories)
- Val pairs: 824 (from 7 trajectories)
- Epochs: 40, wall seconds: 1.8509600162506104
- Final val loss: -0.2243597162887454
- Final val rotation accuracy: 0.9873046875
- Final val thrust MSE: 0.0023521997063653544
- step0 sha256: `adfacc9bad94960380b4562211de203811ae880717e90d0ba9ba4a3df0e495e8`
- bc sha256: `92b495648420db31babff2e1ddf858470f6b9bcd9028a35b3a30173dc60a019e`
- Integrity (no controller at eval): True
- Environment frames for BC: 0

## Phase 3 — Independent gameplay (expert DISABLED)

- L0-near eval n=40: untrained={'perfect': 0, 'hard': 0, 'crash': 40, 'timeout': 0} BC={'perfect': 40, 'hard': 0, 'crash': 0, 'timeout': 0}
- V1 eval n=23: untrained={'perfect': 0, 'hard': 0, 'crash': 40, 'timeout': 0} BC={'perfect': 0, 'hard': 0, 'crash': 23, 'timeout': 0}
- Untrained landings total: 0 (l0=0, v1=0)
- BC landings total: 40 (l0=40, v1=0; perfect=40, hard=0 across listed per-seed rows)
- McNemar BC vs untrained (L0-near primary): {'shared_seeds': [703000, 703001, 703002, 703003, 703004, 703005, 703006, 703007, 703008, 703009, 703010, 703011, 703012, 703013, 703014, 703015, 703016, 703017, 703018, 703019, 703020, 703021, 703022, 703023, 703024, 703025, 703026, 703027, 703028, 703029, 703030, 703031, 703032, 703033, 703034, 703035, 703036, 703037, 703038, 703039], 'mcnemar': {'b': 40, 'c': 0, 'n_discordant': 40, 'p_value': 1.8189894035458565e-12, 'method': 'exact_binomial_mcnemar'}}
- McNemar BC vs untrained (v1): {'shared_seeds': [702000, 702001, 702002, 702003, 702004, 702005, 702006, 702007, 702008, 702009, 702010, 702011, 702012, 702013, 702014, 702015, 702016, 702017, 702018, 702019, 702020, 702021, 702022], 'mcnemar': {'b': 0, 'c': 0, 'n_discordant': 0, 'p_value': 1.0, 'method': 'exact_none'}}
- Expert reference L0 (NOT a learner): {'perfect': 16, 'hard': 0, 'crash': 0, 'timeout': 0}
- Expert reference V1 (NOT a learner): {'perfect': 0, 'hard': 0, 'crash': 0, 'timeout': 0}
- Diagnostic frames spent: 179744
- Landings preserved (videos/traces): 40

## Phase 4 — PPO fine-tune from BC

- PPO frames: 249856 / 250000
- PPO sha256: `03df86ad681b7b56cbdcefc0942de87961bedc61983b19a34d42b7f54dea4a20`
- BC re-eval counts: {'perfect': 40, 'hard': 0, 'crash': 0, 'timeout': 0}
- PPO eval counts: {'perfect': 39, 'hard': 1, 'crash': 0, 'timeout': 0}
- McNemar PPO vs BC: {'shared_seeds': [703000, 703001, 703002, 703003, 703004, 703005, 703006, 703007, 703008, 703009, 703010, 703011, 703012, 703013, 703014, 703015, 703016, 703017, 703018, 703019, 703020, 703021, 703022, 703023, 703024, 703025, 703026, 703027, 703028, 703029, 703030, 703031, 703032, 703033, 703034, 703035, 703036, 703037, 703038, 703039], 'mcnemar': {'b': 0, 'c': 0, 'n_discordant': 0, 'p_value': 1.0, 'method': 'exact_none'}}
- Verdict: PPO_PRESERVED_BC
- Note: PPO started from BC checkpoint; not discovery from scratch.

## Budgets (exact frames)

| Bucket | Cap | Spent |
|---|---:|---:|
| Demo + feasibility + replay | 300000 | 299757 |
| Diagnostics (evals/baselines/footage sim) | 200000 | 179744 |
| PPO fine-tune | 250000 | 249856 |
| BC supervised | 0 env frames | 0 |

## Checkpoints & videos

- step0: `/workspace/examples/apollolander/rl_v7/results/V7_imitation/checkpoints/step0.pt` sha256=`adfacc9bad94960380b4562211de203811ae880717e90d0ba9ba4a3df0e495e8`
- bc: `/workspace/examples/apollolander/rl_v7/results/V7_imitation/checkpoints/bc.pt` sha256=`92b495648420db31babff2e1ddf858470f6b9bcd9028a35b3a30173dc60a019e`
- ppo: `/workspace/examples/apollolander/rl_v7/results/V7_imitation/checkpoints/ppo.pt` sha256=`03df86ad681b7b56cbdcefc0942de87961bedc61983b19a34d42b7f54dea4a20`
- Landing traces persisted for 40 outcomes; Chromium footage for 3 (capped).
- landing bc_l0 seed=703000: video=`/workspace/examples/apollolander/rl_v7/results/V7_imitation/footage/bc_l0_seed703000_landed.mp4` sha256=`75a30ca595dfa9fe6bfd12c59d5c1ef5c02039350f2979cba7997218038f9ef5` reverify=True artifact=`/opt/cursor/artifacts/rl_v7/bc_l0_seed703000_landed.mp4`
- landing bc_l0 seed=703001: video=`/workspace/examples/apollolander/rl_v7/results/V7_imitation/footage/bc_l0_seed703001_landed.mp4` sha256=`91f381d97a8240379c41a3c7b1fa14471221310174b0cd5b1899e3de814b543b` reverify=True artifact=`/opt/cursor/artifacts/rl_v7/bc_l0_seed703001_landed.mp4`
- landing bc_l0 seed=703002: video=`/workspace/examples/apollolander/rl_v7/results/V7_imitation/footage/bc_l0_seed703002_landed.mp4` sha256=`5f513376bd791074b9442a79fa85340a734ca71f9e31cace7953fc23b1193802` reverify=True artifact=`/opt/cursor/artifacts/rl_v7/bc_l0_seed703002_landed.mp4`

## Milestone

- Achieved independent native landing under demonstration-assisted training: **True**
- Explicit label: `demonstration-assisted`

## Representation

Same learner space as V6: continuous thrust, delta{-10,0,+10}, ar=8. Expert absolute target quantized to one ±10/0 step per decision; thrust held. max_steps_v1=8000 required (expert ~6k frames; 3000 falsely times out).

## Artifacts

- Run directory: `/workspace/examples/apollolander/rl_v7/results/V7_imitation`
- Phase JSON: phase0_feasibility.json, phase1_demos.json, phase2_bc.json, phase3_eval.json, phase4_ppo.json

## Notes (demonstration-assisted)

- Demo count 35 < target 50–100: demo/feas/replay hit the 300k physics-frame cap. Kept 11 v1 + 24 L0-near native landings (replay-verified). Trajectory holdout created the BC val split (7/35).
- BC independent landings: **40/40 perfect** on unseen L0-near (`apollolander.starts.l0_near_v6`); **0/23** on v1 under remaining diagnostic budget (untrained v1 0/40). Milestone is L0-near, labeled demonstration-assisted — not reward-only discovery.
- PPO vs BC on same 40 L0-near seeds: BC 40 perfect; PPO 39 perfect + 1 hard. Binary-landing McNemar b=0,c=0,p=1 → **preserves** landing ability. PPO did not discover the maneuver from scratch.
- Expert reference (not a learner): L0-near 20/20 perfect on reference subset.

## Video / checkpoint SHA256

| Artifact | SHA256 |
|---|---|
| step0.pt | `adfacc9bad94960380b4562211de203811ae880717e90d0ba9ba4a3df0e495e8` |
| bc.pt | `92b495648420db31babff2e1ddf858470f6b9bcd9028a35b3a30173dc60a019e` |
| ppo.pt | `03df86ad681b7b56cbdcefc0942de87961bedc61983b19a34d42b7f54dea4a20` |
| bc_l0_seed703000_landed.mp4 | `75a30ca595dfa9fe6bfd12c59d5c1ef5c02039350f2979cba7997218038f9ef5` |
| bc_l0_seed703001_landed.mp4 | `91f381d97a8240379c41a3c7b1fa14471221310174b0cd5b1899e3de814b543b` |
| bc_l0_seed703002_landed.mp4 | `5f513376bd791074b9442a79fa85340a734ca71f9e31cace7953fc23b1193802` |
