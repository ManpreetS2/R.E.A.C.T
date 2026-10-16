# R.E.A.C.T. development plan

Last updated: 2026-10-15 (final offline+live-pilot integration)  
Current milestone: **M1 complete** · **M2 software path verified offline** · first paid call **NO-GO until owner spend approval**  
Maintainer: Agent 4 (Testing & Analytics). Other agents may suggest edits. **Only Agent 4 edits this file.**

Official project name: **R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing**  
GitHub: https://github.com/ManpreetS2/R.E.A.C.T  
Internal Python package: `rewardbench` (do not rename in this sprint)  
Master research plan: [Google Doc](https://docs.google.com/document/d/1fX8ReqGUKCmd_N_cwY6Fa9KfY_P5reKn6jizJcZUDQM/edit) (Section 19 approved staged design)

This is the engineering roadmap. Research protocol details live in the master plan and in `docs/`. Status checked against local git and executed offline runs on **2026-10-15**.

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

The four original workstream histories remain on GitHub as `agent/core`, `agent/lunarlander`, `agent/providers`, and `agent/analysis`. They are **already integrated onto `main`**.

### Integration branch (final v1 tip — verified locally)

| Item | Value |
| --- | --- |
| Worktree | `~/Projects/R.E.A.C.T-worktrees/integration` |
| Branch | `work/integration-offline-v1` |
| Verified tip | **`f82a7dad985530e81e997378c0c2379fea4b0a0a`** (Agents 1–3 merges + README/PLAN) |
| Offline foundation | `11da2e17b7a26c20d300184f51056b25ae80690e` |
| PLAN sprint prep | `e0f1e83` |
| Tests at tip | **250** Python passed + Node physics exit 0 |
| Status | Local only — **not pushed / not merged to `main`** |

### Merged agent tips (contained in integration history)

| Agent | Branch | Tip | Contribution |
| --- | --- | --- | --- |
| 1 Core | `work/v1-live-cli` | `28497b5` | Live CLI, explicit auth, one-call pause, continuation |
| 2 Environments | `work/v1-research-validity` | `7618ee9` | Research-mode development baselines, guidance 16/16 |
| 3 Providers | `work/v1-provider-safety` | `7f599b6` | Prompt v2, pricing preflight, truncation, 800-token pilot |

Agent branches were **not** reset, force-pushed, overwritten, or deleted.

### Worktrees

| Path | Branch |
| --- | --- |
| `~/Projects/R.E.A.C.T` | `main` @ `14061991` (= `origin/main`) |
| `~/Projects/R.E.A.C.T-worktrees/integration` | `work/integration-offline-v1` |
| `~/Projects/R.E.A.C.T-worktrees/live-core` | `work/v1-live-cli` @ `28497b5` |
| `~/Projects/R.E.A.C.T-worktrees/research-env` | `work/v1-research-validity` @ `7618ee9` |
| `~/Projects/R.E.A.C.T-worktrees/provider-safety` | `work/v1-provider-safety` @ `7f599b6` |

## 4. Architecture Overview

| Piece | Role | Location |
| --- | --- | --- |
| Contracts | `ModelClient`, `EnvironmentAdapter`, logs, splits, budgets | `docs/INTERFACES.md`, `src/rewardbench/contracts.py` |
| Runner | Revisions, episodes, resume, SQLite | `src/rewardbench/core/`, `src/rewardbench/storage/` |
| Offline CLI | `python -m rewardbench.run --mode mock` | `src/rewardbench/run/` |
| Live CLI | `--mode live --i-authorize-paid-api-calls` (+ optional continuation) | `src/rewardbench/run/cli.py`, `live.py` |
| Environments | Gymnasium + ApolloLander (+ research starts, flight records) | `src/rewardbench/environments/` |
| Providers | OpenAI, Gemini, Anthropic, xAI, mock + preflight | `src/rewardbench/providers/` |
| Analysis | Session stats, charts, reports | `src/rewardbench/analysis/` |
| Frontend | ApolloLander physics + fixed-map UI | `frontend/apollolander/` |

Controller revisions and simulated episodes are different records. Development seeds and held-out seeds stay in different experiments (`SplitGuard`).

## 5. Agent Ownership

| Agent | Owns | Does not edit |
| --- | --- | --- |
| 1 Core | Runner, storage, config, run CLI, `docs/INTERFACES.md` | Other agents' packages; this file |
| 2 Environments | Gymnasium and ApolloLander adapters, starts, flight records, frontend physics | Contracts unless integration requires it; this file |
| 3 Providers | Model adapters, prompts, parsing, pricing, caps | Physics and analysis; this file |
| 4 Analytics | Analysis, integration validation, docs except `INTERFACES.md`, README/CI coordination, **this file**, integration merges | Substantive redesign outside integration scope |

## 6. Milestones and exit criteria

### M1 — Verified integrated offline feedback experiment

**Goal:** Combined tree with green suites and a mock-model ApolloLander multi-revision loop that writes SQLite, with research-mode starts and auditable flight manifests.

Exit criteria:

- [x] Integration branch based on `main` `14061991`
- [x] Offline agent tips `79ce824`, `4f245f6`, `cc42041` contained in history
- [x] Live-pilot tips `28497b5`, `7618ee9`, `7f599b6` contained in history
- [x] Full `pytest tests` green (**250 passed**, 0 skipped, 0 failed)
- [x] Node ApolloLander `physics.test.js` green
- [x] CLI mock numerical + no-feedback paired runs complete
- [x] Research-mode development baselines: random/coast/hover **0/16** landings; hand-specified guidance **16/16**
- [x] `metadata.adapter_kwargs.research_mode` reaches the adapter (fail-closed if unsupported)
- [x] Flight manifests (`.flight.json`) with replay verification
- [x] No paid API call required
- [ ] Owner approval to merge/push to `main`

### M2 — Capped real-model pilot

**Goal:** One approved, cost-capped live call path. No ranking.

Exit criteria:

- [x] CLI `--mode live` with `--i-authorize-paid-api-calls` (fail-closed without flag)
- [x] Session gate: at most one **new** paid `propose` per CLI invocation; pause ≠ completed
- [x] Continuation flag required when selected attempts already exist
- [x] Preflight: credentials, priced model, budget, retries=0, schema, output ceiling
- [x] Pilot YAML: OpenAI `gpt-5.4-mini`, `max_output_tokens: 800`, `reasoning_effort: none`, `max_model_retries: 0`, `max_cost_usd: 0.05`
- [x] OpenAI request body transmits `max_completion_tokens=800` and `reasoning_effort=none` (mocked transport tests)
- [x] Software budget wired from YAML (in-process only — **not** a vendor billing guarantee)
- [ ] Explicit human approval + USD ceiling + vendor account billing limits
- [ ] Keys only in operator shell env (never commit)
- [ ] At least one capped pilot SQLite session on a real key
- [ ] No public ranking from a single pilot

**Ambiguous-resume risk (documented):** If a process crashes after the provider accepts a paid request but before the selected attempt is persisted, resume cannot prove whether the call already billed. Software cannot guarantee exactly-once billing across that window. On ambiguous resume, **stop and require manual SQLite / provider-dashboard review** before re-authorizing continuation. Do not blindly re-run.

### M3 — Repeated GPT / Gemini / Claude / Grok with held-out evaluation

**Research blocker (explicit):** Average reward change across different research starts does **not**, by itself, prove controller improvement. The study design must (1) evaluate successive controller revisions on **matched development conditions**, then (2) test **final policies** on a **sealed held-out set** with no further learning.

What exists today:

- [x] Disjoint `development_seeds` / `held_out_seeds` in configs
- [x] `SplitGuard` refuses cross-split seed use in a single experiment
- [x] Separate held-out experiment configs (analysis/diagnostics flag development seeds appearing in held-out pools)
- [x] Development baselines never consumed held-out starts

What is **missing** (do not consume held-out during tuning):

- [ ] Automated “freeze final selected controller → evaluate on sealed held-out without another model `propose`” CLI/workflow
- [ ] Documented operator checklist that held-out remains untouched until final freeze

Until that freeze-and-held-out-eval path is wired and offline-tested, treat M3 held-out claims as **blocked**. Do not invent rankings from development-only logs.

### M4 — Independent result validation, charts, and recordings

Not started (offline artifacts are **preliminary** infrastructure logs only).

### M5 — Optional resource-economy study

Deferred until M1–M4 baseline feedback is independently validated.

### M6 — Competitive feedback and later Minecraft work

Deferred.

## 7. Completed work

### On GitHub `main` `14061991`

- [x] Contract 1.0.0, SQLite schema 1, runner, providers, environments, analysis, frontend

### On `work/integration-offline-v1` (2026-10-15)

- [x] Offline CLI `python -m rewardbench.run --mode mock`
- [x] Paired Apollo offline configs (numerical / no-feedback)
- [x] Research-mode starts + fail-closed adapter kwargs
- [x] Flight manifests with deterministic replay verification
- [x] Mocked provider → runner → Apollo physics → SQLite E2E tests
- [x] Authorized live CLI + SessionPaidCallGate + continuation
- [x] Provider preflight, truncation detection, prompt v2
- [x] Research development baselines (scripted — **not** LLM learning)
- [x] Integrated pilot YAML `configs/apollolander_pilot_openai_gpt54mini.yaml` (+ nofeedback twin)
- [x] README documents install, tests, offline twins, reports, replay, dry-run, live requirements

## 8. Offline v1 execution record (scripted mock)

**Label:** offline scripted mock — infrastructure verification. **Not** an AI research finding.

| Field | Numerical | No-feedback |
| --- | --- | --- |
| Experiment ID | `exp_f6d8e0091e67a46641f0` | `exp_3fcd0197614c53ce8d67` |
| Status | completed | completed |
| Revisions | 2 | 2 |
| Selected controllers | thrust 0/−90 → 1.0/0 | thrust 0/−90 → 0/−90 (unchanged) |
| Research mode | true | true |
| Start schedule | `apollolander.starts.v1` | `apollolander.starts.v1` |

### Research development baselines (Agent 2; held-out unused)

| Baseline | Landings / 16 |
| --- | ---: |
| random_seed0 | **0/16** |
| constant_coast | **0/16** |
| constant_hover_upright | **0/16** |
| hand_specified_guidance | **16/16** |

Source: `examples/apollolander/research_development_baseline/DEVELOPMENT_BASELINE_REPORT.md`

## 9. Integration fixes applied by Agent 4

1. **Fail-closed adapter kwargs** (earlier offline sprint).
2. **CLI research/flight linkage** without changing hashed experiment id.
3. **Flight JSON without HD video** by default.
4. **Pilot YAML merge conflict** (Agent 1 × Agent 3): keep `num_revisions: 2` + one-call pause/continuation; set `max_output_tokens: 800`, `reasoning_effort: none`, `max_model_retries: 0`, `max_cost_usd: 0.05`.
5. README + PLAN updates for verified live-pilot soft path and held-out eval blocker.

## 10. Blockers for the first tiny paid pilot (M2)

**Software path: ready (mocked).** **Spend: NO-GO until owner approval.**

Remaining human gates:

- [ ] Explicit owner approval to spend (USD ceiling)
- [ ] Vendor account billing limits set by the human
- [ ] `export OPENAI_API_KEY=...` in local shell only — never commit
- [ ] Run exactly one authorized invocation; review SQLite before continuation
- [ ] On any ambiguous interrupted outcome, manual review before retry
- [ ] No ranking / no publication from the pilot

Provider E2E with **mocked HTTP** through real Apollo physics is green. That does **not** authorize spend.

## 11. Immediate next steps

- [x] Agents 1–3 complete live-pilot work on `work/v1-*` branches (no paid calls)
- [x] Agent 4 integrates tips into `work/integration-offline-v1`, re-runs full suites, updates this file
- [ ] **Owner:** review integration tip; approve merge/push only explicitly
- [ ] **Owner:** if approving a pilot, set billing limits and authorize a USD ceiling
- [ ] Agent 4 (later sprint): narrow freeze → sealed held-out eval CLI for M3
- [ ] **Do not** start credit economy or Minecraft

## 11b. Safe integration → `main` checklist (owner gate)

Do **not** merge or push until the owner explicitly approves.

Pre-flight (checked 2026-10-15):

- [x] `origin/main` == local `main` == `14061991`
- [x] `origin/main` is an ancestor of the integration tip (fast-forward possible from main’s POV once pushed/merged)
- [x] Live-pilot agent branches merged; full suite green (250 passed + Node exit 0)
- [x] PLAN.md / README updated for final SHAs and pilot config
- [ ] Owner names the exact ref to push (integration branch and/or PR into `main`)
- [ ] No force-push; no rewrite of published history; no credentials in the tree

### Exact commands after owner approval (DO NOT RUN without approval)

```bash
# From the integration worktree, after owner names this tip:
cd ~/Projects/R.E.A.C.T-worktrees/integration
git push -u origin work/integration-offline-v1

# Option A — merge locally into main (owner-approved):
cd ~/Projects/R.E.A.C.T
git checkout main
git pull --ff-only origin main
git merge --ff-only work/integration-offline-v1
git push origin main

# Option B — GitHub PR:
# gh pr create --base main --head work/integration-offline-v1 \
#   --title "Integrate offline v1 + authorized live-pilot path" \
#   --body "..."
```

## 12. Safely integrating later agent commits

1. Confirm agent worktrees clean/idle.
2. Record tip SHAs here before merging.
3. Merge one agent at a time into this branch.
4. Re-run full pytest + Node physics + offline CLI paired smoke.
5. Update this file only after green results.
6. Push/merge to `main` only when the owner requests it.

## 13. Research methodology and constraints

- In-context rewards only. No weight updates.
- Gymnasium and ApolloLander scores never pooled.
- Development logs are not held-out evidence.
- Scripted/mock / hand-specified controllers are infrastructure or difficulty baselines, not model learning.
- Native simulator reward stays separate from any 100-point mission-quality index.
- Do not invent rankings or pilot outcomes.
- Do not call a paid API without an approved cap.
- Do not implement the credit economy in this sprint.
- Matched development comparison + sealed held-out final eval are required before claiming adaptation success.

## 14. Third-party credits

**ApolloLander was originally created by Seb Lee-Delisle (© 2017) and released under the MIT License.**

- Source: https://github.com/sebleedelisle/apollolander
- Local: `frontend/apollolander/upstream/LICENSE`
- Upstream snapshot: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`

## 15. Test matrix (final integration tip)

| Suite | Result |
| --- | --- |
| `python -m pytest tests -q` | **250 passed**, 0 skipped, 0 failed |
| `node frontend/apollolander/experiment/physics.test.js` | **exit 0** |
| Paid API calls | **none** |

Scope changes to this plan need approval from the project owner.
