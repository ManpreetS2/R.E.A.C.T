# ApolloLander Gymnasium RL — Pilot Report

**Engine:** Seb Lee-Delisle ApolloLander (MIT), unchanged under
`frontend/apollolander/upstream/`, driven via `frontend/apollolander/original/bridge.js`.

**Branch:** `experiment/apollo-gymnasium-rl` (draft PR; do not merge).

**Credit:** Original game © Seb Lee-Delisle · https://github.com/sebleedelisle/apollolander

---

## Executive answers

| # | Question | Answer |
|---|----------|--------|
| 1 | Real ApolloLander through Gymnasium? | **YES** — `engine=upstream-original` |
| 2 | Browser/headless parity? | **PASS** (`outputs/parity/parity_report.json`) |
| 3 | Task nontrivial + solvable? | **YES** on `pilot_near` (no-op 0%, reference 100%) |
| 4 | Did PPO learn to land? | **NO** (within ≤1M physics-frame pilot budget) |
| 5 | Independent landing rate (trained PPO)? | **0%** on held-out seeds 50000–50019 |
| 6 | Next justified step? | Investigate reward / action / curriculum — **do not** start A/B/C/D yet |

---

## Methods

- **Observations:** 10-D normalized numerical vector (`OBSERVATIONS.md`). No screenshots for RL.
- **Actions:** `MultiDiscrete([5,3])` — thrust ∈ {0, 0.25, 0.5, 0.75, 1}, steer ∈ {−10°, 0, +10°}, `action_repeat=4`.
- **Training reward:** Experiment A progress potential + terminals (`REWARD_DEFINITIONS.md`). Native score untouched.
- **Pilot start:** `pilot_near` (pad midpoint − 40, y=280, rotation=−30°).
- **Algorithm:** SB3 PPO `MlpPolicy`, random init, seed 0.
- **Feasibility reference:** demonstration guidance (continuous absolute controls) — **never** used in PPO updates.
- **Budget:** two sequential 500k-physics pilots (1M total). Hard stop; no A/B/C/D.

---

## Gate evidence

### Parity

Reset identity, deterministic traces, independent parallel pages, pad width ≈ 179 on the fixed map.

### Start distributions (`outputs/start_gate/`)

| Distribution | no-op land | random land | reference continuous | MultiDiscrete ref | Gate |
|--------------|------------|-------------|----------------------|-------------------|------|
| `pilot_near` | 0.0 | 0.0 | 1.0 | 1.0 | PASS (chosen) |
| `pilot_offset` | 0.0 | 0.0 | 1.0 | 1.0 | PASS |
| `original_fixed` | 0.0 | 0.0 | 1.0 | 1.0 | PASS (harder milestone) |

No-input reliably crashes (~1220 physics frames on `pilot_near`). Doing nothing cannot land.

---

## PPO pilot results

### v1 — timeout milder than crash (`outputs/ppo_pilot_v1_hover/`)

- 500k physics frames, timeout reward −20, per-step −0.01.
- **Eval (20 eps):** PPO land 0%, crash 0%, **timeout 100%**.
- Step-0 init: crash 100%.
- **Finding:** policy learned a deterministic hover/delay strategy (crash −100 ≫ timeout −20).

### v2 — timeout = crash severity (`outputs/ppo_pilot_v2/`)

- 500k physics frames, timeout −100, per-step −0.05 (see updated `REWARD_DEFINITIONS.md`).
- **Eval (20 eps):** PPO land 0%, **crash 100%**, timeout 0%.
- Mid-checkpoints sampled: still 0 landings.
- Learning curve: `outputs/ppo_pilot_v2/learning_curve.png`.

Hovering was eliminated; landing was **not** discovered within budget.

---

## Visual evidence (original renderer)

| Clip | Path | Native outcome |
|------|------|----------------|
| Reference landing | `outputs/videos/reference_landing_50000/episode.mp4` | landed, native_score 50 |
| PPO v2 | `outputs/videos/ppo_v2_50000/episode.mp4` | crashed |

Unmodified Seb Lee-Delisle canvas frames (plus short end hold). No fake HUD labels.

---

## Experiment D (documented, **not run**)

Sparse outcome-only: 0 / +1 / −1. Same physics, obs, actions, PPO, starts, eval protocol.
**Blocked** until a landing-capable Experiment A baseline exists and budget is approved.

Optional E (zero-reward negative control) likewise gated.

---

## Follow-up: root-cause (no new training)

See **`ROOT_CAUSE_ANALYSIS.md`**. Primary failure mode: time penalty overwhelms ΣΔΦ
(expert continuous land return **−111** vs crash **−114**). Proposed next pilot
`ppo_pilot_v3_contact_Aprime` uses `sh_contact` + reward A′ — **awaiting approval**.

Do **not** merge as a solved-landing claim. Preserve v1 hover and v2 crash results.
