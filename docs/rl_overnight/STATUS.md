# Overnight RL status

**Branch:** `cursor/apollolander-rl-overnight-v2`  
**PR:** https://github.com/ManpreetS2/R.E.A.C.T/pull/4  
**Started from:** `cursor/apollolander-rl-pilot-2f7b` @ `efb025f`  
**Resources:** 4 CPU, ~15 GiB RAM, $0 CPU-only

## Milestones

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Original-game backend + parity | **PASS** | `PARITY_REPORT.md` |
| 2 Pilot root-cause | **DONE** | `PILOT_ROOT_CAUSE.md`; GAE trunc fix |
| 3 Throughput benchmark | **DONE** | upstream ~9–12k fps; parallel≡serial |
| 4/5 Experiments A–D | **DONE** | ~18.0M physics frames; **0 native landings** |
| 7 Held-out eval | **DONE** | Seeds `1000100–1000299`; all policies 0 land |
| 8 Videos (original renderer) | **DONE** | `/opt/cursor/artifacts/rl_overnight/*.mp4` |
| 9/11 Report + handoff | **DONE** | `OVERNIGHT_REPORT.md`, `WINDOWS_GPU_HANDOFF.md` |

## Budget ledger (physics frames)

| Run | Frames | Landings |
| --- | ---: | ---: |
| smoke_A | 16,384 | 0 |
| A_reproduce_upstream_s0 | 3,000,320 | 0 |
| B_stable_lowlr_s1 | 3,000,320 | 0 |
| C_timeout_eq_crash_s2 | 3,000,320 | 0 |
| C_sparse_s3 | 2,000,896 | 0 |
| C_step_cost_s6 | 4,001,792 | 0 |
| D_curriculum_easy_s7 | 3,000,320 | 0 |
| **Total** | **~18,020,352** | **0** |
| Cap | 30,000,000 | — |

## Held-out test (frozen seeds 1000100–1000299, n=200)

| Policy | Land (Wilson 95%) | Crash | Timeout |
| --- | --- | --- | --- |
| random open-loop | 0.000 [0, 0.019] | 0.000 | 1.000 |
| untrained net | 0.000 [0, 0.019] | 0.520 | 0.480 |
| A step0 | 0.000 [0, 0.019] | 1.000 | 0.000 |
| A final | 0.000 [0, 0.019] | 1.000 | 0.000 |
| C_step_cost final | 0.000 [0, 0.019] | 0.000 | 1.000 |
| D curriculum final | 0.000 [0, 0.019] | 1.000 | 0.000 |

**Conclusion:** No genuine learned landing on unseen starts.
