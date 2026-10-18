# Curriculum v3 STATUS

Branch: `cursor/apollolander-rl-curriculum-v3` (from `cursor/apollolander-rl-overnight-v2` @ `3e08dcb`)

| Phase | Status | Notes |
| --- | --- | --- |
| 0 Branch / scaffold | done | From `3e08dcb`; PR #4 evidence preserved |
| 1 Parity V2 | **PASS** | perfect/hard/crash/timeout all TESTED-PASS vs real game.js |
| 2 Easy-curriculum diagnosis | in progress | |
| 3 Progressive PPO | pending | Budget ≤ 2,000,000 train frames |
| 4 Final eval + report | pending | |

## Budgets

- Training physics frames: **0 / 2,000,000**
- Diagnostic / eval frames: see `results/parity_v2_raw.json` + baseline run

## Rules in force

- No seeds `2000000–2000015`
- No paid GPU / API
- `frontend/apollolander/upstream/` byte-identical
- Guidance controller: parity/eval reference only
- Never rewrite `examples/apollolander/rl_pilot/`, `rl_overnight/`, or `docs/rl_overnight/`
