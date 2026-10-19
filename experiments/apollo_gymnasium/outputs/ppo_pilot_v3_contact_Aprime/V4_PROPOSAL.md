# Operation V4 — Proposal (awaiting approval)

**Status:** Phase 1–3 complete. **No V4 training started. No A/B/C/D. Do not merge PR #11.**

Artifacts: `outputs/ppo_pilot_v3_contact_Aprime/v4_audit/`

---

## Phase 1 — V3 freeze & audit

### Freeze
SHA-256 hashes for final/step0 models, all checkpoints, train_summary, run_config, eval JSONs, landing meta, and `V3_RESULTS.md` are in `v4_audit/v3_freeze_manifest.json`.

| Artifact | SHA-256 (prefix) |
|----------|------------------|
| `final_model.zip` | `3b102ddd…` |
| `step0_random_init.zip` | `6f2ab08f…` |
| `ppo_apollo_40000_steps.zip` (best DEV) | `4a1f2c85…` |

### Landing replay (original game)
- Replayed frozen action trace on seed `300001` / `sh_contact`: **perfect land**, native score 50, 94 physics frames — matches meta.
- No-op on same start: **crash** (not a free lunch).
- Original-renderer MP4: `landing_evidence/landing_native.mp4` and audit copy `v4_audit/landing_native_accessible.mp4`.

### Step-0 held-out (post-hoc only)
Labeled comparison on V3 held-out `300000–300019` — **no tuning**:

| Policy | Land | Crash | Timeout |
|--------|-----:|------:|--------:|
| Step-0 (post-hoc) | 0% | 100% | 0% |
| Final det (prior) | 40% | 0% | 60% |

### DEV checkpoint sweep (selection pool only)

| Checkpoint | Land | Perfect | Hard | Crash | Timeout |
|------------|-----:|--------:|-----:|------:|--------:|
| step0 | 0.00 | 0 | 0 | 1.00 | 0 |
| 5k | 0.00 | 0 | 0 | 1.00 | 0 |
| 10k | 0.05 | 0.05 | 0 | 0.05 | 0.90 |
| 15k | 0.50 | 0.20 | 0.30 | 0.50 | 0 |
| 20k | 0.00 | 0 | 0 | 0.60 | 0.40 |
| 25k | 0.00 | 0 | 0 | 0.60 | 0.40 |
| 30k | 0.40 | 0.25 | 0.15 | 0.20 | 0.40 |
| 35k | 0.05 | 0.05 | 0 | 0.55 | 0.40 |
| **40k** | **0.60** | **0.40** | **0.20** | **0** | **0.40** |
| 45k | 0.55 | 0.35 | 0.20 | 0 | 0.45 |
| 50k / final | 0.10 | 0.10 | 0 | 0 | 0.90 |

**Best existing checkpoint on DEV:** `ppo_apollo_40000_steps` — **60% land**, beats final (10%) by 6×. Late training **regressed** into timeout/hover.

### Physics budget fix
`PhysicsBudgetCallback` now refuses the next Gym step when `frames + action_repeat > max_physics_frames`, so future runs stop **under** the approved cap (fixes V3’s 200003 overshoot).

---

## Phase 2 — Timeout root cause

Compare land vs timeout on best DEV checkpoint (40k), n=20:

| | Land (n=12 incl. hard) | Timeout (n=8) |
|--|------------------------:|---------------:|
| Frames | ~119 | 2000 |
| `alt_last` | ≈ 0 | ≈ **1029** |
| `min_alt` | ≈ 0 | ≈ **5.0** |
| Mean thrust cmd | 0.75 | 0.75 |
| Mean \|rot\| | 0.56 | 3.1 |
| Fuel remaining | ~1000+ | ~701 |

**Root cause:** Timeouts are **commitment aborts**, not crashes and not pure high-altitude loitering from t=0. The craft reaches near-surface (`min_alt ≈ 5`), then **re-ascends** under sustained ~0.75 thrust and burns the full 2000-frame budget at ~1 km altitude. Successful episodes commit in ~80–170 frames.

Final model is worse: timeouts end at ~1541 alt with ~49% full-thrust fraction.

Starts for land vs timeout are similar — failure is behavioral, not seed geometry.

**Not the dominant issue:** rotation lock alone, lateral drift alone, or never approaching the surface.

---

## Phase 3 — Proposed single V4 intervention

### Primary intervention (one change only)
**Increase A′ time cost `c`: `0.005` → `0.02` (4×).**

Evidence: abort-then-hover episodes are ~17× longer than successful landings; weak per-step time cost (`c=0.005` → only −2.5 over 500 Gym steps) does not outweigh delaying the −100 timeout terminal. Stronger `c` pressures early commitment after near-approach without changing observations, action space, terminals, α, or curriculum.

**Explicitly not changing in V4:** obs, action space, α=10, terminals (±100/40/100), `sh_contact`, ar=4, timeout=terminated, physics/steering/terrain/collision/native score.

**Deferred (not V4):** late-approach bonus (backup if `c=0.02` fails), curriculum, original_fixed.

### Training protocol
| Item | Value |
|------|-------|
| Init | Random (fresh PPO; do **not** warm-start from V3) |
| Physics budget | **≤ 200,000** actual engine frames (hard guard; no overshoot) |
| Start | `sh_contact` seed-varied, `TRAIN_SEED_BASE=100000` |
| Reward | A′ with **c=0.02**, α=10 |
| Checkpoints | Every 5k Gym steps (same cadence as V3) |
| Selection | **Best DEV land rate** (deterministic); never use held-out for selection |
| DEV | Existing `DEV_EVAL_SEEDS` 200000–200019 |
| Held-out | **New** `V4_HELD_OUT_SEEDS` 400000–400019 (V3 300k is contaminated) |
| Metrics | perfect, hard, crash, timeout, fuel remaining, flight duration |
| Stochastic | Report both det and stochastic; selection on det land rate |
| Target (DEV, aspirational) | 70–80% land — **do not chase via hidden retries** |
| Separate milestone | `original_fixed` / full-game — out of scope for this pilot |

### Eval cadence
1. After training: DEV eval every saved checkpoint + final.
2. Pick best by `(land_rate, -timeout_rate)` on DEV only.
3. **Once:** evaluate that checkpoint on `V4_HELD_OUT_SEEDS` (n=20).
4. Report vs step-0 and legal reference on the same V4 held-out (no model selection).

---

## Phase 4 — Go / no-go

| Decision | Recommendation |
|----------|----------------|
| **V4 training (200k, c=0.02)** | **GO — pending your approval** |
| A/B/C/D | **NO-GO** |
| Merge PR #11 | **NO-GO** (keep open; audit/proposal can land as follow-up commits) |
| More frames on V3 final | **NO-GO** (final regressed; 40k already better) |
| Promote V3-40k without retrain | Optional baseline only; does not replace V4 from random weights |

**Rationale for GO:** Dominant failure is diagnosed; single coefficient change is justified; budget accounting fixed; new held-out reserved; V3-40k shows 60% DEV is already reachable so 70–80% is plausible without inventing results.

**Awaiting approval before consuming any additional training frames.**
