# Overnight RL status

**Branch:** `cursor/apollolander-rl-overnight-v2`  
**Started from:** `cursor/apollolander-rl-pilot-2f7b` @ `efb025f`  
**Resources:** 4 CPU, ~15 GiB RAM, $0 CPU-only, ≤30M new physics frames, ≤6 h wall, ≤3 trainers

## Milestones

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Original-game backend + parity | **PASS** | Upstream hashes match `0da09dc`. Node-vm host ↔ Chromium bridge PASS. See `PARITY_REPORT.md`. |
| 2 Pilot root-cause | **DONE** | See `PILOT_ROOT_CAUSE.md`. Fixed GAE truncation bootstrap + logging. |
| 3 Throughput benchmark | in progress | |
| 4/5 Experiments A–D | pending | |
| 7 Held-out eval | pending | Test seeds reserved: 1000100–1000299 |
| 8 Videos (original renderer) | pending | Artifacts → `/opt/cursor/artifacts/` |
| 9/11 Report + handoff | pending | |

## Budget ledger (physics frames)

| Run | Frames used | Cumulative |
| --- | ---: | ---: |
| (none yet) | 0 | 0 |

**Cap:** 30,000,000 (eval frames excluded, reported separately)

## Notes

- `wip/blind-visual-local` is **not** on the remote; not used.
- Pilot results under `examples/apollolander/rl_pilot/results/ppo_pilot_v1/` preserved untouched.
- `frontend/apollolander/upstream/` unchanged (byte-identical to Seb Lee-Delisle MIT sources).
