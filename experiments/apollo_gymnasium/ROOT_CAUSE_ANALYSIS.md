# PR #11 root-cause analysis (no new PPO training)

Historical pilots **unchanged**: v1 hover-timeout, v2 crash @ 0% land.
This document diagnoses *why*, proposes fixes, and names **one** next pilot for approval.

Artifacts: `outputs/root_cause/`, `outputs/parity/parity_outcomes.json`.

---

## Strongest finding (highest evidence)

**The progress_a dense reward is dominated by the per-Gym-step time penalty; potential progress is ~O(1) over an entire successful flight while time cost is O(50–200).**

| Policy (pilot_near, ar=4) | Gym steps | ΣΔΦ | Σ time (−0.05) | Terminal | **Total return** |
|---------------------------|----------:|----:|---------------:|---------:|-----------------:|
| no-op (crash) | 305 | +0.98 | −15.2 | −100 | **−114** |
| reference MultiDiscrete (land) | 1017 | +0.68 | −50.8 | +100 | **+50** |
| reference continuous (land) | 4232 | +0.69 | −211.6 | +100 | **−111** |
| PPO v2 (crash) | 346 | +0.44 | −17.3 | −100 | **−117** |

Source: `outputs/root_cause/reward_audit_summary.json`, plots in `reward_scale_plots.png`.

Implications:

1. A **successful continuous landing can score worse than a fast crash** under the training reward (−111 vs −114).
2. Even the MultiDiscrete expert’s dense path is **net negative** (−50); landing is carried almost entirely by the +100 terminal spike after ~1000 steps — brutal credit assignment.
3. Component audit: altitude/angle terms do not accumulate large positive ΣΔΦ on expert flights (alt ≈ 0; ang ≈ +0.5 once). Velocity penalties often cancel progress while descending.

**This is the primary reason PPO did not learn to land** — not a broken physics wrapper.

Secondary (supporting) factors below amplify the same failure.

---

## 1. Reward magnitude & credit assignment

### Dense vs terminal

- Mean |ΔΦ| per Gym step ≪ 0.05 time penalty on long flights.
- Terminal ±100 arrives after hundreds–thousands of steps with weak shaping.

### Terminal step handling

On land/crash/timeout the env **returns only the terminal constant** and drops that step’s ΔΦ (see `apollo_env._train_reward`). Minor vs scale bug, but discards the last progress signal.

### Gymnasium / SB3 timeout bootstrapping

| Event | Flags today | SB3 critic |
|-------|-------------|------------|
| Land / crash | `terminated=True` | No bootstrap |
| Frame budget | `truncated=True` + reward −100 | **Still bootstraps** \(V(s')\) |

So pilot v2’s “timeout = crash severity” is **not** a hard episode end for PPO’s value target. Documented in `outputs/root_cause/sb3_timeout_note.json`.

### Proposed corrected reward (A′ — **do not train until approved**)

\[
R_t^{A'}=\begin{cases}
+100 / +40 & \text{perfect / hard land} \\
-100 & \text{crash} \\
-100 & \text{timeout with }\texttt{terminated=True}\text{ for learning} \\
\alpha(\Phi_t-\Phi_{t-1}) - c & \text{else}
\end{cases}
\]

Recommended first settings (from short-horizon expert scale check):

- \(\alpha = 10\)
- \(c = 0.005\) per Gym step (or charge time per **physics** frame at \(c_\phi=0.001\))

On `sh_contact` MultiDiscrete landings (~40 Gym steps):  
ΣΔΦ≈0.24 → \(10\Sigma\Delta\Phi\approx2.4\); old Σtime≈−2.0; proposed Σtime≈−0.20.  
Dense signal finally dominates time cost while terminals stay large.

---

## 2. Short-horizon nontrivial curriculum

### Historical `pilot_near`

- **Identical** physical state for every seed (obs std = 0 across seeds).
- Reference land ~4000 physics frames — long credit horizon.

### New schedules (`short_horizon.v1`)

| Template | No-op land | Random land | Legal ref land | Mean ref frames | Seed-varied? |
|----------|------------|-------------|----------------|-----------------|--------------|
| `sh_tilt30_low` | 0 | 0 | 1.0 | ~1420 | yes |
| `sh_contact` | 0 | 0 | **0.75** | **~163** | yes |

`sh_contact` (preferred next curriculum):

- No-op crashes ~84 frames (needs control).
- Random 0% land (not trivial).
- Legal MultiDiscrete reference lands 75% in **~100–200** physics frames.
- Not a 3–6px soft-drop: y≈665, vy≈0.12, mild tilt; braking + upright required.
- Evidence: `outputs/root_cause/short_horizon/sh_contact_gate.json`, sweep in `sweep_hits.json`.

---

## 3. Observation & action analysis

### Scaling

- `vx,vy` ÷ 2 → typical |vy|~0.1 → obs **0.05** (tiny vs `|ang|/90` and `alt/300`).
- On varied short starts, obs std of vx/vy ≈ 0.008–0.01 vs angle std ≈ 0.33.
- **Recommendation:** retune velocity divisors (e.g. ÷0.5) in a **separate** controlled change — not in the same pilot as the reward fix.

### Legal controls & upright touchdowns

- ±10° relative steer from −30° reaches **exact 0°** in 3 Gym steps (12 physics @ ar=4).
- Thrust grid includes 0…1. Upstream landing still requires `rotation==0`.
- Action-repeat sweep {1,2,4,8}: MultiDiscrete reference land rate stays 1.0 on `sh_tilt30_low`; frame count ≈1400 (controller-limited, not ar-limited).

Keep **action_repeat=4** fixed for the next pilot so reward/start are the only interventions.

---

## 4. Starting-state variation

| Schedule | Same seed→same start | Different seeds→different physics |
|----------|----------------------|-----------------------------------|
| `pilot_near` (PR #11) | yes | **no** (frozen spawn) |
| `short_horizon.v1` / `sh_contact` | yes | **yes** (sha256 channels) |

API: `derive_short_horizon_start(template, seed)`. Fixed-seed reproducibility tested in parity outcomes.

---

## 5. Parity evidence (updated)

`scripts/parity_check.py` — repeatability / independence (prior).

**New** `scripts/parity_outcomes.py` → `outputs/parity/parity_outcomes.json`:

| Directly tested | Result |
|-----------------|--------|
| Reference → native perfect land + score 50 | pass |
| No-op → crash | pass |
| Short budget hover → truncated timeout | pass |
| Upright drop → crash/hard classifier path | pass |
| `short_horizon.v1` seed repro + variation | pass |
| Physics trace reproducibility | pass |

**Inherited (not re-derived here):** Lander.js landing inequalities; Landscape noise seed 12039 pad geometry. Headless vs windowed **GPU** pixels may differ; JS physics path is shared.

---

## 6. Experiment specification fix

| ID | Intent | Distinct? |
|----|--------|-----------|
| **A** | ΔΦ − \(c\) + terminals | baseline |
| **B** | A + upright∧slow **occupancy** bonus | yes (hover bait) |
| **C** | \(\alpha\Delta\Phi - c^{C}\) + terminated timeouts | **yes** (was identical to A in code — fixed in spec + `progress_c` impl) |
| **D** | sparse 0/+1/−1 | blocked |
| **E** | all-zero control | blocked |

See updated `REWARD_DEFINITIONS.md`. **No A/B/C/D training in this update.**

---

## Proposed single next pilot (awaiting approval)

**Name:** `ppo_pilot_v3_contact_Aprime`  
**Do not start until approved.**

| Knob | Choice | Why |
|------|--------|-----|
| Start | `sh_contact` seed-varied | Short horizon + nontrivial gates |
| Reward | A′: \(\alpha=10\), \(c=0.005\), timeout `terminated` | Fixes measured scale bug |
| Actions | MultiDiscrete, **ar=4** (unchanged) | Isolate reward/start |
| Obs scaling | **unchanged** | One intervention family |
| Budget | **≤200k** physics frames, 1 seed | Bounded |
| Eval | held-out seeds; vs step0 / noop / random / legal ref | Same protocol |
| Stop | If 0 lands after 200k, preserve negative; no B/C/D | Gate |

---

## Ranking of interventions (evidence strength)

1. **Reward re-scale + terminated timeouts (A′)** — quantitative expert/PPO audit; continuous land return &lt; crash return. **Strongest.**
2. **Short contact-horizon starts (`sh_contact`)** — cuts credit horizon ~20× vs pilot_near; gates pass with legal controls.
3. **Velocity obs re-scaling** — clear under-scaling, but secondary; change alone after A′ works or fails.
4. **Action-repeat / absolute-angle redesign** — legal controls already can land; not the binding constraint in audits.

Previous pilot results remain the published negative baseline.
