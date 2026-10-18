# Overnight RL status

**Branch:** `cursor/apollolander-rl-overnight-v2`  
**PR:** https://github.com/ManpreetS2/R.E.A.C.T/pull/4  
**Resources:** 4 CPU, ~15 GiB RAM, $0 · ≤30M physics frames · ≤3 trainers

## Owner direction (binding) — learning from experience

1. **Fewer, longer CONTINUOUS runs.** After random init, keep training the same
   policy (weights + optimizer + counters). Resumes marked in
   `logs/resume_events.jsonl`. No cross-run / pilot weight loading.
2. **Learning-from-experience evidence** per run: chronological crash/timeout/landing
   rates; report if failure modes decline (honest if not). See
   `logs/learning_from_experience.json` + `plots/learning_from_experience.png`.
3. **Reward-causality CONTROL:** `CTRL_zero_reward_s0` — same seed/config as Family A,
   `reward_mode: constant_zero`. Counts inside the 30M frame budget.

Obs use **fixed** `OBS_SCALE` (no running Welford stats to carry).

## Milestones

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Parity gate | **PASS** | upstream `0da09dc` |
| 2 Pilot root-cause | **DONE** | GAE trunc fix |
| 3 Throughput | **DONE** | |
| 4/5 Initial A–D | **DONE** | ~18.0M frames; 0 landings |
| 7 Held-out (phase1) | **DONE** | 0/200 on A/B/C_step/D |
| 8 Videos | **DONE** | `/opt/cursor/artifacts/rl_overnight/` |
| **Continuous continues** | **RUNNING** | A→7M, D→6M from own finals |
| **Reward causality CTRL** | **RUNNING** | zero-reward, seed 0, 3M |
| LFE analysis + report update | pending after continues | |

## Budget ledger

| Run | Frames | Mode | Landings |
| --- | ---: | --- | ---: |
| Phase-1 runs (A–D + smoke) | ~18,020,352 | completed | 0 |
| A_reproduce continuous | →7,000,000 target | resume @ 3,000,320 | TBD |
| D_curriculum continuous | →6,000,000 target | resume @ 3,000,320 | TBD |
| CTRL_zero_reward_s0 | 3,000,000 target | fresh random (control) | TBD |
| **Cap** | **30,000,000** | | |

Approx remaining before these continues: ~11.98M. Planned add ≈ 4M + 3M + 3M = 10M.

## Phase-1 learning-from-experience (honest)

| Run | Verdict |
| --- | --- |
| A | Landing did **not** rise; episode length rose (~2.0k→2.7k steps) — longer survival, **not** landing skill |
| B | Same pattern; crash→100%; longer flights |
| C_step_cost | Frozen 100% timeout entire run — **no** behavioral learning |
| D | Early 100% timeout → late mostly timeout with some crashes; **no** landings |

Failure modes did **not** decline into landings in phase 1.
