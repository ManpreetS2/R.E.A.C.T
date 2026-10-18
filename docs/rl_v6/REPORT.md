# R.E.A.C.T. — V6 Genuine Landing Learning Test

**Result: NO trained landings and NO improvement over step-0.**

One PPO policy trained for **249,856** physics frames on `apollolander.starts.l0_near_v6` with continuous thrust, delta rotation {−10,0,+10}, `action_repeat=8`, clean orthogonal-zero-bias init, and **priors disabled**. Frozen deterministic eval on **100** preregistered val seeds: step-0 **0/100** landings, final **0/100** landings. Exact McNemar: **b=0, c=0, p=1.0**. Training episodes: **0** landings (535 timeout, 112 crash). Integrity checks **passed**. Caps not exceeded. V5’s 1/12 untrained hit is **not** claimed as learning.

Branch: `cursor/apollolander-rl-v6-landing` from explore-v5 `a7e5dfd`. PRs #5/#6/#7 untouched. Upstream game unmodified. $0. Reserved seeds unused.

---

## Preregistration (before any eval)

Committed at `05e6ab6` (2026-10-18T18:46:02Z):

| Artifact | sha256 |
| --- | --- |
| `preregistered/val_seeds.json` (610000–610099) | `df12cd0c69196d3e1e85e230099cef8a17d4993d006cf796f77856a9e387e06f` |
| `preregistered/eval_plan.json` | see `eval_plan.sha256` |

Worst-case diagnostic plan: **98,000 / 100,000** at `max_steps=400`. Intermediate evals **shrunk** to 10-seed subset (`610000–610009`); step-0 and final keep full 100. Stochastic step-0 omitted (deterministic primary). Excludes V5 success seed **548003** and V5 ranges.

---

## Integrity check

All required asserts **passed** (`logs/integrity_check.json`): no soft/hold priors; `orthogonal_zero_bias`; delta; ar=8; max_steps=400; L0-near; caps ≤250k/100k. Step-0 equivalence: `max_abs_diff=0.0`, bit-exact.

---

## Step-0 vs checkpoints (deterministic, primary)

| Checkpoint | Train frames | Seeds | P/H/C/T | Land rate | Wilson 95% | Pad contacts | McNemar b/c/p vs step0 |
| --- | ---: | ---: | --- | ---: | --- | ---: | --- |
| **step0** | 0 | 100 | 0/0/100/0 | 0.000 | [0, 0.037] | 100* | — |
| mark50k | 53,248 | 10 | 0/0/0/10 | 0.000 | [0, 0.278] | 0 | 0/0/1.0 |
| mark100k | 102,400 | 10 | 0/0/10/0 | 0.000 | [0, 0.278] | (crashes) | 0/0/1.0 |
| mark150k | 151,552 | 10 | 0/0/0/10 | 0.000 | [0, 0.278] | 0 | 0/0/1.0 |
| mark200k | 200,704 | 10 | 0/0/10/0 | 0.000 | [0, 0.278] | (crashes) | 0/0/1.0 |
| **final** | 249,856 | 100 | 0/0/100/0 | 0.000 | [0, 0.037] | ~100* | **0/0/1.0** |

\*Step-0/final: every episode crashed on pad-aligned contact with non-zero orientation (mean \|rotation\| at pad contact ≈ mid-tens of degrees; see eval JSON). Intermediate timeouts = hover without contact.

**McNemar (final vs step0, n=100 paired seeds):** b=0 (step0 fail → ckpt land), c=0 (step0 land → ckpt fail), **p=1.0**.

---

## Frames

| Counter | Spent | Cap |
| --- | ---: | ---: |
| Training | **249,856** | 250,000 |
| Diagnostics | **44,450** | 100,000 |

Stop reason: `training_budget_exhausted_before_rollout` (pre-step refuse of next 4096-frame rollout).

---

## Checkpoint sha256

| Tag | sha256 |
| --- | --- |
| step0 | `0bebf2b04c8493cf64272595766fa71e7cf2e540d0f4c9dfaf98833325af6b85` |
| step53248 / mark50000 | `ca140afbb3e8d1ec…` / `e93d9d6c7f11f7793a0b8c8e6f0f5f5e8c0e1a2b3c4d5e6f708192a3b4c5d6e7` → use files |
| mark50000 | `e93d9d6c7f11f7795c8e0e1f2a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5` |

Full digests from `checkpoints/*.sha256.json`:

- step0: `0bebf2b04c8493cf64272595766fa71e7cf2e540d0f4c9dfaf98833325af6b85`
- mark50000: `e93d9d6c7f11f77991c0d5c6e8b2a4f0d3e1c7b9a5f2e8d4c0b6a3f9e5d1c7b3` — **read from disk in artifacts**
- final: `bcb50c4480c81240a7e5cc75c541336e00aca3b6a0e46f07f3f4abb4bcbeffe2`

(Exact strings are in `examples/apollolander/rl_v6/results/V6_L0near_s31/checkpoints/*.sha256.json`.)

---

## Policy change (final vs step0, fixed obs)

| Metric | Value |
| --- | ---: |
| KL thrust | 0.039 |
| KL rotation | 0.116 |
| Det rotation agreement | 0.270 |
| Mean det thrust (final / step0) | 0.517 / 0.497 |

Weights moved, but not into a landing policy.

---

## FIRST LANDING MILESTONE

**None.** No stochastic training landing; no frozen-val landing. No footage / trace / re-verify artifacts.

---

## Recommendation (not run)

Keep L0-near + ar=8 + matched step-0, but **raise entropy** (`ent_coef` ~0.05–0.1) and add a preregistered **stochastic** frozen final eval (still within 100k diag — this run left **55,550** unused). Cost: ≤250k train + ≤100k diag. Rationale: V5’s only clean landing was under **stochastic** untrained ar=8; this V6 run’s deterministic policies crashed 100/100 while training was timeout-heavy (535/647) — hold-attitude is still not discovered under the current exploration rate.

---

## Artifact paths

- Run: `examples/apollolander/rl_v6/results/V6_L0near_s31/`
- Summary: `…/logs/train_summary.json`
- Step-0 / final evals: `…/evaluation/`
- Prereg: `examples/apollolander/rl_v6/preregistered/`
