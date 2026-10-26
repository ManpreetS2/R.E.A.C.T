# Study v2 pilot (Mission 010): results

Run 2026-10-26 under `docs/STUDY_V2_PROTOCOL.md` (pilot tier, unchanged design): `openai:gpt-5.4-mini`
(response model `gpt-5.4-mini-2026-03-17`), prompt `rewardbench.prompts.v4`, guidance-only, 4 revisions per arm,
1 replicate, development seeds 0-7, 8000 steps. 12 paid calls through `rewardbench.autopilot` in 4 matched,
rotated rounds; 12/12 HTTP 200, 0 retries, 0 provider errors. Exploratory feasibility: **descriptive only, one
session per arm, no hypothesis test.** Raw data: `runs/first-llm-study/pilot-p4/` (local, gitignored; SHA-256 in
`../research-results/MANIFEST.json`). Machine-readable summary with every controller: `pilot_p4_results.json`.
All 96 flight recordings replay-verify.

## Outcomes per revision (8 development starts each)

| Arm | Rev | Valid | Mean reward | Pad landings (gentle) | Crashes | Timeouts | Fuel left | Params changed | Cost (USD) |
| --- | ---: | :---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `no_feedback` | 0 | yes | -39.47 | 3 (3) | 5 | 0 | 655.4 | – | 0.002427 |
| | 1 | yes | +57.09 | 7 (7) | 1 | 0 | 582.1 | 18 | 0.002548 |
| | 2 | yes | +79.93 | 8 (8) | 0 | 0 | 536.7 | 18 | 0.002679 |
| | 3 | yes | +79.39 | 8 (8) | 0 | 0 | 526.4 | 18 | 0.002814 |
| `reward_only` | 0 | yes | -51.75 | 0 | 0 | 8 | 406.7 | – | 0.002437 |
| | 1 | yes | -51.28 | 0 | 0 | 8 | 424.2 | 18 | 0.002647 |
| | 2 | yes | -51.15 | 0 | 0 | 8 | 431.3 | 17 | 0.002862 |
| | 3 | yes | -50.92 | 0 | 0 | 8 | 436.9 | 17 | 0.003072 |
| `numerical_reward` | 0 | yes | +80.72 | 8 (8) | 0 | 0 | 552.7 | – | 0.002436 |
| | 1 | yes | +79.39 | 8 (8) | 0 | 0 | 526.0 | 16 | 0.003752 |
| | 2 | yes | +77.86 | 8 (8) | 0 | 0 | 495.3 | 16 | 0.005067 |
| | 3 | yes | +76.16 | 8 (8) | 0 | 0 | 461.6 | 16 | 0.006389 |

Pilot cost $0.039129 (41,778 tokens); cumulative recorded spend under `runs/first-llm-study` **$0.042646**.

Scripted references (same seeds, `docs/assets/study-v2-baselines/`): demonstration +82.96; bound midpoint +25.90;
revision-matched uniform random search, best of 4: expected +11.1, 8/8 lander with p = 0.58.

## The four questions, kept separate

1. **Valid JSON controller:** yes, 12/12, every one a complete in-bounds guidance controller; none copied a
   prompt value (the prompt contains none).
2. **A controller that lands:** yes. `numerical_reward` landed 8/8 gently at revision 0, before any feedback,
   and `no_feedback` reached 8/8 at revision 2. Those landings come from the hand-designed guidance law plus the
   taught mechanics, not from learning.
3. **Better after feedback:** **no.** `numerical_reward` got worse every revision (+80.72 -> +76.16, burning
   more fuel while already landing gently). `reward_only` stayed at 8/8 timeouts for all four revisions; its
   +0.83 is fuel only.
4. **Feedback beats no feedback and random search:** **no.** The arm that improved most was `no_feedback`
   (-39.47 -> +79.39), which never saw a score. Final-minus-initial: `no_feedback` +118.86, `reward_only` +0.83,
   `numerical_reward` -4.56. Two arms' best controllers beat the random-search reference, but `numerical_reward`
   did so at revision 0 with no feedback, so that is zero-shot quality, not adaptation.

**R.E.A.C.T. did not demonstrate measurable feedback-driven improvement in this pilot.**

## What the controller changes show

In every arm and every revision the model nudged almost every parameter by a small step in the same direction:
lower descent targets, higher `brake_thrust`, higher rotation gains, higher `vy_gain`, slightly higher
`hover_thrust`. It looked like a fixed "make it more careful" edit, applied whatever the feedback said.

* For `no_feedback`, whose revision-0 controller crashed 5/8 by descending too fast, that drift happened to fix
  it.
* For `reward_only`, whose controller timed out by never finishing the descent, the same drift pushed further
  the wrong way. In a scripted offline diagnostic (not a model result), setting only its `vy_gain` from 18 to
  6.5 already lands 4/8 (+10.9), and the model moved `vy_gain` from 18 to 26.
* For `numerical_reward`, already landing gently with `vertical_speed` 0.060 shown against a 0.075 limit, the
  drift only spent fuel.

Rewards of about -51 every revision did not change the direction of the edits.

## Interpretation and limits

* The revision-0 spread (-52 to +81 for the same prompt and model) is sampling variance. With one session per
  arm it is far larger than any plausible feedback effect, so any arm comparison here is anecdotal.
* The pooled headroom rule passed (-3.50 < +70; see the protocol's Deviations), but `numerical_reward`
  individually started at +80.72 with almost no headroom.
* `reward_only` cannot tell a timeout from a crash by reward alone, because the prompt gives the score ordering
  but no magnitudes. This pilot suggests it did not try.
* The study tier is **not** run under v2: the pilot gives no sign that more sessions of the same design would
  measure anything except the model's revision prior.
