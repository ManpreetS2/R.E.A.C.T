# R.E.A.C.T. development plan

Last updated: 2026-10-15 (flagship v1 release candidate)  
Current milestone: **M1 complete** · **held-out freeze path merged** · **release candidate ready** · paid LLM runs **empty / owner-gated**  
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
| Tip | `14061991e839409d8f0b4718eef91ed45a1116c7` |
| Remote | `origin` → `https://github.com/ManpreetS2/R.E.A.C.T.git` |

### Integration branch (flagship RC)

| Item | Value |
| --- | --- |
| Worktree | `~/Projects/R.E.A.C.T-worktrees/integration` |
| Branch | `work/integration-offline-v1` |
| Prior tip before this sprint | `2cd59377d0f1265e85d8c66604532deada726064` |
| Agent 1 held-out tip merged | `381d3d13f8259ca633820007a349e7d5963ad236` (`work/v1-heldout-evaluation`) |
| Post-merge integration | `1c1a45e72d95ff229ded7e83f5caebb85c4ff876` |
| Flagship docs tip | **`4c88f2fa234ea2a4ecbacd9fd5998947fad87740`** |
| Tests | **258** Python passed + Node physics exit 0 |
| Publish status | Local only — **not pushed / not merged** without owner approval |

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

1. Approve merge/push of integration tip to GitHub (`main` or PR).  
2. Optional: set project-wide LICENSE.  
3. Optional: approve first `$0.05` software-capped live pilot (separate from publish).  
4. Do **not** invent LLM rankings from scripted evidence.

## 6. Safe publish commands (DO NOT RUN without approval)

```bash
cd ~/Projects/R.E.A.C.T-worktrees/integration
git push -u origin work/integration-offline-v1

# Fast-forward main (owner-approved):
cd ~/Projects/R.E.A.C.T
git checkout main
git pull --ff-only origin main
git merge --ff-only work/integration-offline-v1
git push origin main
```

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
