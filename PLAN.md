# R.E.A.C.T. development plan

Last updated: 2026-10-15 (live-pilot worktrees prepared from offline v1)  
Current milestone: **M1 done locally** → preparing **M2 live-pilot sprint** (no spend yet; no merge/push without owner approval)  
Maintainer: Agent 4 (Testing & Analytics). Other agents may suggest edits. **Only Agent 4 edits this file.**

Official project name: **R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing**  
GitHub: https://github.com/ManpreetS2/R.E.A.C.T  
Internal Python package: `rewardbench` (do not rename in this sprint)  
Master research plan: [Google Doc](https://docs.google.com/document/d/1fX8ReqGUKCmd_N_cwY6Fa9KfY_P5reKn6jizJcZUDQM/edit) (Section 19 approved staged design)

This is the engineering roadmap. Research protocol details live in the master plan and in `docs/`. Status below was checked against local git and executed offline runs on **2026-10-15**.

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

### Integration branch (offline v1 — verified)

| Item | Value |
| --- | --- |
| Worktree | `~/Projects/R.E.A.C.T-worktrees/integration` |
| Branch | `work/integration-offline-v1` |
| Verified tip | **`11da2e17b7a26c20d300184f51056b25ae80690e`** |
| Tests at tip | **221** Python passed + Node physics exit 0 |
| Status | Local only — **not pushed / not merged to `main`** |

### Live-pilot sprint worktrees (branched from `11da2e1`)

| Agent | Path | Branch | Base |
| --- | --- | --- | --- |
| 1 Core | `~/Projects/R.E.A.C.T-worktrees/live-core` | `work/v1-live-cli` | exact `11da2e1` |
| 2 Environments | `~/Projects/R.E.A.C.T-worktrees/research-env` | `work/v1-research-validity` | exact `11da2e1` |
| 3 Providers | `~/Projects/R.E.A.C.T-worktrees/provider-safety` | `work/v1-provider-safety` | exact `11da2e1` |

Older offline-agent worktrees were **preserved** (moved, not deleted):

| Path | Branch / state |
| --- | --- |
| `…/core-offline-loop` | `work/core-offline-loop` @ `79ce824` |
| `…/environments-variation` | `work/environments-variation` @ `4f245f6` |
| `…/providers-preflight` | `work/providers-preflight` @ `cc42041` |
| `…/core`, `…/environments`, `…/providers` | detached tips of the same offline commits |

### Worktrees (full map)

| Path | Branch |
| --- | --- |
| `~/Projects/R.E.A.C.T` | `main` @ `14061991` (= `origin/main`) |
| `~/Projects/R.E.A.C.T-worktrees/integration` | `work/integration-offline-v1` @ `11da2e1` |
| `~/Projects/R.E.A.C.T-worktrees/live-core` | `work/v1-live-cli` |
| `~/Projects/R.E.A.C.T-worktrees/research-env` | `work/v1-research-validity` |
| `~/Projects/R.E.A.C.T-worktrees/provider-safety` | `work/v1-provider-safety` |

## 4. Architecture Overview

| Piece | Role | Location |
| --- | --- | --- |
| Contracts | `ModelClient`, `EnvironmentAdapter`, logs, splits, budgets | `docs/INTERFACES.md`, `src/rewardbench/contracts.py` |
| Runner | Revisions, episodes, resume, SQLite | `src/rewardbench/core/`, `src/rewardbench/storage/` |
| Offline CLI | `python -m rewardbench.run --mode mock` | `src/rewardbench/run/` |
| Environments | Gymnasium + ApolloLander (+ research starts, flight records) | `src/rewardbench/environments/` |
| Providers | OpenAI, Gemini, Anthropic, xAI, mock | `src/rewardbench/providers/` |
| Analysis | Session stats, charts, reports | `src/rewardbench/analysis/` |
| Frontend | ApolloLander physics + fixed-map UI | `frontend/apollolander/` |

Controller revisions and simulated episodes are different records. Development seeds and held-out seeds stay in different experiments.

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
- [x] Agent tips `79ce824`, `4f245f6`, `cc42041` contained in history
- [x] Full `pytest tests` green (**221 passed**, 0 skipped, 0 failed)
- [x] Node ApolloLander `physics.test.js` green
- [x] CLI mock numerical + no-feedback paired runs complete
- [x] `metadata.adapter_kwargs.research_mode` reaches the adapter (fail-closed if unsupported)
- [x] Research starts vary by seed; matching seeds match across conditions; schedules disjoint
- [x] Scripted model revises under numerical feedback; stays put under no-feedback
- [x] SQLite attempts/episodes recorded; analysis report generated
- [x] Flight manifests (`.flight.json`) linked to experiment id / revision / episode / seed; replay verified
- [x] No paid API call required
- [ ] Owner approval to merge/push to `main`

### M2 — Capped real-model pilot

**Goal:** One approved, cost-capped live call path. No ranking.

Exit criteria:

- [ ] Explicit human approval + USD ceiling
- [ ] CLI `--mode live` implemented with opt-in (currently **disabled** / fail-closed)
- [ ] Keys only in operator shell env
- [ ] Known pricing + reservation/settlement
- [ ] At least one capped pilot SQLite session
- [ ] No public ranking from a single pilot

### M3 — Repeated GPT / Gemini / Claude / Grok with held-out evaluation

Not started.

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
- [x] Pilot YAML draft `configs/apollolander_pilot_openai_gpt54mini.yaml` (**documentation only**)
- [x] Executed local offline infrastructure experiments (scripted mock — **not LLM learning**)

## 8. Offline v1 execution record (scripted mock)

**Label:** offline scripted mock — infrastructure verification. **Not** an AI research finding.

Commands:

```bash
python -m rewardbench.run --config configs/apollolander_offline_development_numerical.yaml --mode mock --database runs/offline_v1/numerical.sqlite
python -m rewardbench.run --config configs/apollolander_offline_development_nofeedback.yaml --mode mock --database runs/offline_v1/nofeedback.sqlite
python -m rewardbench.analysis report --logs runs/offline_v1/numerical.sqlite --out reports/offline_v1/numerical
python -m rewardbench.analysis report --logs runs/offline_v1/nofeedback.sqlite --out reports/offline_v1/nofeedback
```

| Field | Numerical | No-feedback |
| --- | --- | --- |
| Experiment ID | `exp_f6d8e0091e67a46641f0` | `exp_3fcd0197614c53ce8d67` |
| Status | completed | completed |
| Revisions | 2 | 2 |
| Episodes | 2 | 2 |
| Selected controllers | thrust 0/−90 → 1.0/0 | thrust 0/−90 → 0/−90 (unchanged) |
| Rewards by revision | −24.9176, −25.9016 | −24.9176, −25.1920 |
| Research mode | true (adapter confirmed) | true |
| Start schedule | `apollolander.starts.v1` | `apollolander.starts.v1` |
| Seed 5 start_x (rev0) | 6873.194… | 6873.194… (identical) |
| Seed 2 start_x (rev1) | 6757.522… | 6757.522… (identical; ≠ seed 5) |
| Flight manifests | `runs/offline_v1/flights/<exp_id>/*.flight.json` | same pattern |
| Report | `reports/offline_v1/numerical/report.md` | `reports/offline_v1/nofeedback/report.md` |

Demonstration flight manifests (hand-specified / deterministic mock; replay matched):

| Flight | Origin | Outcome | Reward |
| --- | --- | --- | --- |
| constant-coast | `hand_specified_demonstration` | crashed | −98.8164 |
| hand-specified-guidance | `hand_specified_demonstration` | landed | +83.4238 |
| research-mock seed 9 | `deterministic_mock` | timeout (short cap) | −24.8291 |

Paths under `examples/apollolander/output/offline_v1/` (gitignored).

## 9. Integration fixes applied by Agent 4

1. **Fail-closed adapter kwargs** in `rewardbench.run.factory` — unsupported `metadata.adapter_kwargs` raise `ConfigError` (no silent fixed-start downgrade).
2. **CLI research/flight linkage** — runtime `adapter_overrides` stamp `experiment_id` and optional `record_dir` without changing the hashed experiment id; `mappingproxy` metadata handled.
3. **Flight JSON without HD video** — `.flight.json` written whenever `record_dir` is set; video remains opt-in.
4. **Flight provenance fields** — optional `experiment_id` / `episode_index` on manifests.
5. Offline configs enable `record_flights` + explicit schedule kwargs.
6. Ignore generated `reports/`.

## 10. Blockers for the first tiny paid pilot (M2)

**Verdict: NO-GO until the checklist below is green and the owner approves spend.**

- [ ] Implement CLI `--mode live` (currently refuses with ConfigError; no network)
- [ ] Wire `build_model_client(..., max_spend_usd=..., max_retries=...)` from YAML budget
- [ ] Require explicit opt-in flag (e.g. `--i-approve-spend`) in addition to `--mode live`
- [ ] Confirm `OPENAI_API_KEY` (or other) present in shell only — never commit
- [ ] Confirm provider account billing limits set by the human
- [ ] Use pilot YAML ceiling (`max_cost_usd: 0.05`, `max_model_calls: 2`) or tighter
- [ ] Research-mode + flight recording on for the pilot path
- [ ] Abort after first revision for human SQLite review before second call
- [ ] No ranking / no publication from the pilot

Provider E2E with **mocked HTTP** through real Apollo physics is green. That does **not** authorize spend.

## 11. Immediate next steps

- [ ] Agents 1–3 complete live-pilot work on `work/v1-*` branches (no paid calls)
- [ ] Agent 4 integrates their tips into `work/integration-offline-v1` (or a new integration tip), re-runs full suites, updates this file
- [ ] **Owner:** review offline v1 / live-pilot readiness; approve merge/push only explicitly
- [ ] **Owner:** if approving a pilot, set billing limits and authorize a USD ceiling
- [ ] **Do not** start credit economy or Minecraft

## 11b. Safe integration → `main` checklist (owner gate)

Do **not** merge or push until the owner explicitly approves.

Pre-flight (checked 2026-10-15):

- [x] `origin/main` == local `main` == `14061991` (no unexpected remote changes after `git fetch`)
- [x] `origin/main` is an ancestor of integration tip `11da2e1` (fast-forward possible from main’s POV once integration is pushed/merged)
- [x] Integration is **18 commits** ahead of `origin/main` (11 non-merge + 7 merges); **34 files** changed vs `origin/main...11da2e1`
- [x] Offline suites at `11da2e1`: 221 passed + Node physics exit 0
- [ ] Live-pilot agent branches finished and re-integrated; full suite re-run on the combined tip
- [ ] PLAN.md milestone checklists updated with final SHAs
- [ ] Owner names the exact ref to push (integration branch and/or PR into `main`)
- [ ] No force-push; no rewrite of published history; no credentials in the tree

What a push of `11da2e1` (or a later integration tip based on it) would include: offline CLI, research starts, flight manifests, provider E2E/pilot docs, PLAN updates, and related tests — **not** live API spend, **not** credit economy.

## 12. Safely integrating later agent commits

1. Confirm agent worktrees clean/idle.
2. Record tip SHAs here before merging.
3. Merge one agent at a time into this branch (or a new `work/integration-offline-v2`).
4. Re-run full pytest + Node physics + offline CLI paired smoke.
5. Update this file only after green results.
6. Push/merge to `main` only when the owner requests it.

## 13. Research methodology and constraints

- In-context rewards only. No weight updates.
- Gymnasium and ApolloLander scores never pooled.
- Development logs are not held-out evidence.
- Scripted/mock controllers are infrastructure tests, not model learning.
- Native simulator reward stays separate from any 100-point mission-quality index.
- Do not invent rankings or pilot outcomes.
- Do not call a paid API without an approved cap.
- Do not implement the credit economy in this sprint.

## 14. Third-party credits

**ApolloLander was originally created by Seb Lee-Delisle (© 2017) and released under the MIT License.**

- Source: https://github.com/sebleedelisle/apollolander
- Local: `frontend/apollolander/upstream/LICENSE`
- Upstream snapshot: `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`

## 15. Test matrix (offline v1 tip before final PLAN commit)

| Suite | Result |
| --- | --- |
| `python -m pytest tests -q` | **221 passed**, 0 skipped, 0 failed |
| `node frontend/apollolander/experiment/physics.test.js` | **exit 0** |
| Paid API calls | **none** |

Scope changes to this plan need approval from the project owner.
