# Final release verification (Phase 4)

Audit date: 2026-10-19. No additional training was run for this audit.

## 1. Metrics recomputed from eval JSON

All `outputs/phase4/eval_{A,B,C}_best.json` values for mean / median / std / CI95 / ≥200 / mean steps / timeouts / ≥800 steps were recomputed from `episodes_detail` and **matched exactly**.

| | Mean | ≥200 | Mean steps | ≥800 | Timeouts | land_heuristic |
|--|-----:|-----:|-----------:|-----:|---------:|---------------:|
| A | 232.33 | 44 | 381.68 | 4 | 3 | 34 |
| B | 132.23 | 10 | 638.52 | 15 | 2 | 43 |
| C | 222.51 | 44 | 332.52 | 1 | 1 | 40 |

**≥200 ≠ landing count.** B’s high `land_heuristic` with low ≥200 shows delayed / low-score rests are common.

## 2. Native reward on held-out eval

`scripts/evaluate_rich.py` creates `gym.make("LunarLander-v3")` only — **no** `wrap_reward` / shaping imports. Each JSON records `"eval_reward": "native_only"` and seeds `50000…50049`.

## 3. Checkpoint selection before held-out test

| Artifact | mtime (local) |
|----------|----------------|
| A `best_model.zip` | 2026-10-18T20:27:40 |
| B `best_model.zip` | 2026-10-18T20:45:09 |
| C `best_model.zip` | 2026-10-18T20:49:54 |
| Held-out eval JSONs | 2026-10-18T20:50:23–31 |

EvalCallback during training used **native** reward and seed base `10000` (`train_ppo.py`). Held-out seeds `50000+` are disjoint.

## 4. Reward equations vs code

| Exp | Doc | Code |
|-----|-----|------|
| B | +1 if `\|angle\|<0.2` and speed`<0.5` | `ProblematicHoverReward` defaults match |
| C | `R = r + (Φ_t−Φ_{t-1}) − 0.05` | `CorrectedProgressReward` matches |

## 5. Video audit (Gymnasium 600×400 @ 50 fps)

| Clip | Frames | Duration | Visual check |
|------|-------:|---------:|--------------|
| A success | 359 | ~7.2 s | Terminal frame: upright between flags |
| B seed 50019 | 1001 | ~20.0 s | Mid: airborne / delayed; full timeout length |
| B seed 50018 | 636 | ~12.7 s | Long approach |
| C success | 343 | ~6.9 s | Terminal frame: upright between flags |

Frames saved under `outputs/phase4/video_audit_frames/`.

## 6. ApolloLander preservation

This branch/PR must contain **only** the simplified LunarLander project (+ `.gitignore` tweak). No ApolloLander / `blind_visual` source changes are included in the publication commit.
