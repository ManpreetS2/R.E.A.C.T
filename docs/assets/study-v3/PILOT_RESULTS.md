# Study v3 pilot results (Mission 012)

**Run 2026-10-27, `openai:gpt-5.4-mini`, protocol `docs/STUDY_V3_PROTOCOL.md` (pilot tier), executed exactly as
written.** Two blocks (`crash1-r1`, `timeout1-r1`) × three arms × three paid revisions = **18 paid calls**.
Machine-readable output of `python -m rewardbench.study_v3 analyze`: `pilot_results.json` (same directory).
Raw databases, prompt logs, autopilot journal and 184 flight recordings: `runs/first-llm-study/v3-pilot/`
(gitignored, local only; per-file SHA-256 in `docs/assets/research-results/MANIFEST.json`).

**Predeclared verdict: G1 passes, G2 fails → "no evidence of feedback use in the v3 pilot". The study tier is not
recommended and was not run.** Everything below the verdict is descriptive; with one block per start type nothing
here supports a causal claim.

## Authorization and spend

| | Value |
| --- | --- |
| Owner authorization | OpenAI `gpt-5.4-mini`; blocks `crash1-r1`, `timeout1-r1`; ≤ 18 paid calls (9 per block); cumulative recorded-spend ceiling $0.21 including history; no study tier, no held-out evaluation |
| Recorded spend before | $0.042646 (Missions 006, 008, 010) |
| Block `crash1-r1` | 9 calls, $0.031890 (worst-case reservation for the block $0.132367) |
| Block `timeout1-r1` | 9 calls, $0.031483; whole-run-fit check before it: $0.074536 + $0.132367 = $0.206903 ≤ $0.21 |
| **Pilot total** | **18 calls, $0.063374** (protocol expected $0.063659, worst case $0.264735) |
| **Cumulative recorded spend** | **$0.106019** (local ledger estimate, not a provider invoice) |
| Provider errors / retries / cost above quote | 0 / 0 / 0 (every call cost 23–30% of its byte-based quote) |
| Held-out or reserved seeds flown | none (development seeds 0–7 only) |

Prompt-log directories contain `revision_NN_call_01.txt` files in addition to `call_00`; these are the
per-invocation prompt logger's counter (`src/rewardbench/run/prompt_log.py`), the same pattern as Mission 010.
Each database holds exactly one paid attempt per paid revision (3 per arm), matching the ledger and the
autopilot journal.

## Preflight (before the first paid call)

* PR #20 (`PROJECT.md`, `AGENTS.md`, `CLAUDE.md`) merged into the v3 branch (README auto-merged, both sides kept);
  GitHub CI green on Windows, macOS and Ubuntu for the merge commit; local suite 440 passed, 0 failed.
* `study_v3 write-configs --check` ok; `study_v3 budget` matched the protocol; `study preflight` matched arms.
* Ledger: recorded spend $0.042646 equals `MANIFEST.json`; all 156 manifest-listed raw files present and SHA-256-identical.
* Provider: key and model verified with a free metadata request (`GET /v1/models/gpt-5.4-mini`, HTTP 200).
  The project key lacks `api.usage.read`, so the provider-side limit was **not** independently read; the repo
  records a $0.25 OpenAI project hard limit, $5 prepaid credit, auto-reload off, which leaves more room than
  the most this ceiling could spend ($0.167).
* Backups: no off-machine backup of `runs/` existed (no GitHub release; none uploaded, owner approval needed).
  Local zip snapshots were made outside the repo before and after the pilot (see `../research-results/RESULTS.md`).
* `study_v3 seed` flew revision 0 offline for each block; all three arms had identical revision-0 flights
  (crash1 −109.5195, timeout1 −65.0719). `autopilot plan` fit before each block; nothing was sent.

## Per-block results

R(k) is mean development reward over seeds 0–7 at revision k; r0 is the shared fixed start (free).
Δ = R(final) − R(0); D = Δ(arm) − Δ(no_feedback). Landing columns are the final revision, out of 8.

### `crash1-r1` (crash-type start, −109.52, 8/8 crashes)

| Arm | Valid | r0 | r1 | r2 | r3 | Δ | Δ best | Landed / gentle / crash / timeout | D vs no_feedback | First-edit alignment | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no_feedback | 3/3 | −109.52 | +87.73 | +87.07 | +86.58 | +196.10 | +197.25 | 8 / 8 / 0 / 0 | — | +0.557 | $0.008064 |
| reward_only | 3/3 | −109.52 | +87.98 | +86.82 | +86.23 | +195.75 | +197.50 | 8 / 8 / 0 / 0 | −0.36 | +0.229 | $0.008597 |
| numerical_reward | 3/3 | −109.52 | +87.82 | +85.71 | +85.71 | +195.23 | +197.33 | 8 / 8 / 0 / 0 | −0.88 | +0.182 | $0.015229 |

Scripted references for `crash1` (16 runs each, committed before any v3 call): reward-driven hill climber mean
Δ +82.93 (median +75.08, 75th pct +133.82); blind random walk mean Δ +33.79.

All three arms made essentially the **same first edit** (largest normalised changes: `descent_low` −0.37 to
−0.49 and `hover_thrust` +0.32 to +0.33, both in the start's helpful direction) and went from 8/8 crashes to 8/8
gentle landings in one revision. The no_feedback arm, which never saw an outcome, did this too. All three then
drifted down by 1–2 reward over revisions 2–3. The crash start was therefore **not diagnostic**: the model's
default "land more gently" edit repairs it regardless of feedback, and every arm far exceeds both scripted
references, including the arm with no feedback.

### `timeout1-r1` (timeout-type start, −65.07, 8/8 timeouts)

| Arm | Valid | r0 | r1 | r2 | r3 | Δ | Δ best | Landed / gentle / crash / timeout | D vs no_feedback | First-edit alignment | Cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |
| no_feedback | 2/3 | −65.07 | −65.11 | −63.36 | invalid | +1.72 | +1.72 | 0 / 0 / 0 / 8 (r2) | — | +0.019 | $0.008057 |
| reward_only | 3/3 | −65.07 | −52.06 | −51.60 | −51.86 | +13.22 | +13.47 | 0 / 0 / 0 / 8 | +11.50 | +0.244 | $0.008591 |
| numerical_reward | 3/3 | −65.07 | −51.81 | −52.27 | −52.45 | +12.62 | +13.26 | 0 / 0 / 0 / 8 | +10.91 | +0.222 | $0.014836 |

The invalid proposal: no_feedback revision 3 set `vy_gain` outside its bound (`vy_gain must be between 0.0 and
40.0`); it was billed, rejected by validation, not flown, and the final controller is revision 2 per the protocol.

Scripted references for `timeout1`: hill climber mean Δ +11.67 (median +8.63, 75th pct +10.42); random walk
mean Δ +10.41.

Here the arms **differed**. Both feedback arms made a large first edit led by `aligned_rotation_limit` (−0.68 /
−0.70 normalised, a helpful direction) together with lower `descent_mid`/`descent_low` (neutral in the
one-parameter probe), gaining about +13 and then holding. no_feedback made small edits and stayed near the start.
No arm landed: every final controller still timed out 8/8. The feedback arms' gain is about the size of the
**scripted references**, including the blind random walk (+10.41 mean); this block alone does not show that the
model did better than undirected search would.

## Pilot summary and go/no-go

| Outcome (2 complete blocks, 0 excluded) | no_feedback | reward_only | numerical_reward |
| --- | ---: | ---: | ---: |
| Mean Δ | +98.91 | +104.48 | +103.93 |
| Mean D vs no_feedback (95% t-interval, n = 2) | — | +5.57 (−69.75, +80.90) | +5.02 (−69.84, +79.87) |
| Mean first-edit alignment | +0.288 | +0.236 | +0.202 |
| …on the crash start / timeout start | +0.557 / +0.019 | +0.229 / +0.244 | +0.182 / +0.222 |
| Mean alignment minus no_feedback | — | −0.052 | −0.086 |
| Mean Δ minus hill-climber mean Δ | +51.61 | +57.18 | +56.62 |

* **G1 engineering: pass.** 17/18 = 94% valid (≥ 90%), no billed provider failures, every cost within its
  quote, both blocks complete with identical revision-0 flights.
* **G2 signal: fail for both feedback arms.** Mean D is +5.6 and +5.0 (threshold +10); mean alignment difference
  is −0.05 and −0.09 (threshold +0.25).
* **Decision (predeclared): stop. Report "no evidence of feedback use in the v3 pilot"; do not scale up.**

## What this pilot does and does not support

Supported, at the claim levels the protocol defines:

1. *Valid controller*: 17 of 18 proposals were schema-valid.
2. *Lands*: from the crash start, all three arms produced controllers with 8/8 gentle landings (the hand-designed
   guidance law plus the model's parameter values). No arm landed from the timeout start.
3. *Improves after feedback*: Δ > 0 for both feedback arms in both blocks. By itself this is not evidence of
   feedback use: no_feedback also improved, by the most on `crash1`.

Not supported:

* **Feedback-driven improvement** (level 4). The predeclared signal rule failed, and with two blocks the intervals
  span about ±75 reward. Nothing here is reinforcement learning; model weights are fixed.
* Any claim of improvement beyond matched random search. On `crash1` all arms beat the references equally,
  no_feedback included. On `timeout1` the feedback arms matched the references.
* Cross-model, cross-task or blind-visual-gameplay claims. This is in-context tuning of an 18-parameter
  hand-designed guidance law (`PROJECT.md` §0.1).

Descriptive observations for the owner (hypotheses, not findings):

* The **timeout block is where feedback could matter**, and there both feedback arms moved +11 to +12 more than
  no_feedback, with positive first-edit alignment on both start types, while no_feedback's alignment flipped from
  +0.56 (crash) to +0.02 (timeout). That is the pattern the protocol associates with feedback use. With one block
  per start it is indistinguishable from chance, and the absolute gain only matched blind random search.
* The **crash start is saturated by the model's prior**: one edit fully repairs it in every arm. Averaged with
  the timeout block, it pulls both G2 metrics below threshold. Whether to change starts or weighting is a
  design question for a *new, separately approved* protocol. This pilot does not re-analyse or re-run itself
  to favour that reading.
* As in v2, all arms drifted slightly downward after their first successful edit.
