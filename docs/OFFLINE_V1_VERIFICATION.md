# Offline v1 completion audit — 2026-10-24

The completion audit below records the original local verification. The final
integration verification section records the subsequently authorized push,
draft PR, independent review and remote CI separately.

**Verdict: ready as a local offline research-infrastructure release candidate.**
No critical known defect remains in the documented ApolloLander offline workflow.
This does not validate the feedback hypothesis or establish real LLM adaptation.
No branch was pushed, no PR merged, no release published, no training run started,
and no provider request or real credential was used during this audit.

## Scope and repository reality

Inspected `README.md`, `PLAN.md`, both experiment protocols, `DEMO.md`,
`INTERFACES.md`, tests, CI, current code, fetched branches and open PRs #3–#11.
Fetched `main` was `5e624c7`: PR #2 already integrated the original offline v1.
The plan's unmerged/local-only description was stale. Work was performed on the
existing isolated branch `t3/verify-offline-v1`.

The smallest defensible v1 is the existing paired mock development → controller
freeze → demo held-out scoring → SQLite inspection → report → deterministic
flight replay pipeline. Provider wiring is tested using fake HTTP transports.
Paid studies, RL training, a model ranking, new dashboards and other environments'
frozen-evaluation support are outside this release.

## Independently verified

Clean install in a new `.venv` using Python 3.12.13 and Node v22.12.0:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,analysis,environments]"
python -m pip check
python -m pytest tests -q
node frontend/apollolander/experiment/physics.test.js
python examples/verify_offline_v1.py --out runs/offline-v1-committed
```

The requested Python and Node commands passed. The final Python run, with the
same import mode and a single quiet flag so pytest prints its count, reported
**290 passed** (`python -m pytest tests -q -o addopts='--import-mode=importlib'`).
No missing/skipped environment tests or broken installed requirements were found.
The unactivated system Python initially lacked pytest; activation of the newly
installed environment resolved that prerequisite.

The verifier runs the existing CLIs, not an alternate experiment implementation:

- Two fresh independent repetitions, each with numerical and no-feedback arms.
- Two revisions per arm, one repeated development start per revision; matching
  model settings, budgets, schema, simulator version and seeds between arms.
- A completed-run resume does not add model attempts. Held-out scoring leaves
  model-call records unchanged. Separate regression tests forbid constructing a
  model during the held-out CLI and reject general-runner held-out adaptation.
- One persisted last-valid-selected freeze per arm; eight engineering held-out
  episodes per freeze. A repeat evaluation fails closed with exit 2.
- SQLite integrity, foreign keys, attempt providers/costs, frozen hashes,
  matched starts and stored replay links checked directly.
- **41 verified replays:** 40 newly recorded development/held-out flights across
  both repetitions plus the pre-existing tracked sample.
- Six figures per report. Repeating reports on the same database produces
  identical markdown excluding the generation timestamp and byte-identical PNGs.
  Fresh repetitions produce identical controllers, rewards, states and trace
  hashes. Session ids, timings, database bytes and report provenance hashes are
  expected to differ across fresh runs.
- Generated reward figures inspected visually; long provenance legends are
  wrapped outside the data area.

Use a new output directory to repeat the verifier; it refuses to overwrite any
previous run. Full local databases, logs, reports and manifests are under
`runs/offline-v1-committed/`. `verification.json` records code identity, dirty-tree
status/diff hash, verifier hash, runtime packages and deterministic observations.
A compact tracked snapshot is in
`assets/v1-evidence/offline_v1_verification.json`; matched-panel figures have new
filenames so original engineering evidence remains intact.

## Outcomes (scripted mock, real Node simulator)

Both revisions now use development seed 5. The config lists eight available
seeds, but `episodes_per_revision: 1` intentionally selects only one for this
short infrastructure demonstration.

| Condition | Revision 0 | Revision 1 | Demo held-out mean (n=8) | Landings |
| --- | ---: | ---: | ---: | ---: |
| Numerical | -24.9176200572 | -25.6282158036 | -25.7852906940 | 0/8 |
| No feedback | -24.9176200572 | -24.9176200572 | -25.0756937877 | 0/8 |

All 16 held-out flights per repetition time out at the deliberately short
120-step cap. The numerical scripted revision worsens reward; nothing is
retuned to make it look successful. Provider cost is **$0**.

Seeds `1000000–1000007` are already exposed engineering/demo cases. The reserved
`apollolander.final_eval.v1`, seeds `2000000–2000015`, was **not executed**, its
physical states were not derived, and its outcomes were not inspected. Synthetic
report fixtures formerly using those integers now use demo seed labels.

## Repairs and reviewable commits

- `48398f2` — durable billed-failure/overrun accounting, additive `usage_json`
  migration, provider provenance through SQLite and JSONL, serialized SQLite
  schema initialization. Historical usage remains empty when unavailable.
- `c2bfb5c` — disallow held-out adaptation, match development starts across
  revisions, hash the new schedule version, reject mock/live identity mixing,
  bind evaluation to its persisted freeze/source attempt, verify actual adapter
  settings, reject invalid/error/nonfinite evaluation results, repair real
  replay links and prevent recording collisions between evaluations. Validate
  replay hashes/settings and reject nonfinite comparisons. Add regressions and
  explicit Node physics CI.
- `821dce2` — reconstruct resumed experiment trajectories and split revisions;
  retain retry latency; correct chronological success plots; separate provider,
  environment and recorded simulator settings in reports; explicitly label mocks
  and make provenance legends readable. Compatible independent replicas still
  pool together. Historical unrecorded settings remain unknown.
- `f065aed` — repeatable offline workflow verification without credentials,
  provider calls or reserved cohort access.
- Completion documentation corrects demo SQL (`parameters_json`, `seed`), stale
  plan state, legacy held-out-runner instructions, recorded artifact provenance
  and the later-study protocol. Old evidence is preserved.

## Open PR review disposition

All nine PRs remain open drafts and were linked to the audit thread. Their
existing CI checks were green when inspected; those checks do not independently
validate every experiment's scientific claims. No experimental branch was merged.

- [#3](https://github.com/ManpreetS2/R.E.A.C.T/pull/3): custom-Node PPO negative
  landing result. Its Wald intervals at 0/32 and 32/32 are degenerate and should
  not be used as valid uncertainty bounds. Separate archival review required.
- [#4](https://github.com/ManpreetS2/R.E.A.C.T/pull/4): upstream-host overnight
  negative landing result; behavioral change does not establish landing success.
- [#5](https://github.com/ManpreetS2/R.E.A.C.T/pull/5): L0 learning claim retracted;
  unmatched initialization priors and early-stop bug documented.
- [#6](https://github.com/ManpreetS2/R.E.A.C.T/pull/6): matched no-prior negative
  result; integrity fixes stay on its branch.
- [#7](https://github.com/ManpreetS2/R.E.A.C.T/pull/7): exploration diagnostics;
  a random hit is not learned landing.
- [#8](https://github.com/ManpreetS2/R.E.A.C.T/pull/8): negative genuine-learning test.
- [#9](https://github.com/ManpreetS2/R.E.A.C.T/pull/9): audited demonstration-assisted
  near-pad soft drops; maneuver milestone retracted, not normal-spawn learning.
- [#10](https://github.com/ManpreetS2/R.E.A.C.T/pull/10), tip `4774fef`: independent
  Gymnasium PPO reward-shaping showcase. Recomputed all three best-checkpoint
  mean rewards and ≥200 counts from 50 stored native-evaluation rows per arm,
  seeds `50000–50049`: A 232.3259269 (44), B 132.2315507 (10), C 222.5073583 (44).
  Native evaluator code has no training reward wrapper. These are PPO results,
  not in-context LLM evidence; score ≥200 is not a verified landing count.
  Checkpoint mtime ordering is supporting provenance, not cryptographic proof.
- [#11](https://github.com/ManpreetS2/R.E.A.C.T/pull/11), tip `750131d`: its old PR
  body is superseded by later V3–V5 reports/comments. Recomputed the stored
  V3-40k champion artifact: **53 landings, 47 timeouts on 100 `sh_contact` cases**,
  seeds `600000–600099`. This is limited short-horizon PPO evidence, not full-game
  performance or LLM adaptation. V4/V5 negatives and the unexecuted A/B/C/D
  preflight remain separate. No additional training or evaluation was launched.

This was an artifact/code-scope review of the experimental PRs; it was not an
independent re-training, full browser-parity audit or checkpoint re-evaluation.

## Remaining and next action

**Offline release blockers: none known in the verified source-checkout workflow.**
Review/integration of this local branch still requires the owner; release
publication is not authorized. New CI configuration has been checked locally,
not executed remotely from this branch.

**Research limitations/future work:** no real paired LLM result; numerical prompts
also expose outcome/state metrics, so scalar reward's independent contribution
is not identified; mock curves and older rotating-start curves are not learning
evidence; one-start/two-revision demos cannot establish adaptation statistics.
No Gymnasium frozen-scoring CLI, wheel-only Apollo resource packaging, full-game
RL solution or project-wide license is claimed by this source-checkout v1 scope.
Cost estimates cannot guarantee a vendor invoice or recover unreported usage.

The precise later study is in `FIRST_EXPERIMENT_PROTOCOL.md`. It explicitly fixes
the existing pilot templates' missing research-mode settings and distinguishes
connectivity/demo evaluation from consuming the reserved final cohort.

**Single next action:** owner review of `t3/verify-offline-v1` for integration as the
offline v1 release candidate. Paid model studies remain a separate approval gate.

## Final integration verification (2026-10-24)

Draft PR: [#12](https://github.com/ManpreetS2/R.E.A.C.T/pull/12),
`t3/verify-offline-v1` → `main`. The owner authorized pushing this branch and
opening a draft only. No merge, force-push, tag or release publication is authorized.

Before the first push, the worktree was clean at
`71f712da923ef7e0e6a3448149be2d84ed6b3378`; fetched `main` remained
`5e624c7f1032a1e33f9657ef6183efbaefaa2756`. The full 51-file diff was inspected.
Credential-signature checks found no provider/GitHub token, private-key, AWS-key
or credentialed-URL matches in changed files. No runtime databases, logs, model
checkpoints, credentials files or unrelated RL branch content were included.
The tracked package/verification snapshots and two PNG figures are intentional,
explicitly labeled offline engineering evidence; they are not model-learning data.

**Local evidence:** the preceding 290-test run, Node checks, clean editable
installation and 41 replay checks are local results, not GitHub CI results.

**Remote CI:** opening/pushing the draft triggered `analysis-checks` for both
`push` and `pull_request` at source head `71f712da923ef7e0e6a3448149be2d84ed6b3378`:
[push run](https://github.com/ManpreetS2/R.E.A.C.T/actions/runs/40140295063),
[PR run](https://github.com/ManpreetS2/R.E.A.C.T/actions/runs/40140314044).
Both runs completed successfully. The PR run's `integrated (ubuntu-latest)`,
`integrated (windows-latest)` and `integrated (macos-latest)` jobs all succeeded.
The documentation-only head `f8bff611d93e3aa61d91643fdd2989313f8ffa2d` also passed
both its [push run](https://github.com/ManpreetS2/R.E.A.C.T/actions/runs/40140386623)
and [PR run](https://github.com/ManpreetS2/R.E.A.C.T/actions/runs/40140390303)
on all three platforms. These passes apply to those exact heads, not later
review repairs. Final-head results remain separately required on the
[PR checks](https://github.com/ManpreetS2/R.E.A.C.T/pull/12/checks).

An independent read-only reviewer was assigned the entire 51-file source diff,
including experimental correctness, resume/legacy behavior, SQLite migrations
and races, freeze/isolation, replay integrity, billed failures and scientific
claims. Findings and any focused repairs will be recorded here before final
handoff; a passing test suite alone is not independent review approval.

The existing experiment is preserved. Its comparison tests **richer simulator
feedback versus no feedback**, not the isolated causal effect of scalar reward.
`FIRST_EXPERIMENT_PROTOCOL.md` now recommends a separate minimal matched-transcript
control: identical baseline controller, history and non-reward metrics in both
requests; vary only whether the true scalar reward is displayed, allow one
proposal each, freeze immediately, and score on a common engineering panel.
Independent pairs and a pre-declared analysis/budget are required for inference.
That control is documentation only; no model calls or reserved-cohort execution
were performed.

### Independent review round 1 and focused response

The reviewer covered all 51 files at `71f712d`, including both PNGs and recorded
evidence. They independently passed 290 tests, Node physics, the full two-repeat
verifier with 41 replays and a 12-connection SQLite initialization probe. They
requested changes despite the passing fresh workflow:

1. **P1, legacy restart:** adding the schedule version changed identities, allowing
   an unchanged historical config to create a new run and proposal. The repair
   checks its original canonical identity before CLI model construction and
   under the runner lock; completed/interrupted legacy runs refuse explicitly.
   No history, checkpoint, status or old experiment is rewritten. An intentionally
   renamed new study still runs.
2. **P2, report stratification:** legacy rotating and matched schedules could pool
   into a confounded estimate. Reports and JSONL now retain schedule provenance
   and separate matched-v2 from unknown historical schedules. A regression keeps
   the reproduced 0.02 versus 0.00 changes as separate one-replicate estimates.
3. **P2, billed HTTP cache usage:** a pre-existing live-use gap discarded cache
   counts on failed calls, unlike the successful-response guard. Error accounting
   now retains reported read/creation/write counts across attempts and blocks
   both internal retries and later calls when cache usage is unpriced. Mocked
   regressions cover all three fields; no real provider was contacted.

Repair commit: `ae6914b`. This adds one focused file (`providers/http.py`) to the
original review scope, bringing the overall changed-file count to 52. The fresh
paired workflow and all 41 replays still reproduce after these changes. A second
independent read-only review is checking the repairs and remaining objections;
final approval and exact-head remote CI are not inferred from these local checks.
