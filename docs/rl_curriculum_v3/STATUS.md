# Curriculum v3 STATUS

Branch: `cursor/apollolander-rl-curriculum-v3` (from `cursor/apollolander-rl-overnight-v2` @ `3e08dcb`)

| Phase | Status | Notes |
| --- | --- | --- |
| 0 Branch / scaffold | done | From `3e08dcb`; PR #4 evidence preserved |
| 1 Parity V2 | **PASS** | perfect/hard/crash/timeout all TESTED-PASS vs real game.js |
| 2 Easy-curriculum diagnosis | done (pending full baseline file) | random/untrained ~0% all levels |
| 3 Progressive PPO | in progress | s11 early-stop @500k (hover); s12 delta-rotation |
| 4 Final eval + report | pending | |

## Budgets

- Training physics frames: **500,736 / 2,000,000** (s11); s12 using remainder
- Diagnostic / eval frames: see `results/parity_v2_raw.json` + baseline run

## Rules in force

- No seeds `2000000–2000015`
- No paid GPU / API
- `frontend/apollolander/upstream/` byte-identical
- Guidance controller: parity/eval reference only
- Never rewrite `examples/apollolander/rl_pilot/`, `rl_overnight/`, or `docs/rl_overnight/`
