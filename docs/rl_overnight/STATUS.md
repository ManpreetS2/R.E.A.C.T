# Overnight RL status

**Branch:** `cursor/apollolander-rl-overnight-v2`  
**PR:** https://github.com/ManpreetS2/R.E.A.C.T/pull/4  
**Started from:** `cursor/apollolander-rl-pilot-2f7b` @ `efb025f`  
**Resources:** 4 CPU, ~15 GiB RAM, $0 CPU-only, ≤30M new physics frames, ≤6 h wall, ≤3 trainers

## Milestones

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Original-game backend + parity | **PASS** | Upstream hashes match `0da09dc`. Node-vm ↔ Chromium PASS. `PARITY_REPORT.md`. |
| 2 Pilot root-cause | **DONE** | `PILOT_ROOT_CAUSE.md`. GAE truncation bootstrap fixed. |
| 3 Throughput benchmark | **DONE** | Upstream ~9–12k phys frames/s; Python ~15–16k; parallel≡serial bit-identical. |
| 4/5 Experiments A–D | **RUNNING** | A + C launched; B/C-sparse next. |
| 7 Held-out eval | pending | Test seeds frozen: `1000100–1000299` |
| 8 Videos (original renderer) | pending | Artifacts → `/opt/cursor/artifacts/` |
| 9/11 Report + handoff | pending | |

## Budget ledger (physics frames)

| Run | Frames | Cumulative |
| --- | ---: | ---: |
| smoke_A | 16,384 | 16,384 |
| A_reproduce_upstream_s0 | 3,000,000 (target) | ~3.0M |
| C_timeout_eq_crash_s2 | 3,000,000 (target) | ~6.0M |
| **Cap** | | **30,000,000** |

Eval frames excluded from cap; reported separately.

## Notes

- `wip/blind-visual-local` not on remote — not used.
- Pilot `ppo_pilot_v1/` preserved.
- `frontend/apollolander/upstream/` byte-unchanged.
