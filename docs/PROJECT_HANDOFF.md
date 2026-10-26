# R.E.A.C.T. project handoff (current state)

Last updated: 2026-10-26 (emergency checkpoint, written from a low-usage session).
`docs/HANDOFF.md` is an older, historical handoff (Agent 4, 2026-10-15); this file supersedes it.

Repository: `ManpreetS2/R.E.A.C.T` (private). Local checkout: `C:\Users\sh1ft\R.E.A.C.T`.

## Where things stand

R.E.A.C.T. measures whether an LLM can improve a controller for the ApolloLander task from reward feedback
(`no_feedback` vs `reward_only` vs `numerical_reward`). The offline v1 infrastructure is merged (PR #2) and verified.
Two single paid exploratory calls have been made with `openai:gpt-5.4-mini` (total **$0.003516**). The study
itself has **not** been run. A revised protocol (v2, prompt v4, guidance-only) and an automatic-round tool
(`autopilot`) are written but **no paid call has been made under them**.

## PR stack (all draft, none merged; each stacked on the previous)

| PR | Branch | Content |
| --- | --- | --- |
| [#12](https://github.com/ManpreetS2/R.E.A.C.T/pull/12) | `t3/verify-offline-v1` | Offline v1 verification (base: `main`) |
| [#13](https://github.com/ManpreetS2/R.E.A.C.T/pull/13) | `feature/operator-reward-only` | Operator command, reward-only control, prompt logging |
| [#14](https://github.com/ManpreetS2/R.E.A.C.T/pull/14) | `feature/flight-replay-viewer` | Visual flight replay viewer |
| [#15](https://github.com/ManpreetS2/R.E.A.C.T/pull/15) | `feature/first-llm-study` | First real-LLM study launch package |
| [#16](https://github.com/ManpreetS2/R.E.A.C.T/pull/16) | `feature/spend-ceiling-and-billing-guide` | Aggregate USD ceiling, fail-closed ledger, billing guide (CI green on 3 OSes at `0ed02c9`) |
| [#17](https://github.com/ManpreetS2/R.E.A.C.T/pull/17) | `feature/controller-instance-prompt-v3` | Prompt v3 + prompt version in experiment identity (head `82ae009`) |
| see "Latest checkpoint" below | `feature/prompt-v4-guidance-autopilot` | Missions 008-009 work in progress: prompt v4, v2 protocol, autopilot, baselines, results manifest |

PRs #3-#11 are unrelated RL research branches off `main`.

## Missions

| Mission | What | Status |
| --- | --- | --- |
| 001-005 | Offline v1, operator, replay viewer, study launch package | Done (PRs #12-#15) |
| 006 | First paid call (prompt v2). Model echoed the schema. | Done; failed as evidence. $0.00258375 |
| 006b | Spend ceiling + billing guide; Windows CI fix (unclosed SQLite handles in tests) | Done (PR #16) |
| 007 | Prompt v3: schema vs instance, example, error messages, prompt version in hash, live guard | Done, offline (PR #17); 399 tests passed at `82ae009` |
| 008 | Paid call with prompt v3: valid but copied the prompt's example; 8/8 timeouts. $0.00093225 | Done; failed as evidence |
| 009 | v2 protocol, prompt v4 (guidance-only, mechanics taught, no copyable controller), `autopilot`, scripted baselines, v2 configs | **Written, committed as a checkpoint, 425 tests pass locally, not reviewed, CI not yet run** |

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
`runs/first-llm-study/pilot-p3/` (Mission 008, includes 8 flight recordings). **They are not backed up online.**
Never modify, delete or resume them.

## Next recommended mission (do not skip the order)

1. Confirm CI on the Mission 009 PR, then review Mission 009 (autopilot, v4 prompt, v2 protocol).
2. Owner decision: approve a private backup of `runs/` (see `RESULTS.md`).
3. Free dry run: `python -m rewardbench.autopilot plan ...` and `python -m rewardbench.study rehearse` for the v4 pilot.
4. Only with written owner approval of a total USD ceiling and a maximum call count, run the v4 pilot
   (three arms, matched rounds, `runs/first-llm-study/pilot-p4`). Check the headroom rule on the revision-0 results
   before any study-tier spend.

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
