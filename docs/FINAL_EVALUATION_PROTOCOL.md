# Final evaluation cohort protocol (research validity)

## Why this document exists

Comparing average reward across **different** research starts between successive
revisions does **not**, by itself, prove controller improvement. Valid claims
require:

1. Matched development starting conditions across feedback arms and revisions.
2. A **frozen** final controller selected without looking at held-out scores.
3. Scoring that frozen controller on a **pre-registered, untouched** final
   evaluation cohort with **no** further model calls.
4. Held-out rewards never entering model prompts or development history.

## Three data classes (do not conflate)

| Class | Purpose | Example |
| --- | --- | --- |
| Development | In-context revision / tuning | `development_seeds` in offline and pilot YAMLs |
| Engineering validation / demo | Pipeline proof, CI, README evidence | Offline mock runs; research baselines; seeds `1000000–1000007` already executed in demos |
| Pre-registered final evaluation | Untouched sealed score for a genuine study | Reserved cohort below — **not yet executed** |

## Burned for final research claims

The following held-out seed list has already been used during engineering
demonstrations and offline validation (including flagship demo held-out runs):

`1000000, 1000001, 1000002, 1000003, 1000004, 1000005, 1000006, 1000007`

Treat results on these seeds as **engineering validation / demo data** only.
They are **not** untouched final-evaluation evidence for the upcoming genuine
LLM study.

Pilot YAML files that still list a subset of these seeds for config
completeness must not be cited as a sealed research holdout once a real
multi-revision study is published.

## Reserved final-evaluation cohort (v1 study)

**Status:** pre-registered identity only. **Do not execute** until the owner
starts the genuine paired LLM experiment and freezes final controllers.

| Field | Value |
| --- | --- |
| Cohort id | `apollolander.final_eval.v1` |
| Schedule formula | `apollolander.starts.v1` (same generator; disjoint seeds) |
| Reserved seed integers | `2000000` … `2000015` (16 seeds) |
| Selection rule | `last_valid_selected` (fixed in advance) |
| Model calls during eval | **none** (`python -m rewardbench.heldout`) |

**Do not** call `derive_start` / adapter evaluation / flight recording against
this cohort until controllers are frozen for the real study. Seed integers are
listed so the cohort is auditable; physical start states and rewards remain
unexposed until execution day.

When execution is authorized, write outcomes only into
`heldout_evaluations` / `heldout_episodes` for that study’s databases and
report them under sealed held-out sections — never back into development
prompts.

## Operator checklist

- [ ] Development arms use matched seeds and identical schemas/budgets.
- [ ] Controller freeze uses `last_valid_selected` (or another pre-declared rule).
- [ ] Final eval uses `apollolander.final_eval.v1` seeds only.
- [ ] No peeking at final-eval rewards before freeze.
- [ ] Reports label engineering-demo held-out separately from final-eval.
