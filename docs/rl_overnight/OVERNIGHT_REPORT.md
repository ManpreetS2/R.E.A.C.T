# Overnight RL report — ApolloLander (original upstream)

**Verdict (outcomes first):** Across **~28.0M** physics frames of genuine CPU PPO on
the **parity-verified original upstream** ApolloLander engine, **no trained network
achieved a verified native landing** (train or held-out `1000100–1000299`).  

Reward **does change behavior** (shaped A vs zero-reward CTRL differ), but the
change is longer hovering / mode-switching — **not** learning to land. This is a
documented negative result with continuous-resume and causality evidence.

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-overnight-v2` |
| PR | https://github.com/ManpreetS2/R.E.A.C.T/pull/4 |
| Base pilot | `cursor/apollolander-rl-pilot-2f7b` @ `efb025f` |
| Upstream | Seb Lee-Delisle `0da09dc` (hashes MATCH) |
| Parity | **PASS** |
| Physics frames used | ~28,020,736 / 30M |
| Hardware | 4 CPU, ~15 GiB RAM, $0 |

---

## Owner rules: learn from experience (how we complied)

1. **Fewer, longer CONTINUOUS runs.** After each run’s own random `step0`, training
   continued by resuming **that run’s** `final.pt` (weights + optimizer +
   `global_step` / update counters). Resume points logged in
   `logs/resume_events.jsonl`. Obs use fixed `OBS_SCALE` (no running norm to carry).
2. **Never** loaded the old pilot `final.pt` or any other run’s weights into a new
   experiment.
3. **Learning-from-experience evidence** per run: chronological crash/timeout/landing
   plots + JSON verdicts (`logs/learning_from_experience.json`,
   `plots/learning_from_experience.png`).
4. **Reward-causality CONTROL:** `CTRL_zero_reward_s0` — same seed/config as Family A,
   `reward_mode: constant_zero`, counted inside the 30M frame budget.

---

## 1. Original-game integration

Unmodified upstream `Lander.js` / `Landscape.js` via Node `vm` host; Chromium bridge
for parity/videos. **PASS** — see `PARITY_REPORT.md`.  
Actions: `lander.thrust(0..1)`, `lander.setRotation` (10°). Abort not exposed.

---

## 2. Pilot root-cause

See `PILOT_ROOT_CAUSE.md`. Confirmed: GAE timeout non-bootstrap (fixed); throughput
inflation; action_repeat 2 vs bench 4; timeout≪crash hover incentive.

---

## 3. Completed runs

| Run ID | Family | Notes | Seed | Frames | Wall (s) | Episodes | Land | Crash | Timeout | Checkpoint | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| smoke_A | A | smoke | 0 | 16,384 | 3 | 0 | 0 | 0 | 0 | `smoke_A/checkpoints/final.pt` | done |
| A_reproduce_upstream_s0 | A | **continuous** 0→7.0M (resume @ 3.0M) | 0 | **7,000,064** | ~429+650 | 2535 | 0 | — | — | `A_…/checkpoints/final.pt` | done |
| B_stable_lowlr_s1 | B | short family | 1 | 3,000,320 | 431 | 1505 | 0 | 1493 | 12 | `B_…/final.pt` | done |
| C_timeout_eq_crash_s2 | C | alt reward | 2 | 3,000,320 | 413 | 372 | 0 | 0 | 372 | `C_timeout…/final.pt` | done |
| C_sparse_s3 | C | sparse | 3 | 2,000,896 | 278 | 272 | 0 | 36 | 236 | `C_sparse…/final.pt` | done |
| C_step_cost_s6 | C | step cost | 6 | 4,001,792 | 688 | 500 | 0 | 0 | 500 | `C_step…/final.pt` | done |
| D_curriculum_easy_s7 | D | **continuous** 0→6.0M (resume @ 3.0M) | 7 | **6,000,640** | ~431+… | 1777 | 0 | — | — | `D_…/final.pt` | done |
| CTRL_zero_reward_s0 | CTRL | **causality** zero reward | 0 | 3,000,320 | ~450 | 533 | 0 | 219 | 314 | `CTRL_…/final.pt` | done |

All policies: **random init at that run’s step0 only**. Continues carry the same run forward.

### A continuous detail (learning from experience)

| Phase | Episodes | Crash | Timeout | Mean steps |
| --- | ---: | ---: | ---: | ---: |
| Pre-resume (0–3.0M) | 1416 | 0.985 | 0.015 | 2114 |
| Post-resume (3.0–7.0M) | 1119 | 0.833 | 0.167 | 3554 |
| Late 20% overall | 507 | 0.716 | 0.284 | 4222 |

- Landing rate: **0 throughout**; time to first landing: **never**.
- Terminal `|vy|` / pad distance (post-resume logging): pad distance did **not** improve
  (late mean dist ~813 vs earlier ~679); softer `|vy|` alone is not landing skill.
- **Honest verdict:** failure modes did **not** decline into landings. Behavior shifted
  toward longer flights / more timeouts (hover), consistent with shaped reward ranking
  timeout above crash.

### D continuous detail

Crash rate declined somewhat while timeouts rose; episode length rose; **0 landings**.
Curriculum easy starts did not unlock a first success.

---

## 3b. Reward-causality control

| | A shaped (phase1 ~3M, seed 0) | CTRL zero-reward (~3M, seed 0) |
| --- | --- | --- |
| Early crash / timeout / steps | 0.98 / 0.02 / 1631 | 0.00 / 1.00 / 8000 |
| Late crash / timeout / steps | 0.95 / 0.05 / 2978 | 0.44 / 0.56 / 5783 |
| Landings | 0 | 0 |

**Finding:** Trajectories differ under the same seed/config/budget → the reward signal
**does** change behavior (not pure entropy-identical drift). Shaped A stays
crash-dominated with lengthening flights; zero-reward CTRL starts as pure timeouts
then mixes crashes. **Neither learns to land.**  
Evidence: `results/causality_comparison.json`.

---

## 4. Plots

- Standard: `results/<run>/plots/{reward,outcomes,fuel,stability}.png`
- **Learning-from-experience:** `results/<run>/plots/learning_from_experience.png`
  (+ copies under `/opt/cursor/artifacts/rl_overnight/`)

---

## 5. Videos

Original renderer under `/opt/cursor/artifacts/rl_overnight/*.mp4` (phase-1
checkpoints; manifests with `outcome_match: true`). Seeds chosen before outcomes.

---

## 5b. Held-out test (n=200, seeds 1000100–1000299)

Phase-1 finals: all **0** land (A/B/C_step/D). Continued A final re-eval logged under
`A_reproduce_upstream_s0/evaluation/` (expect 0; see latest held_out JSON).

---

## 6. Checkpoints & scripts

- Continuous resume: `train.py --resume <same-run>/checkpoints/final.pt --total-env-steps …`
- LFE analysis: `analyze_learning_from_experience.py`
- Causality config: `configs/CTRL_zero_reward_s0.yaml`
- Sealed seeds `2000000–2000015` never touched

---

## 7. Scientific conclusion

1. **Did any net learn to land?** **No** — including after continuous extension of A to
   7M and D to 6M frames.
2. **Did agents learn from mistakes?** They **changed** failure modes (longer survival,
   more timeouts under shaped reward) but did **not** reduce crashes into landings or
   improve pad approach. Reported honestly.
3. **Does reward cause the change?** **Yes, partially** — zero-reward CTRL ≠ shaped A
   on the same seed/config. Causality for *behavior*, not for *success*.
4. **Unresolved / next:** continuous actions or denser success bonuses; GPU PPO
   updates (`WINDOWS_GPU_HANDOFF.md`); pixel RL only after a state policy can land.

---

## 8. Verified vs inferred

| Verified | Inferred |
| --- | --- |
| Upstream parity PASS | Need ≫30M or different action space to land |
| 0 RL landings @ ~28M frames | — |
| Continuous resume carried optimizer/weights | — |
| Reward vs zero-CTRL behavioral divergence | — |
| Failure modes did not become landings | — |
