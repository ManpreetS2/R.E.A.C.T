# Curriculum v3 STATUS

Branch: `cursor/apollolander-rl-curriculum-v3` (from `cursor/apollolander-rl-overnight-v2` @ `3e08dcb`)

| Phase | Status | Notes |
| --- | --- | --- |
| 0 Branch / scaffold | **done** | PR #4 evidence preserved |
| 1 Parity V2 | **PASS** | perfect/hard/crash/timeout TESTED-PASS |
| 2 Easy-curriculum diagnosis | **done** | random 0% all levels; D too hard + rotation rule |
| 3 Progressive PPO | **done (negative result)** | 1,991,752 train frames; s13 L0 learning check **FAILED**; gate 40/40 is prior-contaminated / not learning evidence; early-stop bug after L0 advance |
| 4 Final eval + report | **done** | Target-task success criterion **not** met |
| Audit | **done** | `AUDIT.md` — claims aligned to logs; no further training |

## Budgets

- Training physics frames: **1,991,752 / 2,000,000** (s13 continued after failed check — should have stopped)
- Diagnostic frames: **~6.9M** (baselines 3,358,817 + final eval 3,201,575 + gates/parity) — overshot ~1M target

## Best evidence (for the negative result)

- Failed L0 check: `CURR_touchdown_delta_s13/logs/l0_learning_check.json`
- Audit: `docs/rl_curriculum_v3/AUDIT.md`
- Full write-up: `docs/rl_curriculum_v3/REPORT.md`
