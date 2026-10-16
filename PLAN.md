# R.E.A.C.T. development plan

Last updated: 2026-10-15 (integration validation recorded)  
Current milestone: **M1 — Verified integrated offline feedback experiment** (offline suites green; YAML→adapter wiring still open)  
Maintainer: Agent 4 (Testing & Analytics). Other agents may suggest edits. **Only Agent 4 edits this file.**

Official project name: **R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing**  
GitHub: https://github.com/ManpreetS2/R.E.A.C.T  
Internal Python package: `rewardbench` (do not rename in this sprint)  
Master research plan: [Google Doc](https://docs.google.com/document/d/1fX8ReqGUKCmd_N_cwY6Fa9KfY_P5reKn6jizJcZUDQM/edit) (Section 19 approved staged design)

This is the engineering roadmap. Research protocol details live in the master plan and in `docs/`. Status below was checked against local git on **2026-10-15**, not taken from agent reports alone.

## 1. Project Vision

R.E.A.C.T. compares how GPT, Gemini, Claude, and Grok change a constrained controller when they can see objective numerical rewards and penalties. Adaptation is in-context. Model weights are not trained. A simulator, not another model, assigns the score.

Environments (scored separately; never pooled):

- Gymnasium LunarLander-v3
- ApolloLander (Seb Lee-Delisle, MIT), with its own physics and native reward
- Later (only after baseline results are independently validated): Minecraft AI Civilization

A hand-written or scripted controller is a demonstration. It is not evidence that a language model adapted.

## 2. Approved staged research design (Section 19)

Status: **approved research direction**. Sample credit prices and economy rules in the master plan are hypotheses, not implemented features.

Order of work:

1. **Prove numerical feedback vs no-feedback adaptation** (primary). Same model, schema, simulator, starts, revision count, and inference-budget ceiling. Held-out evaluation with no further learning.
2. **Then** investigate adaptive inference-resource allocation against fixed/random controls.
3. **Then** study competitive feedback (rival controllers / outcomes).
4. **Defer** the credit economy, crash-penalty shopping, parallel agents, and Minecraft until baseline experiments are independently validated.
5. Keep the **original simulator reward** separate from any proposed **100-point mission-quality index** (presentation metric only; physics decides validity).
6. **Do not purchase or use API credits** until offline tests, recording, model compatibility, and cost caps are verified.

## 3. Current repository state (15 October 2026)

### GitHub `main`

| Item | Value |
| --- | --- |
| Tip | `14061991e839409d8f0b4718eef91ed45a1116c7` |
| Remote | `origin` → `https://github.com/ManpreetS2/R.E.A.C.T.git` |
| Contents | Combined public tree: contracts, runner, Gymnasium, ApolloLander, providers, analysis, docs, frontend |

The four original workstream histories remain on GitHub as `agent/core`, `agent/lunarlander`, `agent/providers`, and `agent/analysis`. They are **already integrated onto `main`**. Claims that Agent 2 is uncommitted, that there is no remote, or that the four workstreams live only on separate branches are **obsolete**.

### Local post-`main` agent branches (not yet on `main`)

Pinned for this integration pass (exact commits; later tips are deferred):

| Agent | Branch | Pinned commit | Intent |
| --- | --- | --- | --- |
| 1 Core | `work/core-offline-loop` | `acda700` | Offline multi-revision ApolloLander reward-loop tests |
| 2 Environments | `work/environments-variation` | `c0114b67052d227cf210ca40ca546bade10d5688` | Opt-in research starts; fixed demo mode preserved |
| 3 Providers | `work/providers-preflight` | `0f234eb` | Pricing/catalog preflight, Apollo schema fixtures, readiness report |
| 4 Analytics | `work/integration-offline-v1` | *(this branch)* | PLAN, merge, validation |

Observed later tips **not** included in this first pass (integrate only after this baseline is green and the owning agent is idle):

- Agent 1 tip after pin: `79ce824` — mock-mode CLI + `metadata.adapter_kwargs` forwarding
- Agent 3 tip after pin: `5dac743` — merge of `main` into providers + further E2E work

### Worktrees

| Path | Branch |
| --- | --- |
| `~/Projects/R.E.A.C.T` | `main` |
| `~/Projects/R.E.A.C.T-worktrees/core` | `work/core-offline-loop` |
| `~/Projects/R.E.A.C.T-worktrees/environments` | `work/environments-variation` |
| `~/Projects/R.E.A.C.T-worktrees/providers` | `work/providers-preflight` |
| `~/Projects/R.E.A.C.T-worktrees/integration` | `work/integration-offline-v1` |

## 4. Architecture Overview

| Piece | Role | Location on `main` / integration |
| --- | --- | --- |
| Contracts | `ModelClient`, `EnvironmentAdapter`, logs, splits, budgets | `docs/INTERFACES.md`, `src/rewardbench/contracts.py` |
| Runner | Revisions, episodes, resume, SQLite | `src/rewardbench/core/`, `src/rewardbench/storage/` |
| Environments | Gymnasium + ApolloLander | `src/rewardbench/environments/` |
| Providers | OpenAI, Gemini, Anthropic, xAI, mock | `src/rewardbench/providers/` |
| Analysis | Session stats, charts, reports | `src/rewardbench/analysis/` |
| Frontend | ApolloLander physics + fixed-map UI | `frontend/apollolander/` |

Controller revisions and simulated episodes are different records. Development seeds and held-out seeds stay in different experiments.

## 5. Agent Ownership

| Agent | Owns | Does not edit |
| --- | --- | --- |
| 1 Core | Runner, storage, config, run CLI, `docs/INTERFACES.md` | Other agents' packages; this file |
| 2 Environments | Gymnasium and ApolloLander adapters, starts, frontend physics | Contracts unless integration requires it; this file |
| 3 Providers | Model adapters, prompts, parsing, pricing, caps | Physics and analysis; this file |
| 4 Analytics | Analysis, integration tests of logs, docs except `INTERFACES.md`, README/CI coordination, **this file**, integration merges | Substantive component bugs outside integration scope |

## 6. Milestones and exit criteria

Do **not** mark a milestone done until every exit checkbox is verified on the integration branch (or later on `main` after an approved merge). Offline/mock success is not a paid benchmark result.

### M1 — Verified integrated offline feedback experiment

**Goal:** One integration branch combines the pinned Agent 1–3 commits on top of `main` `14061991`, with green suites and a mock-model ApolloLander multi-revision loop that writes SQLite.

Exit criteria:

- [x] Integration branch `work/integration-offline-v1` exists and is based on `main` `14061991`
- [x] Pinned commits `acda700`, `c0114b6`, and `0f234eb` are contained in the integration history
- [x] `pytest` core, providers, prompts, analysis, and environments are green (**194** passed, 0 skipped, 0 failed on `9f08b71`)
- [x] Node ApolloLander `physics.test.js` is green
- [x] Mock model completes ≥2 ApolloLander revisions with real physics; numerical feedback reaches the next revision (`tests/core/test_offline_loop.py`, analysis Apollo integration)
- [x] No-feedback condition hides rewards in history while SQLite still stores them
- [x] Attempts and episodes are recorded in SQLite
- [x] Research-mode / seed-derived starts and separate development vs held-out schedules are covered by Agent 2 tests (`test_research_mode_*`, research YAML configs present)
- [x] Deterministic repeatability and budget/resume behavior remain covered
- [x] Replay/recording smoke tests pass
- [x] No paid API call was required
- [x] Results recorded in this file
- [ ] **Still open for full M1 command-path closure:** `metadata.adapter_kwargs` is **not** applied when loading research YAML without Agent 1's later `rewardbench.run` factory (`79ce824`). Adapter supports `research_mode=True`; naive `make_environment(config.environment_id)` leaves `research_mode=False`.

### M2 — Capped real-model pilot

**Goal:** One approved, cost-capped live call path for a single model/environment pair. No ranking.

Exit criteria:

- [ ] Offline M1 remains green
- [ ] Recording, model compatibility, and cost-cap reservation verified without spend, then with an explicit human-approved USD ceiling
- [ ] Live keys present only in the operator environment (never committed)
- [ ] At least one capped pilot session writes SQLite with real provider usage metadata
- [ ] No public ranking published from a single pilot

### M3 — Repeated GPT / Gemini / Claude / Grok with held-out evaluation

**Goal:** Pre-registered repeated sessions per model under numerical vs no-feedback arms; held-out evaluation with no further learning.

Exit criteria:

- [ ] Development and held-out start schedules are disjoint and enforced
- [ ] All four providers complete the protocol under the same caps
- [ ] Gymnasium and ApolloLander scores remain unpooled
- [ ] Variance / intervals reported across independent sessions

### M4 — Independent result validation, charts, and recordings

**Goal:** Logs marked `independently_validated`; charts and flight recordings tied to the same experiment IDs.

Exit criteria:

- [ ] Validation status set only after separate review of config, seeds, and raw DB
- [ ] Analysis reports and figures generated from validated logs only
- [ ] Replay/recording artifacts linked by experiment ID
- [ ] No synthetic fixture rows presented as results

### M5 — Optional resource-economy study

**Goal:** Adaptive inference-resource allocation vs fixed/random controls. **Not** the full credit economy.

Exit criteria:

- [ ] M1–M4 baseline feedback result already independently validated
- [ ] Fixed and random spend controls implemented and documented
- [ ] Credit-economy / crash-penalty shopping still deferred

### M6 — Competitive feedback and later Minecraft work

**Goal:** Competitive feedback experiments; Minecraft only after M1–M4 (and preferably M5) are settled.

Exit criteria:

- [ ] Competitive arm defined without confounding the baseline feedback claim
- [ ] Minecraft isolated as a separate experiment family
- [ ] Still no claim that in-game credits prove weight learning

## 7. Completed work (verified on GitHub `main` `14061991`)

- [x] Contract 1.0.0 and SQLite schema version 1
- [x] Experiment runner, reward history, seed split, shared spending cap, resume
- [x] Provider adapters (OpenAI, Gemini, Anthropic, xAI) + mock offline path
- [x] Gymnasium LunarLander-v3 and ApolloLander adapters on `main`
- [x] Analysis charts, session rollups, report generator; families stay separate
- [x] ApolloLander frontend + Node physics tests
- [x] Public README, CI workflow files, remote `origin` on GitHub
- [x] Prior local MacBook setup: editable install, **178** Python tests passed, Node physics passed, local HTTP game at port 8766 (Agent 4 setup report; not a paid pilot)

## 8. In progress — integration sprint

- [x] Merge pinned Agent 1–3 commits into `work/integration-offline-v1`
- [x] Re-run full suites on the combined tree
- [ ] Confirm `metadata.adapter_kwargs` / research-mode wiring end-to-end when launching from YAML — **blocked on next Agent 1 pin `79ce824`** (`src/rewardbench/run/` absent on this baseline)
- [x] Record integrated commit hash and remaining blockers here (see §15)

## 9. Blockers and risks

- **Integration risk:** Agent 3 pin `0f234eb` was built from older `agent/providers` history; merge carefully so `main`'s environments/analysis/frontend are preserved.
- **Gap:** Agent 1's post-pin CLI (`79ce824`) carries `metadata.adapter_kwargs` → adapter construction. Without it, research YAML may not reach ApolloLander research mode through the runner entrypoint even if the adapter supports the flag.
- **Gap:** Agents may keep committing on their worktrees; do not merge moving tips while they are editing.
- **Research risk:** Fixed ApolloLander demo starts are not independent generalization trials; research starts (Agent 2) must be used for held-out claims.
- **Spend risk:** No paid API call is authorized until M1 offline verification and explicit M2 cap approval.
- **Doc risk:** Mission-quality index (100-point) must never replace or be pooled with native simulator reward.

## 10. Immediate next steps

- [ ] **P0.** Agent 4: commit this PLAN update on `work/integration-offline-v1`
- [ ] **P0.** Agent 4: merge `acda700`, `c0114b6`, `0f234eb`; fix only integration conflicts
- [ ] **P0.** Agent 4: run full test matrix; record results and integrated SHA here
- [ ] **P1.** Integrate Agent 1 `79ce824` (CLI / adapter_kwargs) in a **second** pass when Agent 1 is idle
- [ ] **P1.** Integrate Agent 3 post-`0f234eb` work only after reviewing `5dac743+` and confirming the agent is idle
- [ ] **P1.** Human approval + USD cap before any live provider call
- [ ] **P2.** Do not merge this branch to `main` or push until the owner requests it

## 11. Integration and testing checklist (this sprint)

- [x] `main` contains runner, providers, environments, analysis
- [x] Mock / recorded HTTP provider tests exist (no live spend)
- [x] Combined suites green on `work/integration-offline-v1` after merges
- [x] Offline ApolloLander multi-revision numerical + no-feedback isolation
- [x] Research starts + held-out schedules (Agent 2) — via adapter kwargs / tests; not via YAML CLI yet
- [x] Recording / replay smoke
- [x] Budget / resume coverage still green
- [x] YAML → adapter research-mode path **explicitly listed as blocked** pending Agent 1 `79ce824`
- [ ] GitHub Actions not yet claimed green from this machine

## 12. Research methodology and constraints

- In-context rewards only. No weight updates.
- Gymnasium scores and ApolloLander scores are never pooled.
- Development logs are not held-out evidence.
- Do not treat a scripted or hand-tuned controller as model learning.
- Keep native simulator reward separate from any 100-point mission-quality index.
- Do not invent logs, rankings, or pilot outcomes.
- Do not call a paid API without an approved cap.
- Do not implement the credit economy in this sprint.
- Keep contract 1.0.0 stable unless Agent 1 owns a version bump.

## 13. Third-party credits

**ApolloLander was originally created by Seb Lee-Delisle (© 2017) and released under the MIT License.**

- Source: https://github.com/sebleedelisle/apollolander
- License: https://github.com/sebleedelisle/apollolander/blob/master/LICENSE
- Local: `frontend/apollolander/upstream/LICENSE`
- Upstream snapshot: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`
- Audio/font notes: `frontend/apollolander/THIRD_PARTY.md`

Gymnasium LunarLander-v3 is a separate project and a separate score.

## 14. Safely integrating the agents' NEXT round of commits

1. Freeze: confirm each agent worktree is clean and the agent is not mid-edit (`git status`, ask the human if unsure).
2. Record the new tip SHAs explicitly in this file before merging.
3. Merge one agent at a time into `work/integration-offline-v1` (or a fresh `work/integration-offline-v2` branched from the verified baseline). Prefer merge commits; never squash away agent history; never force-push agent branches.
4. Re-run the full test matrix after each merge (or after each logical group if conflicts force a combined fix).
5. If a conflict touches another agent's owned package, stop and request that agent — do not silently rewrite their design.
6. Only after green tests, update the milestone checklists in this file.
7. Push / merge to `main` only when the project owner requests it.

## 15. Integration results (Phase C / D — 15 October 2026)

### Verified baseline

| Item | Value |
| --- | --- |
| Worktree | `~/Projects/R.E.A.C.T-worktrees/integration` |
| Branch | `work/integration-offline-v1` |
| PLAN update commit | `0e6c8223958752f971f770a7d11eb2fd8df37ec0` |
| Integrated tip (post-merge) | `9f08b71a7c5ec381a510b1cf477bd800d57ab948` |
| Parent `main` | `14061991e839409d8f0b4718eef91ed45a1116c7` |
| Merged pins | `acda700` (Agent 1), `c0114b6` (Agent 2), `0f234eb` (Agent 3, includes `fb5d4ca`) |
| Not merged (next round) | Agent 1 `79ce824`; Agent 3 `5dac743` |
| Push / merge to `main` | **Not done** (owner must request) |

### Exact local test results on `9f08b71`

| Suite | Result |
| --- | --- |
| `tests/core` + `tests/providers` + `tests/prompts` + `tests/analysis` | **128 passed**, 0 skipped, 0 failed |
| `tests/environments` | **66 passed**, 0 skipped, 0 failed |
| Full `pytest tests` | **194 passed**, 0 skipped, 0 failed |
| `node frontend/apollolander/experiment/physics.test.js` | **exit 0** |
| Paid API calls | **none** |

### Gaps before a complete offline experiment from one command

1. **YAML → adapter research mode:** `examples/apollolander/research_*.yaml` store `metadata.adapter_kwargs`, but this tree has no `src/rewardbench/run/` factory/CLI. Loading the config and calling `make_environment(environment_id)` alone leaves `research_mode=False`. Manual `make_environment(..., **adapter_kwargs)` works. **Owner: Agent 1 (`79ce824`).**
2. **Single-command offline entrypoint:** no integrated `python -m rewardbench.run ... --mode mock` on this baseline.
3. **Experiment ID ↔ recording ↔ analysis:** SQLite + analysis loaders work; tying video/replay artifacts automatically to the same experiment ID through the CLI path is not closed until the run package lands.
4. **M2 blockers:** no API keys; live mode must stay disabled until human-approved USD cap; Agent 3 readiness docs exist (`docs/AGENT3_AI_INTEGRATIONS_REPORT.md`) but do not authorize spend.
5. **Credit economy:** deferred (Section 19 / M5–M6).

### Integration fixes in this pass

None required. All three pinned merges applied cleanly (ort strategy; Agent 3 `pyproject.toml` package-data line already matched `main`).

Scope changes to this plan need approval from the project owner.
