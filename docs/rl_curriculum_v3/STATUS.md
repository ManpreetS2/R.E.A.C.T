# Curriculum v3 STATUS

Branch: `cursor/apollolander-rl-curriculum-v3` (from `cursor/apollolander-rl-overnight-v2` @ `3e08dcb`)

| Phase | Status | Notes |
| --- | --- | --- |
| 0 Branch / scaffold | **done** | PR #4 evidence preserved |
| 1 Parity V2 | **PASS** | perfect/hard/crash/timeout TESTED-PASS |
| 2 Easy-curriculum diagnosis | **done** | random 0% all levels; D too hard + rotation rule |
| 3 Progressive PPO | **done** | 1,991,752 train frames; L0 gate pass (s13); stuck at L1 |
| 4 Final eval + report | **done** | Target-task success criterion **not** met |

## Budgets

- Training physics frames: **1,991,752 / 2,000,000**
- Diagnostic frames: parity ~37k + baselines **3,358,817** + final eval ~3.1M (baseline overshoot — see REPORT)

## Best evidence

- L0 gate-pass: `CURR_touchdown_delta_s13/checkpoints/gate_pass_L0_109128.pt`
- Videos: `/opt/cursor/artifacts/rl_curriculum_v3/gateL0_seed430011_landed.mp4`
- Full write-up: `docs/rl_curriculum_v3/REPORT.md`
