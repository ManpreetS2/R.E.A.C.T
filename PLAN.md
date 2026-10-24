# R.E.A.C.T. development plan

Last updated: 2026-10-24 (independent offline v1 audit)
Current milestone: offline integration is on `main` via PR #2 at `5e624c7`.
Independent completion work is on `t3/verify-offline-v1`; see
[OFFLINE_V1_VERIFICATION.md](docs/OFFLINE_V1_VERIFICATION.md) for current checks,
repairs and release scope. Paid LLM results remain **empty / owner-gated**.
Maintainer: Agent 4 (Testing & Analytics). Other agents may suggest edits. **Only Agent 4 edits this file.**

Official project name: **R.E.A.C.T. — Reward-Enhanced Adaptive Controller Testing**  
GitHub: https://github.com/ManpreetS2/R.E.A.C.T  
Internal Python package: `rewardbench`  
Master research plan: [Google Doc](https://docs.google.com/document/d/1fX8ReqGUKCmd_N_cwY6Fa9KfY_P5reKn6jizJcZUDQM/edit) (Section 19)

## 1. Vision (unchanged)

Compare how GPT, Gemini, Claude, and Grok revise constrained controllers when numerical rewards are visible versus a matched no-feedback arm. In-context only. Simulator scores. No public ranking until independently validated.

Out of v1 scope: credit economy, competition mode, Minecraft, new dashboards.

## 2. Repository state

### GitHub `main`

| Item | Value |
| --- | --- |
| Tip | `5e624c7` (PR #2 integrated; fetched and checked 2026-10-24) |
| Remote | `origin` → `https://github.com/ManpreetS2/R.E.A.C.T.git` |

### Historical integration branch (superseded by PR #2 merge)

| Item | Value |
| --- | --- |
| Worktree | `~/Projects/R.E.A.C.T-worktrees/integration` |
| Branch | `work/integration-offline-v1` |
| Prior tip before this sprint | `2cd59377d0f1265e85d8c66604532deada726064` |
| Agent 1 held-out tip merged | `381d3d13f8259ca633820007a349e7d5963ad236` (`work/v1-heldout-evaluation`) |
| Post-merge integration | `1c1a45e72d95ff229ded7e83f5caebb85c4ff876` |
| Flagship docs tip | **`4c88f2fa234ea2a4ecbacd9fd5998947fad87740`** |
| Release-audit tip | **`89f006de563396c0e9f9f7010dbc388b24d596ed`** |
| Tests | **258** Python passed + Node physics exit 0 |
| Publish status | Historical branch merged in PR #2. Current audit changes remain local; no release published. |

## 3. Milestones

### M1 — Offline integrated experiment — **DONE**

- [x] Mock CLI, paired numerical / no-feedback configs  
- [x] Research-mode starts + flight manifests  
- [x] Development baselines 0/16 / 16/16  
- [x] Full suites green  

### M2 — Capped live pilot path — **software DONE; spend empty**

- [x] Authorized live CLI, one-call pause, continuation  
- [x] Preflight, 800-token OpenAI pilot YAML, mocked E2E  
- [ ] Owner spend approval + vendor billing limits + real key  
- [ ] First real capped SQLite session  

### M3 — Held-out evaluation — **freeze path DONE; multi-model empty**

- [x] `python -m rewardbench.heldout` freeze `last_valid_selected`  
- [x] Sealed held-out starts; no `ModelClient.propose`  
- [x] Additive SQLite tables unread by development history  
- [x] Offline tests for isolation / no prompt leak  
- [ ] Owner-approved multi-provider LLM development runs  
- [ ] Independently validated held-out comparisons  

### M4–M6

Deferred (validation, economy, competition/Minecraft).

## 4. Completed this flagship sprint

- [x] Merged Agent 1 held-out evaluator `381d3d1`  
- [x] Full suite regression: 258 passed + Node exit 0  
- [x] Documented single workflow: develop → freeze/held-out → report → replay  
- [x] Verified paired configs comparable; no-feedback hides rewards from prompts  
- [x] Professional README landing page + mermaid architecture  
- [x] Tracked evidence under `docs/assets/v1-evidence/` (scripted/preliminary only)  
- [x] `docs/DEMO.md` technical demonstration plan  
- [x] Security / attribution audit for RC  

## 5. Minimal remaining launch gates (owner)

1. Review the focused `t3/verify-offline-v1` completion changes; the earlier integration already merged in PR #2.
2. Optional: set project-wide LICENSE (do not invent one).  
3. Optional: follow `docs/PILOT_CHECKLIST.md` for one paid connectivity call.  
4. For a real paired study: `docs/FIRST_EXPERIMENT_PROTOCOL.md` + `docs/FINAL_EVALUATION_PROTOCOL.md` (cohort `2000000–2000015`; burned `1000000–1000007`).  
5. Do **not** invent LLM rankings from scripted evidence.

## 6. Integration status

The former integration push/fast-forward instructions are obsolete: PR #2 is
already merged. PRs #3–#11 are separate RL investigations and are not required
for the offline v1 release. No additional branch merge, push or release publication
is authorized by this completion audit.

## 7. Methodology constraints

- Matched development conditions before sealed held-out claims.  
- Held-out scores never enter model prompts.  
- Scripted / hand-specified ≠ LLM learning.  
- No paid API calls without explicit approval.  
- Gymnasium and ApolloLander never pooled.

## 8. Credits

**ApolloLander was originally created by Seb Lee-Delisle (© 2017) and released under the MIT License.**  
Local: `frontend/apollolander/upstream/LICENSE` · snapshot `0da09dccbadf0d6ee6efcce1f72e9ae206d341d2`.

## 9. Test matrix (flagship RC)

| Suite | Result |
| --- | --- |
| `python -m pytest tests` | **258 passed**, 0 failed, 0 skipped |
| `node frontend/apollolander/experiment/physics.test.js` | **exit 0** |
| Paid API calls | **none** |
