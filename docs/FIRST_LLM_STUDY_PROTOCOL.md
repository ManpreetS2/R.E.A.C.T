# First real-LLM study: protocol (pre-registration draft)

**Status: NOT EXECUTED. No paid call has been made.** Nothing here authorizes spending. Execution needs the
owner's explicit approval of provider, model and a total USD ceiling (see `FIRST_LLM_STUDY_LAUNCH.md`).
A T3 Code, Codex, ChatGPT or Claude subscription is not API credit and provides no API key.

This document fixes the design, outcomes and analysis **before** any live call. Do not edit it after the first
paid call except to record deviations in a dated "Deviations" section.

## Hypothesis

> Does revealing the scalar episode reward to a language model improve the controller revisions it proposes,
> compared with withholding feedback?

Adaptation is **in-context controller revision**: the model's weights never change, and a physics simulator
(ApolloLander, `apollolander.env.v1`) assigns every score. This is not PPO or any weight training.

## Conditions (everything else identical)

| Arm | `feedback_condition` | The model sees about earlier revisions |
| --- | --- | --- |
| A | `no_feedback` | its previous controllers only |
| B | `reward_only` | controllers + the scalar reward of each episode (nothing else) |
| C | `numerical_reward` | controllers + reward + success, crashed, steps and simulator metrics |

Contrasts: **B vs A** isolates the scalar reward. **C vs B** is the added value of outcome and simulator
metrics. A vs C alone cannot isolate reward (C also adds metrics); this is why B exists
(`REWARD_ONLY_CONTROL.md`). Rendered prompts differ only by the condition's disclosure sentence and the
feedback lines (proved by `tests/prompts/test_reward_only.py` and by the rehearsal audit; example prompts in
`docs/assets/first-llm-study-rehearsal/prompts/`).

## Matched design (single source: `rewardbench.study.study_config`)

| Field | Value (all arms) |
| --- | --- |
| Provider / model | `openai` / `gpt-5.4-mini` (**proposal; requires owner approval**) |
| Model settings | `max_output_tokens 800`, `reasoning_effort none`, `json_mode true`; no temperature set |
| Controller schema, prompt version | `rewardbench.apollolander.controller.v1`, `rewardbench.prompts.v3` |
| Development seeds | `0-7`, `episodes_per_revision 8`: **the same 8 starts every revision** |
| History window | 4 revisions |
| Max episode steps / simulator | 8000 / ApolloLander research mode, `apollolander.starts.v1`, `vary_fuel false` |
| Retries | `max_model_retries 0` (no automatic paid retry) |
| Invalid controller policy | `skip` (not flown; shown to the model as invalid) |
| Model failure policy | `abort` |
| Budget block | identical across arms (worst case of the largest arm, rounded up to the cent) |
| Master seed | replicate *r* uses `20261101 + r - 1` for all three arms |

Because every revision flies the same 8 starts, a reward change between revisions cannot come from a change
of starts. Revision 0 has no history, so its prompts are identical across arms apart from the condition
sentence; any revision-0 difference between arms is model sampling noise (manipulation check).

## Tiers

| Tier | Revisions | Replicates | Held-out seeds | Purpose |
| --- | ---: | ---: | --- | --- |
| first call | 1 | 1 per arm | engineering `1000000-1000007` | connectivity, valid-JSON check |
| pilot | 4 | 1 per arm | engineering `1000000-1000007` | feasibility; **never touches the reserved cohort** |
| study | 6 | 5 per arm | reserved `2000000-2000015` (`apollolander.final_eval.v1`) | the registered comparison |

Replicates are independent sessions (separate databases). A resumed session is **not** an extra replicate.
Arm order inside each replicate is rotated (A,B,C / B,C,A / C,A,B / ...) so provider drift is not confounded with arm.

## Outcomes (declared before any live call)

**Primary (study tier).** For each session, freeze the controller selected by `last_valid_selected` from the
development database (never by held-out score), score it on the 16 reserved starts with no model calls, and
take the mean total reward. Primary contrast: **mean session score of `reward_only` minus `no_feedback`**,
reported as a difference with a 95% t-interval over the 5 independent sessions per arm. Interpretation rule:
"supports the hypothesis" only if the whole interval is above 0; otherwise "inconclusive". With 5 sessions
per arm a null result is *not* evidence that reward does not help.

**Secondary (all descriptive, no multiplicity-corrected claims):**
1. Development improvement: mean reward at the final revision minus revision 0 on the same 8 starts, per session.
2. Landing rate of the frozen controller on the reserved cohort.
3. `numerical_reward` minus `reward_only` on the primary measure (value of extra metrics).
4. Fraction of invalid controllers, and revisions until the first landing in development.
5. Tokens, cost, latency per session against the worst-case budget.

**Pilot go/no-go for proceeding to the study** (pilot only, engineering seeds): at least 90% of proposals valid;
no billed failures; measured cost within the worst-case bound; prompts spot-checked for isolation; the model
changes controllers at all (otherwise the study cannot detect anything).

## Controller-freeze rule

`last_valid_selected` from the final development revision, fixed in advance. Held-out scores never enter
prompts or development history (enforced and audited). No tuning after seeing any final-evaluation reward.

## Failure and exclusion policy

* No automatic retries. A failed or unparseable billed call is recorded; under `on_model_failure: abort` the
  session ends `failed` (terminal). It is **reported, not replaced**. A replacement session is a new replicate
  that needs a fresh owner approval and is labeled as such.
* A session with no valid controller at all is reported and excluded from the primary contrast; the report
  shows failures per arm so differential attrition is visible.
* Incomplete arms are never silently dropped; all outcomes, including worse rewards, are reported.
* Resume: one paid call per invocation; continuing requires `--authorize-continuation` after reviewing
  stored results. Stored attempts are never re-billed; terminal states (`failed`, `budget_exhausted`) are not resumed.

## Offline rehearsal (scripted mock, infrastructure only)

`python -m rewardbench.study rehearse` runs this exact design with the scripted model on real physics
(pilot tier results, engineering seeds):

| Arm | Model calls | Dev episodes | Dev mean reward by revision | Held-out mean reward | Replays verified |
| --- | ---: | ---: | --- | ---: | ---: |
| no_feedback | 4 | 32 | [-98.97, -98.97, -98.97, -98.97] | -98.585 | 40 |
| reward_only | 4 | 32 | [-98.97, -200.626, -200.626, -200.626] | -199.965 | 40 |
| numerical_reward | 4 | 32 | [-98.97, -200.626, -200.626, -200.626] | -199.965 | 40 |

These numbers show the machinery works (isolation verified, replays verified, no reserved seed touched). They
say **nothing** about language-model learning; the scripted model's "revision" is a fixed controller that
happens to score worse. Study tier rehearsal: `docs/assets/first-llm-study-rehearsal/study_audit.json`.

## Limitations

* One model, one task. Results do not rank models or generalize beyond ApolloLander.
* Five sessions per arm give wide intervals; this is an exploratory first study.
* The model name resolves to a provider snapshot that can change; the resolved id is stored per call
  (`attempts.model_id`). The pricing catalog is dated `2026-10-14` and was re-checked for this model on 2026-10-24.
* No temperature is set (the model's default); sessions are not reproducible bit-for-bit.
* Reward is partly inferable from the metrics in arm C; B was added to separate the two.
* Software spend caps are not vendor billing guarantees; set a hard limit in the provider dashboard.
* In-context revision is not weight training; do not compare with PPO results.
