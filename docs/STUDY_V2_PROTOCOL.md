# Study v2: revised exploratory protocol (`first_llm_study.v2`)

**Status: written 2026-10-26; pilot executed 2026-10-26 (Mission 010, see Deviations); study tier not run.** It was written
**after** two paid exploratory calls under the original protocol (`FIRST_LLM_STUDY_PROTOCOL.md`, v1), so it is
not a pre-registration of the original study and must not be presented as one. It fixes the revised design,
outcomes and stopping rules before any v2 call. After the first v2 paid call, edit it only in the dated
"Deviations" section at the end.

## Why there is a v2 (what happened under v1)

| Date | Mission | Prompt | Outcome | Cost |
| --- | --- | --- | --- | ---: |
| 2026-10-26 | 006 | `rewardbench.prompts.v2` | model returned the schema document; invalid; nothing flown | $0.00258375 |
| 2026-10-26 | 008 | `rewardbench.prompts.v3` | valid, but a verbatim copy of the prompt's "format illustration" `{"policy":"constant","rotation":0,"thrust":0.5}`; 8/8 timeouts, mean reward -104.56 | $0.00093225 |

Both are **exploratory engineering attempts**. They are excluded from every v2 analysis, kept unmodified for
audit (`runs/first-llm-study/pilot/`, `runs/first-llm-study/pilot-p3/`), and their configs are archived in
`configs/study/archive/prompt_v2/` and `prompt_v3/`. Their recorded spend counts toward every later ceiling.
Mission 008 showed that v3 tested whether the model copies a supplied example, not whether it can design a
controller.

## Simulator evidence gathered before writing v2 (scripted controllers only, no model)

`python -m rewardbench.study baselines --out docs/assets/study-v2-baselines/baselines.json` flies these on the
development seeds 0-7 (research starts `apollolander.starts.v1`, 8000 steps, `vary_fuel false`). These are
diagnostics, never AI results.

| Controller | Mean reward | Pad landings (gentle) | Crashes | Timeouts | Fuel left |
| --- | ---: | ---: | ---: | ---: | ---: |
| guidance, hand-tuned demonstration | +82.96 | 8 (8) | 0 | 0 | 597.5 |
| guidance, every parameter at its bound midpoint | +25.90 | 8 (0) | 0 | 0 | 657.4 |
| guidance, midpoints but `descent_low` 0.05 | +81.43 | 8 (8) | 0 | 0 | 569.5 |
| constant 0.5 / 0 deg (Mission 008's reply) | -104.56 | 0 | 0 | 8 | 200.4 |
| constant 0.333 / 0 deg (upright hover) | -62.71 | 0 | 1 | 7 | 498.1 |
| constant 0 (free fall) | -98.47 | 0 | 8 | 0 | 1000.0 |
| random, seed 0 / seed 1 | -94.85 / -95.21 | 0 | 0 | 8 | ~202 |

Uniform random search over the 18 guidance bounds (48 samples, seed 20261026): 24 samples land at least once,
9 land all 8 starts; per-episode outcomes 15 gentle, 108 hard, 111 crashes, 142 timeouts, 8 off-pad; mean
reward from -122.7 to +81.7 (median -51.3). Given 4 tries (the pilot's revision count), random search finds an
8/8 lander with probability 0.58 and an expected best mean of +11.1. Perturbing every demonstration parameter
by up to ±30% (16 samples) still lands 127 of 128 episodes.

Conclusions: (1) the environment is controllable and reproducible (deterministic traces; recorded flights
replay exactly); (2) open-loop `constant` and `random` controllers cannot land from these starts at all;
(3) the guidance law does most of the work: a mechanical midpoint already lands every start, and **one number
read from the landing rule turns it into a near-optimal controller**.

## Declared change to the controller search space

v1 let the model choose `guidance`, `constant` or `random`. **v2 lets the model propose only `guidance`**: one
JSON object with a concrete, in-bounds value for each of the 18 parameters of the fixed feedback law in
`rewardbench/environments/apollolander/schema.py::guidance_action`. The restriction is recorded as
`metadata.adapter_kwargs.allowed_policies: [guidance]` (it changes the experiment id). A `constant` or `random`
reply is rejected as invalid ("not allowed in this experiment"), never converted. Missing, extra, non-finite or
out-of-range parameters are rejected; nothing is defaulted, repaired, clamped or replaced by a hand-written
controller. `constant` and `random` remain available as scripted baselines through the default adapter.

What this means for interpretation: v2 measures **in-context tuning of a hand-designed control law**, not the
design of a control law. It cannot show that a model invents control structure. That narrower question is the
only one this environment can currently answer without the model copying or ignoring the structure.

## Prompt v4 (`rewardbench.prompts.v4`), identical in every arm

* The task, an **objective** (land gently and upright on the pad from every start, no crash or timeout, little
  fuel, one controller for all starts) and **flight mechanics** taken from `physics.js`: step length and step
  limit; coordinates (x right, y down; vy > 0 descends); `dx` = pad minus ship; gravity 0.0005/step; thrust
  0.0015 x engine level along the ship axis with a 20%/step engine lag; hover at about 1/3 thrust upright;
  rotation lag 30%/step and its direction; negligible horizontal drag; fuel burn; the start ranges of the
  schedule; the exact landing rule (whole base on the pad, rotation exactly 0, vy < 0.15, gentle < 0.075; slope
  contact is a crash; off-pad is not a success; timeout); a qualitative description of the score ordering, with
  no reward magnitudes (so `reward_only` cannot decode outcomes from known bonuses).
* The guidance law step by step, and what each parameter changes (qualitative; no values).
* The schema with bounds, and a reply **shape** with `<number>` placeholders that is deliberately not valid JSON.
* No complete controller, no example values, no tuned or demonstration parameters, no "prefer the smallest
  valid controller". A test parses every JSON object in the rendered prompt and requires that none validates.
* The history and feedback sections are unchanged from v3: `no_feedback` sees only earlier controllers;
  `reward_only` adds per-episode `reward=`; `numerical_reward` adds success, steps, crashed and metrics. The
  shared instructions contain no simulator values (tested for all arms, with and without history).

The worst-case input reservation grows with the prompt: a revision-0 call now reserves about $0.0104 (one matched round of three: $0.031100).

## Matched design

Identical to v1 (`rewardbench.study.study_config`) except the study id, the prompt template, the search space
and the names/paths: `gpt-5.4-mini`, `max_output_tokens 800`, `reasoning_effort none`, JSON mode, no
temperature; development seeds 0-7, the same 8 starts every revision; history window 4; 8000 steps;
`max_model_retries 0`; invalid controllers skipped and shown as invalid; model failure aborts. Names end
`-p4-r<k>`; pilot databases live in `runs/first-llm-study/pilot-p4/`. Tiers: pilot (4 revisions, 1 replicate,
engineering held-out seeds 1000000-1000007) and study (6 revisions, 5 replicates, reserved cohort
2000000-2000015 only after separate final-evaluation approval).

## Exploratory versus controlled

* Missions 006 and 008: exploratory engineering attempts under v1. Excluded.
* v2 pilot: exploratory feasibility. Reported descriptively; no hypothesis test.
* v2 study tier: the controlled comparison. Allowed only after the pilot passes go/no-go below and the owner
  approves its budget. Primary outcome and interpretation rule are those of v1 (mean frozen-controller score on
  the reserved cohort, `reward_only` minus `no_feedback`, 95% t-interval over 5 sessions per arm; "supports"
  only if the interval excludes 0).

## Pilot go/no-go (decided now, before any v2 call)

All of: at least 90% of proposals valid; no billed failures; measured cost within the worst-case bound;
prompts spot-checked for isolation; **and headroom**: the arms' revision-0 mean development reward must be
below +70 (the demonstration scores +82.96, so at +70 or more there is too little left to improve for a
5-session comparison to detect anything). If revision 0 already saturates, the study tier is not run under v2:
the task must first be made harder or the outcome changed (see risks), as a v3 protocol.

Every LLM result is also compared, descriptively, with the scripted references above: the bound midpoint
(+25.90) and revision-count-matched random search (expected best of 4: +11.1, 8/8 lander with p = 0.58). An arm
that does not beat them has not shown controller generation beyond chance.

## Automatic matched rounds (optional; `rewardbench.autopilot`)

Allowed only with the owner's written approval of a total ceiling **and** a maximum number of calls. One
round advances every arm by one revision through the unchanged `rewardbench.run` path (one call per
invocation, preflight, aggregate ceiling over the ledger root, ledger lock, zero retries). Arm order rotates
each round (A,B,C / B,C,A / C,A,B). A round starts only if recorded spend plus the exact worst-case quote of
every arm's next call fits under the ceiling; arms are never advanced selectively, and a round interrupted
part-way is completed first. It stops on provider errors, unreadable ledgers, spend it did not make, cost above
a reservation, terminal or inconsistent state, the call limit, and by default when every arm has returned
2 invalid or 2 unchanged controllers in a row. The default early-stop scope is "all arms" because
`no_feedback` is expected to repeat itself; stopping when any one arm stalls would end the comparison exactly
where the feedback arms might still improve. Reserved seeds are never flown by it (it has no held-out path).

## Remaining risks

1. **Ceiling effect (largest).** The mechanics the owner asked to teach include the gentle-touchdown speed and
   say `descent_low` sets the touchdown speed. Midpoints plus that one fact score +81.43. A capable model may
   land everything gently at revision 0, leaving only fuel efficiency (a few points) to improve; the feedback
   contrast would then be noise. The headroom rule above stops the study tier in that case.
2. **Structure supplied by the environment.** Success depends mostly on the hand-designed law; results say
   little about controller design.
3. **Reward decodability.** `reward_only` can partly infer outcomes from reward size even without magnitudes.
4. **One model, one task, no temperature control, provider snapshot drift** (recorded per call).
5. **Cost reservations.** Byte-based input bounds over-reserve several-fold, so ceilings must be set from
   worst cases; the $0.03 ceiling does not cover one matched round of v2.
6. **Post-hoc revision.** v2 was designed after seeing two failures. The headroom rule and the scripted
   references were fixed before any v2 data, but the design is still informed by v1's outcomes.

## Deviations

**2026-10-26, Mission 010, revision-0 go/no-go (recorded before any revision-1 call).** Round 0 ran under the
unchanged design (3 calls, $0.0073, 3/3 valid, no billed failures, cost within the worst-case bound, prompts
isolated). Revision-0 means: `no_feedback` -39.47, `reward_only` -51.75, `numerical_reward` +80.72; pooled
-3.50. The headroom rule names one mean over the arms, and at revision 0 no arm has seen feedback, so it was
applied to the pooled mean (-3.50 < +70): the pilot continues unchanged. Caveat stated now, not after the data:
`numerical_reward` alone is above +70 (about 2 points below the demonstration), so its pilot trajectory can show
fuel efficiency at most and is not evidence about improvement. The three revision-0 controllers are three draws
from essentially the same prompt; their spread (-52 to +81) is sampling variance, not a feedback effect.

**2026-10-26, Mission 010, pilot outcome.** The pilot finished as specified (12 calls, 4 revisions per arm,
$0.039129; cumulative $0.042646; results in `docs/assets/study-v2-pilot/RESULTS.md`). No feedback-driven
improvement was observed: `numerical_reward` declined (+80.72 -> +76.16), `reward_only` stayed at 8/8 timeouts,
and `no_feedback` improved most (-39.47 -> +79.39) through an edit pattern the model applied in every arm. Per the
go/no-go section the study tier is not run under v2; a redesign is a v3 protocol. Nothing in this protocol or
its evaluation was changed after seeing the results.
