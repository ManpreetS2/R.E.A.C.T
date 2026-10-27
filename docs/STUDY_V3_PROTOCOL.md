# Study v3: controlled feedback experiment (`feedback_study.v3`)

**Status: written 2026-10-26, NOT EXECUTED.** No paid call has been made under this protocol. It was written
after the v2 pilot (Mission 010, `docs/assets/study-v2-pilot/RESULTS.md`), so it is informed by v2's
outcomes; it is fixed before any v3 model output exists. After the first v3 paid call, edit it only in the
dated "Deviations" section at the end. v1/v2 evidence and configs are untouched (`configs/study/`,
`configs/study/archive/`, `runs/first-llm-study/pilot*/`; a test pins the Mission 010 experiment ids).

## What v2 showed, and the one thing v3 changes

In the v2 pilot each arm's revision 0 was a separate model draw from the same prompt; the draws ranged from
-52 to +81, larger than any plausible feedback effect, and every arm then applied the same "be more careful"
edit regardless of feedback. Two consequences: (1) arms must be compared on **improvement from a shared
start**, not on unrelated initial scores; (2) the start must be one where the right edit depends on what
went wrong, so feedback is necessary to know which way to move.

v3 therefore changes **only the starting point**: every arm of a block begins from the **same fixed
controller**, flown as revision 0 without a model call. Everything else is v2's matched design, unchanged:

| Unchanged from v2 | Value |
| --- | --- |
| Task difficulty | research starts `apollolander.starts.v1`, 8000 steps, `vary_fuel false`, development seeds 0-7 every revision |
| Prompt | `rewardbench.prompts.v4` byte-for-byte (guidance-only, mechanics taught, no copyable controller) |
| Feedback design | `no_feedback` (controllers only), `reward_only` (per-episode reward), `numerical_reward` (reward + success, steps, crashed, metrics) |
| Model | `openai:gpt-5.4-mini`, `max_output_tokens 800`, `reasoning_effort none`, JSON mode, no temperature, 0 retries |
| Revisions | 4 per arm (v2 pilot length): revision 0 = fixed start (free), revisions 1-3 = paid calls; history window 4 |

Task difficulty and feedback design are deliberately **not** changed here. If v3 finds no feedback effect,
a harder task or a richer feedback channel is a separate later protocol, run against this one as its control,
never mixed into it.

## Fixed starts (selected before any v3 model output; scripted flights only)

Pool: the 48 controllers of the v2 uniform guidance search (seed 20261026, drawn before any model data),
rounded to 3 significant figures and clipped to the bounds; the rounded controllers are what is flown.
Rule: a start has **no pad landing** and **at least 6 of 8 episodes of one failure type**; the first
qualifying pool indices are taken, crash type and timeout type separately. No model output and no
"repairability" judgement enters the choice. `python -m rewardbench.study_v3 starts` reproduces
`docs/assets/study-v3/starts.json` (a test re-flies two of them).

| Start | Pool # | Tier | Mean reward | Crashes | Timeouts | Helpful directions (+ raise, − lower) |
| --- | ---: | --- | ---: | ---: | ---: | --- |
| `crash1` | 3 | pilot + study | -109.52 | 8 | 0 | −vx_gain, −vx_limit, −rotation_gain, −cruise_rotation_limit, −descent_mid, −descent_low, −altitude_mid, −altitude_low, +hover_thrust, −vy_gain, −brake_thrust |
| `crash2` | 6 | study | -115.12 | 8 | 0 | −vx_gain, +vx_limit, −cruise_rotation_limit, −descent_aligned, −descent_cruise, −descent_low, −vy_gain |
| `crash3` | 8 | study | -110.86 | 8 | 0 | −vx_limit, −aligned_rotation_gain, −descent_low |
| `timeout1` | 1 | pilot + study | -65.07 | 0 | 8 | −vx_gain, −rotation_gain, −aligned_rotation_gain, −aligned_rotation_limit, −cruise_rotation_limit, +aligned_vx, −descent_aligned, +descent_cruise |
| `timeout2` | 2 | study | -52.83 | 0 | 8 | −vx_limit, +descent_aligned, +descent_cruise, −hover_thrust, −brake_thrust |
| `timeout3` | 5 | study | -52.10 | 0 | 8 | +descent_mid |

Of the 48 pool controllers, 10 qualify as crash type and 14 as timeout type; the rest land at least once or are mixed.

Helpful edit directions (used only for the secondary edit-alignment outcome): from each start, every
parameter is moved +25% and -25% of its bound range alone; a parameter's direction is +1 or -1 when one way
beats the other by at least 1.0 reward and improves on the start by at least 1.0, otherwise 0. Physically
they say what one expects: crash starts improve with a lower touchdown target (`descent_low`) and gentler
gains; timeout starts improve with faster descent targets or less hover thrust. The step and threshold were
fixed before any v3 call (a ±10% probe was tried first and found too flat to define directions on the
timeout plateaus; that is recorded here, not hidden).

## Design

* **Block** = one start × one replicate × the three arms. Within a block arms differ only in
  `feedback_condition` and names (enforced by `check_matched` and tests); blocks differ only in the start,
  the replicate (which reorders the same 8 seeds) and names.
* **Pilot tier (first paid experiment):** 2 blocks, `crash1-r1` and `timeout1-r1`: 18 paid calls.
* **Study tier (confirmatory, separate approval):** 6 starts (`crash1-3`, `timeout1-3`) × 2 replicates =
  12 blocks, 108 paid calls. Pilot sessions are not reused in the study analysis.
* Names `llmstudy3-<tier>-openai-gpt54mini-<arm>-p4-<start>-r<k>`; databases under
  `runs/first-llm-study/v3-<tier>/`, inside the ledger root `runs/first-llm-study` so all earlier spend counts.
  Configs: `configs/study_v3/` (generated; a test enforces they are current).
* Execution per block: `study_v3 seed` flies revision 0 offline for all three arms (identical flights, $0),
  then `rewardbench.autopilot run ... --require-whole-run-fit` makes the 9 paid calls in 3 matched rounds
  with rotated arm order, one call per `rewardbench.run` invocation, under the aggregate ceiling. The live CLI
  and the autopilot both refuse an arm whose fixed start has not been seeded.

## Outcomes (computed by `python -m rewardbench.study_v3 analyze`; nothing else is reported as a result)

Per arm in a complete block, with R(k) the mean development reward of revision k and R(0) the shared start:

1. **Primary: Δ = R(final) − R(0)**, final = last valid selected controller (the start itself if no paid
   proposal is valid, so Δ = 0). Contrast per block: **D = Δ(feedback arm) − Δ(no_feedback)**.
2. Secondary: Δ_best (best revision minus start); landings, gentle landings, crashes, timeouts at the final
   revision; valid fraction; cost.
3. Secondary, **does the edit respond to the failure?** Edit alignment of the first valid edit (start →
   first valid paid revision) against the start's helpful directions: (Σ direction × normalised change) /
   Σ |normalised change|, from −1 (every change hurts) to +1. Reported overall and **by start type**. An arm
   that applies one fixed edit regardless of failure (the v2 pattern) scores with opposite signs on crash and
   timeout starts; an arm that uses feedback scores positive on both. no_feedback cannot know the failure, so
   it is the drift control.
4. References (scripted, free, `docs/assets/study-v3/random_search.json`): for each start, 16 runs of a
   **reward-driven hill climber** (3 proposals, Gaussian steps σ = 0.10 of each bound range, clipped, keep only
   improvements: the matched "uses the reward, no understanding" baseline) and a **blind random walk** (same
   steps, always keeps the latest: the matched "revises without feedback" baseline).

| Start | Start reward | Hill climb: mean Δ | median Δ | 75th pct Δ | improved | Random walk: mean Δ | improved |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `crash1` | -109.52 | +82.93 | +75.08 | +133.82 | 100% | +33.79 | 94% |
| `crash2` | -115.12 | +53.43 | +41.19 | +88.33 | 100% | +52.11 | 100% |
| `crash3` | -110.86 | +35.87 | +1.38 | +3.25 | 88% | +45.11 | 62% |
| `timeout1` | -65.07 | +11.67 | +8.63 | +10.42 | 100% | +10.41 | 69% |
| `timeout2` | -52.83 | +9.80 | +2.21 | +2.75 | 75% | -12.95 | 38% |
| `timeout3` | -52.10 | +17.45 | +0.36 | +1.47 | 88% | -0.91 | 38% |

Reading these before any model data: on **crash starts even blind random edits usually help** (a crash scores
below almost everything else), so improvement there says little by itself and the no_feedback arm, the drift
control, is essential; the reward-driven hill climber sets a high bar (+83 mean on `crash1`). On **timeout
starts blind edits do not help** (random walk mean Δ about 0 or negative on `timeout2`/`timeout3`) and the
hill climber gains about +10 to +17. Timeout starts are therefore the cleanest test of whether feedback is used.
These numbers were computed and committed before any v3 call.

## What may be claimed (each level requires the previous)

1. *Valid controller*: a schema-valid guidance controller (counts only).
2. *Lands*: a controller with pad landings (attribute to the hand-designed law plus the model's values).
3. *Improves after feedback*: Δ > 0 for a feedback arm in that block. Not evidence of feedback use by itself.
4. *Feedback beats no feedback and matched random search*: the study-tier rules below. Only this level may be
   described as feedback-driven improvement. Nothing in R.E.A.C.T. is reinforcement learning (weights are
   fixed); results are in-context revision.

## Pilot go/no-go (decided now)

* **G1 engineering:** at least 90% of paid proposals valid, no billed failures, every cost within its
  quote (the autopilot stops otherwise), both blocks complete with identical revision-0 flights across arms.
* **G2 signal:** for at least one feedback arm, mean D ≥ +10 reward **or** mean first-edit alignment minus
  no_feedback's ≥ 0.25.
* Both pass → recommend the study tier (owner approval of its budget required). G1 fails → stop and fix the
  engineering. G2 fails → stop: report "no evidence of feedback use in the v3 pilot"; do not scale up.
  The pilot is descriptive; with 2 blocks it cannot establish anything by itself.

## Study tier rules (confirmatory, decided now)

* Hypotheses H1: D(reward_only) > 0; H2: D(numerical_reward) > 0, over the 12 blocks (paired by block).
  Two-sided 95% t-intervals, Holm-adjusted over the two; **supported** only if the adjusted interval excludes 0
  with a positive mean.
* Beats matched random search: an arm's mean (Δ − hill-climber mean Δ for that start) has a 95% t-interval
  above 0. A supported H without this is reported as "feedback helped, but no better than reward-driven
  random search".
* Edit-responsiveness is secondary and descriptive (mean alignment by start type, per arm).
* Exclusions: a block that is incomplete (any arm stopped early), whose arms do not share identical
  revision-0 flights, or that hit a provider error is excluded and reported; it is never re-run to replace a
  bad result. Pilot blocks are excluded from the study analysis.

## Stopping rules (all before any request)

The aggregate ceiling over `runs/first-llm-study`, the owner's call limit, `--require-whole-run-fit` (a block
starts only if the worst case of all its remaining calls fits), the autopilot safety stops (provider error,
unreadable ledger, foreign spend, cost above reservation, inconsistent state) and its early stop (every arm 2
invalid or 2 unchanged controllers in a row). Zero retries. No ceiling or limit is raised mid-run without a
dated deviation and the owner's written approval. No held-out or reserved seed is flown by v3.

## Price (exact worst-case bounds from the pricing catalog; expected from Mission 010's measured calls)

Catalog `2026-10-14`, `openai:gpt-5.4-mini` at $0.75 / $4.50 per 1M input / output tokens. Worst case is the same byte-based reservation the live gates enforce (one token per UTF-8 byte + 64, 800 output tokens, worst-case history entries); expected is what the same prompt cost per call in Mission 010.

| Per block, arm | Call (revision) 1 | 2 | 3 | Worst case | Expected |
| --- | ---: | ---: | ---: | ---: | ---: |
| `no_feedback` | $0.011150 | $0.012013 | $0.012875 | $0.036038 | $0.008041 |
| `reward_only` | $0.011426 | $0.012517 | $0.013607 | $0.037550 | $0.008581 |
| `numerical_reward` | $0.014963 | $0.019593 | $0.024223 | $0.058779 | $0.015208 |
| **block (9 calls)** | $0.037539 | $0.044122 | $0.050706 | **$0.132367** | **$0.031829** |

| Tier | Blocks | Paid calls | Worst case | Expected |
| --- | ---: | ---: | ---: | ---: |
| pilot | 2 | 18 | $0.264735 | $0.063659 |
| study | 12 | 108 | $1.588410 | $0.381954 |

## Proposed first paid experiment (needs the owner's approval; nothing here authorizes it)

**v3 pilot: blocks `crash1-r1` then `timeout1-r1`, 18 paid calls, `openai:gpt-5.4-mini`.**

* Recorded spend so far: $0.042646. Expected pilot cost $0.0637, so
  about $0.106 cumulative.
* **Requested ceiling: $0.21 cumulative under `runs/first-llm-study`, at most 18 paid calls.** With
  `--require-whole-run-fit`, block 1 starts only if $0.0426 + $0.1324 ≤ ceiling and block 2
  only if the spend after block 1 (about $0.0740) + $0.1324 ≤ ceiling, so $0.21 lets both
  blocks run to completion and nothing can be stranded half-way. The mission's current $0.18 covers block 1
  only; block 2 would then be refused before any request (verified offline, below).
* Exact commands (PowerShell; the key only in the owner's own session as `OPENAI_API_KEY`):

```powershell
$py = ".\.venv\Scripts\python.exe"
& $py -m rewardbench.study_v3 write-configs --check
foreach ($block in "crash1_r1", "timeout1_r1") {
  $cfg = "no_feedback", "reward_only", "numerical_reward" | % { "configs/study_v3/pilot_${block}_$_.yaml" }
  & $py -m rewardbench.study_v3 seed --config $cfg[0] --config $cfg[1] --config $cfg[2]          # free
  & $py -m rewardbench.autopilot plan --config $cfg[0] --config $cfg[1] --config $cfg[2] `
      --out runs/first-llm-study/v3-pilot --ledger-root runs/first-llm-study `
      --total-usd-ceiling 0.21 --max-total-calls 9 --require-whole-run-fit                          # free
  & $py -m rewardbench.autopilot run --mode live --i-authorize-paid-api-calls --authorize-automatic-revisions `
      --config $cfg[0] --config $cfg[1] --config $cfg[2] --out runs/first-llm-study/v3-pilot `
      --ledger-root runs/first-llm-study --total-usd-ceiling 0.21 --max-total-calls 9 --require-whole-run-fit
}
& $py -m rewardbench.study_v3 analyze --out runs/first-llm-study/v3-pilot --json docs/assets/study-v3/pilot_results.json
```

* Then apply the pilot go/no-go above and stop. The study tier (108 calls, expected about
  $0.38, worst case $1.59) needs its own approval;
  its worst case is above the $1.00 research total, so it would have to run block by block under a ceiling the
  owner sets, with incomplete blocks excluded.

## Risks

1. **Small pilot.** Two blocks are a feasibility check; the go rule guards against scaling a null result,
   not against a lucky pilot (the study tier is the test).
2. **Directions are one-parameter probes.** They ignore interactions; alignment is secondary for that reason.
3. **Starts are far from good.** A crash start needs a large repair; improvement may need more than 3
   revisions. That is the same for all arms and for the random-search references.
4. **reward_only cannot read the failure type** except through reward size (crash about −110, timeout about
   −50 to −65 here); whether the model infers it is part of what is measured.
5. **One model, one task, no temperature control, provider snapshot drift** (recorded per call; arm order
   rotates within each block).
6. **Informed by v2.** The design and start rule were written after v2's results; they were fixed before any v3
   data, which is what this document records.

## Deviations

None. Execution record, 2026-10-27 (Mission 012): the pilot tier ran with the exact commands above under the
owner's written authorization (OpenAI `gpt-5.4-mini`, blocks `crash1-r1` and `timeout1-r1`, ≤ 18 paid calls,
$0.21 cumulative ceiling). Both blocks completed: 18 calls, $0.063374, cumulative recorded spend $0.106019.
G1 passed, G2 failed: no evidence of feedback use, study tier not run. Results:
`docs/assets/study-v3/PILOT_RESULTS.md`. The status line at the top is kept as written at design time.
