# V5 results — `ppo_pilot_v5_commitment` (NEGATIVE vs V3-40k)

**Preflight:** PASSED (`outputs/preflight_v5/preflight_report.json`)  
**Physics budget:** **199 999** actual frames (cap 200 000; verified in `v5_freeze_manifest.json`)  
**Sole intended change vs V3 A′:** late-approach commitment shaping  
`(β=1, H_app=25, D_app=60, V_soft=0.15, R_soft=15°)` + explicit `approached` obs bit (**11-D**)

V4 time-cost negative result preserved. V3-40k incumbent untouched (`sha256 4a1f2c85…`).

Frozen formula: `V5_COMMITMENT.md`. Freeze hashes: `v5_freeze_manifest.json`.

---

## Selected checkpoint (DEV 200000–200019 only)

| Rule | max native land rate → min timeout rate → min mean flight duration |
|------|---------------------------------------------------------------------|
| **Selected** | `step0_random_init` (**untrained**) |
| SHA-256 | `f98153e1032b5f283970cc0d70372c772c50f2d81e527485da143670c076b5e4` |
| DEV land | **0/20 = 0%** |
| DEV crash | 20/20 |
| Beats V3-40k on DEV (60%)? | **No** |

`selected/selected_model.zip` byte-identical to `step0_random_init.zip`.

### Full DEV sweep (all 0% land)

| Checkpoint | Land | Crash | Timeout | Reascent |
|------------|-----:|------:|--------:|---------:|
| **step0 (selected)** | 0 | 20 | 0 | 0 |
| 5k–30k (trained) | 0 | 2 | 18 | **18** |
| 35k–50k / final (trained) | 0 | 20 | 0 | 0 |

---

## Held-out (`500000–500019`) — selected vs trained (not for selection)

| Policy | Land | Crash | Timeout | Reascent | Mean frames |
|--------|-----:|------:|--------:|---------:|------------:|
| **V5 selected = step0** | **0/20** | 20 | 0 | 0 | 90 |
| V5 trained final (not selected) | **0/20** | 20 | 0 | 0 | 97 |
| V5 trained 25k (not selected) | **0/20** | 5 | 15 | **15** | 1526 |
| V3-40k det (incumbent) | **8/20 (40%)** | 0 | 12 | 12 | 1238 |
| No-op / random | 0/20 | 20 | 0 | 0 | ~90–117 |
| Legal reference | 16/20 (80%) | 4 | 0 | 0 | 163 |

**Δ land (selected V5 − V3-40k) = −40 pp.**  
Trained V5 checkpoints also **0% land** on this pool — selection of step0 did not hide a secret trained success.

Artifact: `heldout_trained_vs_selected.json`.

---

## Re-ascent

- Selected/step0 & final: 0 reascent because **crash-before-approach**.
- Trained mid (25k): **15/20** held-out reascent — commitment did not remove the mode.
- Do not read selected held-out reascent=0 as a win.

---

## Failure autopsy (offline)

See `failure_autopsy/FAILURE_AUTOPSY.md`.

- Undiscounted: crash (~−98) ≫ V3-style reascent under V5 R (~−401; Σ commit ≈ −261).
- Discounted γ=0.99: mid-reascent can beat crash (−13 > −78) because distant penalties dilute.
- Lands unaffected by commit (Σ≈0). Reward penalty ≠ obs feature; both changed in V5.

---

## Video evidence (original renderer)

- Failure: `evidence/failure_500000/native.mp4` (preserved; hashed in freeze manifest)

---

## Champion

**Preserve V3-40k.** V5 is a completed negative experiment. No V6. No A/B/C/D launch from this file.
