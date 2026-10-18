# Clean learning validation v4 — report

**Scientific verdict:** **No clean L0 learning detected.** One PPO policy trained for **250,368** physics frames on `curriculum_l0_v3` with **no** output-layer priors / maneuver bias. **Zero** native landings in training (0/876 episodes) and **zero** landings on the fixed validation set for every frozen checkpoint (deterministic and stochastic). Exploration under a matched no-prior action space is still inadequate. Learning is **not** claimed.

Branch: `cursor/apollolander-rl-clean-v4` (from v3 head `19ffafd`). PR #5 / v3 logs untouched. Upstream game unmodified. Reserved seeds `2000000–2000015` unused. $0 spend.

---

## Integrity fixes (STEP 1) — unit tests

| Fix | Behavior | Tests |
| --- | --- | --- |
| (a) Early stop | Failed learning/integrity check stops at **any** `level_idx`; records `early_stop_reason` | `tests/rl/test_train_integrity.py` |
| (b) Diagnostic cap | `DiagnosticBudget` hard cap **400,000**; overspend raises `DiagnosticBudgetExhausted` (cap not raised) | same |
| (c) Resume | `preserve_resume_artifacts` reloads first-landing map; learning-curve CSV append-only | same + `tests/rl/test_clean_resume_interrupt.py` (forced interrupt/resume) |
| Clean init | `reset_parameters_clean`: orthogonal gain=1.0, zero bias, `thrust_log_std=0`; rejects priors | `tests/rl/test_clean_policy_init.py` |

**Test result:** `16 passed` (`pytest tests/rl/test_train_integrity.py tests/rl/test_clean_policy_init.py tests/rl/test_clean_resume_interrupt.py`).

---

## Experiment design (matched)

| Item | Value |
| --- | --- |
| Engine | Upstream Node VM host of unmodified `frontend/apollolander/upstream/` (Parity V2 engine; engine code unchanged → no parity rerun) |
| Level | `apollolander.starts.curriculum_l0_v3` only (`allow_level_advance: false`) |
| Init | **orthogonal_zero_bias** via `reset_parameters_clean` (not the prior-era head gain=0.01 path) |
| Priors | `soft_thrust_prior=false`, `hold_attitude_prior=false` |
| Action space | Continuous thrust + **delta** rotation `{-10,0,+10}` |
| Horizon | `max_steps=400` for train, step-0, random, and all checkpoint evals |
| Val seeds | `510000–510039` (n=40), fixed before outcomes |
| Train seeds | `82000` pool (100k), non-reserved |
| Baseline | **step-0 checkpoint of the same network** (plus uniform-random on same seeds/horizon) |
| Claim rule | Frozen ckpt beats step-0 on fixed val: Wilson non-overlap **or** two-proportion p&lt;0.01 |

---

## Step-0 equivalence

| Field | Value |
| --- | --- |
| Path | `examples/apollolander/rl_clean_v4/results/CLEAN_L0_s21/checkpoints/step0.pt` |
| sha256 | `90c5c1e10b648bbe03735619bc00d93dd6536e58f9df686ca32fbb2c34747fa4` |
| Batch | 64 obs, seed 12345 |
| max_abs_diff | **0.0** |
| bit_exact | **true** (`logs/step0_equivalence.json`) |

---

## Frame budgets

| Counter | Value |
| --- | ---: |
| Training physics frames | **250,368** / 250,000 cap (one rollout past the cap, then stop) |
| Diagnostic spent (train evals) | **147,737** |
| Diagnostic spent (exploration probes) | **+51,049** → **198,786** total |
| Diagnostic hard cap | **400,000** (remaining **201,214**) |

---

## Step-0 and random baselines (val seeds 510000+, n=40, max_steps=400)

| Agent | perfect | hard | crash | timeout | land rate | Wilson 95% |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| step0 deterministic | 0 | 0 | 40 | 0 | 0.000 | [0, 0.088] |
| step0 stochastic | 0 | 0 | 23 | 17 | 0.000 | [0, 0.088] |
| uniform random (delta) | 0 | 0 | 13 | 27 | 0.000 | [0, 0.088] |

---

## Frozen checkpoint evals vs step-0 (same val set)

All checkpoints: **0 landings**. None beat step-0.

| Checkpoint | frames | det counts (P/H/C/T) | sto counts (P/H/C/T) | beats step0? |
| --- | ---: | --- | --- | --- |
| step0 | 0 | 0/0/40/0 | 0/0/23/17 | n/a |
| step50176 | 50176 | 0/0/40/0 | 0/0/40/0 | no |
| step100352 | 100352 | 0/0/0/40 | 0/0/37/3 | no |
| step150016 | 150016 | 0/0/0/40 | 0/0/24/16 | no |
| step200192 | 200192 | 0/0/40/0 | 0/0/32/8 | no |
| step250368 / final | 250368 | 0/0/40/0 | 0/0/20/20 | no |

Training episodes logged: **876** (652 crash, 224 timeout, **0 land**).

Mid-run det evals at 100k/150k were all **timeout** (hover-like), then returned to crash — still zero landings.

---

## Checkpoint sha256

| Tag | sha256 |
| --- | --- |
| step0 | `90c5c1e10b648bbe03735619bc00d93dd6536e58f9df686ca32fbb2c34747fa4` |
| step50176 | `741bfe61c2763db5e0a7aae260c960d94bdbb93145c0cd28442eba088a6481b8` |
| step100352 | `1e7066c2d32130e9101205848023c159674e9816cd95de73090677aefcf125da` |
| step150016 | `e2e1976311802fec914ea14b2a11c4077bc4d7d9e15393cafc98d635effce11e` |
| step200192 | `b57b3ee6c9a73923e82b1fbf482038b5ad0122a7e18bb7f7c4d8a099e899da1e` |
| step250368 | `82eb18d073b1f7c2ac7386fb932f3e4e6ff0d109c90b889d8c82b60278da968d` |
| final | `4725d1a989b3946d1232dd98fbeafcb4b1df6b2077fe4a7fa057a512ea805449` |

`final` and `step250368` have **identical policy weights** (max abs diff 0); file hashes differ due to non-weight checkpoint fields after stochastic eval RNG use.

---

## Footage

**None.** No frozen checkpoint produced a landing; no browser video recorded.

---

## Exploration probes (remaining diagnostic budget)

Open-loop soft-hold is **solvability only** (not a training prior):

| Probe | counts (P/H/C/T) | land rate |
| --- | --- | ---: |
| L0 random absolute | 0/0/0/40 | 0.000 |
| L0-near random delta (~3–6 px above pad) | 0/0/24/16 | 0.000 |
| L0 open-loop soft thrust 0.22 + hold | 37/3/0/0 | **1.000** |
| L0-near open-loop soft + hold | 40/0/0/0 | **1.000** |
| L0 random binary thrust {0, 0.25} + delta | 0/0/40/0 | 0.000 |

**Plain statement:** under matched no-prior random/NN policies, **no L0 landing was discovered** in 250k train frames or in these random probes. The task remains solvable by a scripted soft-drop, so the failure mode is **exploration**, not physics/scoring.

---

## Recommended next experiment (do not start here)

**Clean L0-near run:** same integrity rules (no priors, matched step-0, diag cap 400k), but start distribution ~3–6 px above pad, upright, low velocity (as in the probe). Action space unchanged (delta). Train ≤250k; step-0 + random + 6 ckpt evals ≈150k diagnostic.

| Cost | Frames |
| --- | ---: |
| Training | ≤ 250,000 |
| Diagnostics (matched evals) | ~150,000 |
| **Total** | **~400,000** |

Rationale: open-loop solvability is 100% on L0-near; random still 0/40 — a cleaner test of whether PPO can discover soft-drop when contact is sooner. If that also yields 0 train landings, next lever is action representation (e.g. coarser thrust bins) with a **new** random-rate probe before any longer train.

---

## Artifact paths

- Run: `examples/apollolander/rl_clean_v4/results/CLEAN_L0_s21/`
- Summary: `…/logs/train_summary.json`
- Evals: `…/logs/checkpoint_evals.json`
- Probes: `…/logs/exploration_probes.json`
- Trainer: `examples/apollolander/rl_clean_v4/train_clean_l0.py`
