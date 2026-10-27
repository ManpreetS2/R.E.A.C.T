# R.E.A.C.T. project handoff (current state)

Last updated: 2026-10-27 (Mission 012: v3 pilot run, results recorded).
`docs/HANDOFF.md` is an older, historical handoff (Agent 4, 2026-10-15); this file supersedes it.

Repository: `ManpreetS2/R.E.A.C.T` (private). Local checkout: `C:\Users\sh1ft\R.E.A.C.T`.

## Where things stand

R.E.A.C.T. measures whether an LLM can improve a controller for the ApolloLander task from reward feedback
(`no_feedback` vs `reward_only` vs `numerical_reward`). The offline v1 infrastructure is merged (PR #2) and verified.
Two single paid exploratory calls (Missions 006, 008) and the 12-call v2 pilot (Mission 010, prompt v4,
`autopilot`, `runs/first-llm-study/pilot-p4/`) and the 18-call v3 pilot (Mission 012,
`runs/first-llm-study/v3-pilot/`) have been made with `openai:gpt-5.4-mini`; total recorded spend **$0.106019**.
Neither pilot found feedback-driven improvement (`docs/assets/study-v2-pilot/RESULTS.md`,
`docs/assets/study-v3/PILOT_RESULTS.md`); the v3 go/no-go failed on G2, so the v3 study tier is not run.
`PROJECT.md` §0 is the canonical status; it was merged into the v3 branch from PR #20 in Mission 012.

## PR stack (all draft, none merged; each stacked on the previous)

| PR | Branch | Content |
| --- | --- | --- |
| [#12](https://github.com/ManpreetS2/R.E.A.C.T/pull/12) | `t3/verify-offline-v1` | Offline v1 verification (base: `main`) |
| [#13](https://github.com/ManpreetS2/R.E.A.C.T/pull/13) | `feature/operator-reward-only` | Operator command, reward-only control, prompt logging |
| [#14](https://github.com/ManpreetS2/R.E.A.C.T/pull/14) | `feature/flight-replay-viewer` | Visual flight replay viewer |
| [#15](https://github.com/ManpreetS2/R.E.A.C.T/pull/15) | `feature/first-llm-study` | First real-LLM study launch package |
| [#16](https://github.com/ManpreetS2/R.E.A.C.T/pull/16) | `feature/spend-ceiling-and-billing-guide` | Aggregate USD ceiling, fail-closed ledger, billing guide (CI green on 3 OSes at `0ed02c9`) |
| [#17](https://github.com/ManpreetS2/R.E.A.C.T/pull/17) | `feature/controller-instance-prompt-v3` | Prompt v3 + prompt version in experiment identity (head `82ae009`) |
| [#18](https://github.com/ManpreetS2/R.E.A.C.T/pull/18) | `feature/prompt-v4-guidance-autopilot` | Missions 008-009 work in progress: prompt v4, v2 protocol, autopilot, baselines, results manifest |

PRs #3-#11 are unrelated RL research branches off `main`.

## Missions

| Mission | What | Status |
| --- | --- | --- |
| 001-005 | Offline v1, operator, replay viewer, study launch package | Done (PRs #12-#15) |
| 006 | First paid call (prompt v2). Model echoed the schema. | Done; failed as evidence. $0.00258375 |
| 006b | Spend ceiling + billing guide; Windows CI fix (unclosed SQLite handles in tests) | Done (PR #16) |
| 007 | Prompt v3: schema vs instance, example, error messages, prompt version in hash, live guard | Done, offline (PR #17); 399 tests passed at `82ae009` |
| 008 | Paid call with prompt v3: valid but copied the prompt's example; 8/8 timeouts. $0.00093225 | Done; failed as evidence |
| 009 | v2 protocol, prompt v4 (guidance-only, mechanics taught, no copyable controller), `autopilot`, scripted baselines, v2 configs | Done (PR #18, CI green on 3 OSes) |
| 010 | v2 pilot: 12 paid calls via `autopilot`, 3 arms x 4 revisions. 12/12 valid; no feedback-driven improvement. $0.039129 | Done (`docs/assets/study-v2-pilot/RESULTS.md`); study tier not run |
| 011 | v3 design: shared fixed failing starts, matched random-search references, edit alignment, `--require-whole-run-fit` | Done, offline (PR #21, CI green on 3 OSes) |
| 012 | PR #20 merged into the v3 branch; v3 pilot: 18 paid calls, 2 blocks x 3 arms x 3 revisions, 17/18 valid. G1 pass, G2 fail: no evidence of feedback use. $0.063374 | Done (`docs/assets/study-v3/PILOT_RESULTS.md`); study tier not run |

## Test results at this checkpoint

Command (Windows, `.venv`, no API key in the environment):

```powershell
$env:PYTHONPATH='src'; $env:MPLBACKEND='Agg'
.\.venv\Scripts\python.exe -m pytest tests/core tests/providers tests/prompts tests/analysis tests/environments -p no:warnings -o addopts="" --import-mode=importlib -q
```

Result on the exact tree committed in this checkpoint: **425 passed, 0 failed** (3m58s). The ApolloLander Node
checks (`physics.test.js`, `replay.test.js`) pass. An earlier run of the same suite on the uncommitted tree showed
2 failures (a stale `prompts.v3` assertion in `test_first_call_safety.py` and a mocked-transport fixture in
`test_first_llm_study.py`); both were fixed in the working tree by a concurrent session before this commit, and are
included in it. GitHub Actions had not run on this branch when this was written, so do not call it green yet.

## Known bugs, limits and scientific caveats

* Mission 009 code has not had a review pass and its CI has not run.
* **Exploratory, post-hoc:** v2 was designed after two failures. Missions 006/008 are excluded from analysis.
* **Ceiling effect (largest risk):** scripted guidance at bound midpoints scores +25.90, and one fact (`descent_low`)
  takes it to +81.43 versus the hand-tuned +82.96. If the model saturates at revision 0 there is nothing to
  improve and the study tier must not run (the pilot go/no-go headroom rule: revision-0 mean below +70).
* v2 measures in-context tuning of a hand-designed control law, not controller design.
* `reward_only` can partly decode outcomes from reward size. One model, one task, no temperature control.
* The aggregate spend ledger is a software estimate. OpenAI prepaid credit and project limits are not instant
  cutoffs. The cross-process lock only covers live runs started through `rewardbench.operate`/`autopilot`.
* Cost reservations are byte-based and over-reserve several-fold; a matched v4 round reserves about $0.0311.
* Prompt-version guard only applies to configs that record `metadata.prompt_template` (the study configs do).
* `docs/assets/first-llm-study-rehearsal/` prompt samples still show old wording.

## Experiment evidence (see `docs/assets/research-results/`)

`RESULTS.md` (summary, backup options) and `MANIFEST.json` (experiment ids, costs, outcomes, per-file SHA-256).
Raw artifacts live only under gitignored `runs/` on this PC: `runs/first-llm-study/pilot/` (Mission 006) and
`runs/first-llm-study/pilot-p3/` (Mission 008, includes 8 flight recordings) and `runs/first-llm-study/pilot-p4/`
(Mission 010, 3 databases, 96 flight recordings). **They are not backed up online.**
Never modify, delete or resume them.

## Next recommended mission

1. Owner review of the v3 pilot (`docs/assets/study-v3/PILOT_RESULTS.md`). Its predeclared rule says stop:
   no study tier. No further paid run is authorized.
2. Decision on an off-machine private backup of `runs/` (local zip snapshots exist in
   `C:\Users\sh1ft\R.E.A.C.T-backups\`; see `docs/assets/research-results/RESULTS.md`).
3. Owner decision on direction (`PROJECT.md` §0.3): the blind visual-gameplay track, or a new, separately
   approved controller-tuning protocol. The pilot's descriptive pattern (crash start saturated by the model's
   prior; arms separated only on the timeout start) is a hypothesis for such a protocol, not a result.

## Exact steps to resume

```powershell
cd C:\Users\sh1ft\R.E.A.C.T
git fetch origin
git checkout feature/prompt-v4-guidance-autopilot      # tracks origin
git log -1 --oneline
py -m venv .venv                                       # only if .venv is missing
.\.venv\Scripts\python.exe -m pip install -e ".[dev,analysis,environments]"
.\.venv\Scripts\python.exe -m rewardbench.study write-configs --check
.\.venv\Scripts\python.exe -m rewardbench.study preflight
.\.venv\Scripts\python.exe -m rewardbench.study budget
```

The OpenAI key is only ever loaded by the owner into their own PowerShell session as `OPENAI_API_KEY`
(never in a file, chat or commit). No agent should run `--mode live`, `--i-authorize-paid-api-calls`,
`--authorize-automatic-revisions`, any reserved final seed, or merge any PR without explicit owner approval.
