# Overnight RL status

**Branch:** `cursor/apollolander-rl-overnight-v2`  
**PR:** https://github.com/ManpreetS2/R.E.A.C.T/pull/4  
**Final focus:** continuous resumes + reward causality (owner direction)

## Owner direction (binding) — status

| Requirement | Status |
| --- | --- |
| Fewer, longer CONTINUOUS runs (resume full state) | **DONE** — A 3M→7M, D 3M→6M; `resume_events.jsonl` |
| No cross-run / pilot weight loading | **DONE** — each run’s own step0 random only |
| Chronological crash/timeout/landing + failure-mode report | **DONE** — LFE JSON/plots; honest: modes did not become landings |
| Reward-causality control within 30M | **DONE** — `CTRL_zero_reward_s0` (constant zero, seed 0) |

## Budget

| Item | Frames |
| --- | ---: |
| Phase-1 family runs + smoke | ~18,020,352 |
| A continuous extension | +4,000,000 (total 7,000,064) |
| D continuous extension | +3,000,000 (total 6,000,640) |
| CTRL zero-reward | 3,000,320 |
| **Total used** | **~28,020,736** |
| Cap / remaining | 30,000,000 / ~1.98M (stopped; more training adds little) |

## Learning-from-experience (honest)

- **A continuous:** crash 0.99→0.72 late, timeout↑, mean steps 1.6k→4.2k; **0 landings**; pad distance did not improve.
- **D continuous:** more timeouts late; **0 landings**.
- **CTRL zero-reward:** different trajectory than A (timeout→crash mix); **0 landings**.
- **Causality:** reward changes behavior ≠ reward teaches landing. See `results/causality_comparison.json`.

## Milestones

| Phase | Status |
| --- | --- |
| Parity / root-cause / throughput | DONE |
| Families A–D initial | DONE (0 land) |
| Held-out phase-1 | DONE (0/200) |
| Videos (original renderer) | DONE |
| Continuous A/D + CTRL | DONE |
| LFE + causality in report | DONE — `OVERNIGHT_REPORT.md` |
