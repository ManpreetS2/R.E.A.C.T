# Curriculum v3 report — ApolloLander progressive landing curriculum

**Audit supersedes earlier “L0 learning is real” wording.** See `AUDIT.md`.

**Outcomes first**

| Question | Answer |
| --- | --- |
| Evidence of genuine L0 learning vs matched untrained/prior? | **No.** s13 L0 basic learning check at **259,144** frames: frozen policy **0/40** (all crash), `passed: false`, reasons `not_above_random`, `not_above_untrained`, `prior_solves_l0_require_retain_ge_0.5`. Baselines used for that comparison were **not** matched (see below). |
| Highest level reached | **L1** after an L0 **gate** 40/40 at **109,128** frames (deterministic eval). Never passed L1 ≥50% gate. Gate success ≠ learning-check success. |
| Frames to first train landing (logged) | s13: one stochastic train landing in `first_landings.jsonl` at **8,776** (prior-on run). Resumed `learning_curve.csv` shows **0** train landings thereafter. s11: first at **271,136** (no delta/hold priors; check later failed). |
| Success criterion (one verified native landing on **normal** `apollolander.starts.v1`, unseen seed, trained NN)? | **No.** Final eval seeds `1000300+`: **0** landings for trained final / spot-check policies. |
| What failed | Absolute rotation → hover collapse (s11). Delta without priors → 0 landings (s12). s13 **output-layer init priors** (soft thrust + hold attitude) contaminate L0; learning check failed; early-stop bug let training continue to ~1.09M; no L1/v1 transfer. |
| Parity (V2) | **TESTED-PASS** for perfect, hard, crash, timeout (real `game.js` in Chromium vs Node host). |
| Random-policy landing rate per level | **0.000** (200 eps) on L0–L4, Family-D easy, and v1 — but measured at `max_steps=1200`, mostly timeouts. |
| Training frames | **1,991,752 / 2,000,000** (s11 500,736 + s12 400,384 + s13 1,090,632). s13 should have stopped at the failed L0 check. |
| Diagnostic frames | **~6.9M** (baselines 3,358,817 + final eval 3,201,575 + gates/check/parity). Far above ~1M target — see `AUDIT.md` (f). |
| Wall time (train) | s11 ~661 s + s12 ~115 s + s13 ~408 s ≈ **19.7 min** CPU train (plus baselines/parity/eval). |
| Desktop GPU justified? | **Not for claiming L0 learning.** Physics is CPU-bound; GPU does not fix invalid priors/baseline design. |

---

## Branch / PR / SHA

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-curriculum-v3` |
| Base | `main` (draft PR; does **not** merge overnight-v2) |
| Forked from | `cursor/apollolander-rl-overnight-v2` @ `3e08dcb` |
| Upstream game | Seb Lee-Delisle MIT `0da09dc` — `frontend/apollolander/upstream/` **unchanged** |
| Hardware | This VM CPU only, $0 |
| Audit | `docs/rl_curriculum_v3/AUDIT.md` |

---

## Phase 1 — Parity V2

See `PARITY_REPORT_V2.md`.

- PR #4 marked landing/timeout PASS without trajectories ending in those terminals — **corrected here**, original PR #4 report untouched.
- Categories: perfect **TESTED-PASS**, hard **TESTED-PASS**, crash **TESTED-PASS**, timeout **TESTED-PASS**.
- Browser runs **literal** `game.js` collision/scoring functions; Node host copies match on terminals (crash-frame fuel differs by documented `Math.random` penalty in real `game.js`).
- Guidance controller used **only** to generate landing traces — isolated under `reference_guidance/`.

## Phase 2 — Why Family D got zero landings

| Factor | Finding |
| --- | --- |
| Start hardness | `curriculum_easy_v1` is ~60–180 px above pad with rotations often ≠ 0; native land needs **exact** `rotation == 0` and `vy < 0.15`. |
| Random rate | **0/200** landings on D-easy and on new L0–L4 (uniform random continuous thrust + rotation), at 1200-step horizon. |
| Action structure | Independent absolute 10° bins make holding upright for many steps probability ~`(1/19)^n` — landings almost never observed. |
| Reward (overnight D) | `step_cost` / hover ranking; without observed landings, PPO cannot reinforce touchdown. |
| Scripted solvability | Open-loop soft drop on L0: **100/100** perfect landings — task is solvable; exploration is the bottleneck. |

## Phase 3 — Progressive PPO

Reward frozen: `touchdown_v1` (`REWARD_TOUCHDOWN_V1.md`). Continuous thrust + rotation; GAE truncation bootstrap retained.

| Run | Seed | Frames | Result |
| --- | ---: | ---: | --- |
| `CURR_touchdown_s11` | 11 | 500,736 | 3 train L0 landings (first 271,136); frozen L0 check **40/40 timeouts** → early stop |
| `CURR_touchdown_delta_s12` | 12 | 400,384 | Delta rotation, no prior; **0** landings; L0 check fail → early stop |
| `CURR_touchdown_delta_s13` | 13 | 1,090,632 | Delta + **output-layer init priors**; L0 gate 40/40 @ 109,128 then L1; L0 learning check **FAIL 0/40** @ 259,144; training **did not stop** (bug: stop only if `level_idx==0`); stuck on L1 at 0% |

### Priors (s13) — what they actually are

`soft_thrust_prior` / `hold_attitude_prior` set **output-layer init biases** in `ContinuousThrustActorCritic.reset_parameters` (`thrust_mean.bias=-1.25` ≈ 0.22 thrust; delta hold logit `+2.5`). They are human-coded soft-drop / attitude-hold biases, not residual policies or action-space transforms. Full analysis: `AUDIT.md` (a).

`prior_solves_l0: true` in the learning-check JSON is a **config-flag inference**, not a measured prior-alone landing rate. Prior-alone rates on gate seeds and baseline seeds were **not logged**.

### Baseline mismatch (invalid “vs untrained”)

Phase-2 / embedded check baselines built `ContinuousThrustActorCritic(hidden=128)` with defaults: **absolute** rotation, **no** priors, `max_steps=1200`. s13 train/gate used **delta** + both priors + `max_steps=400`. See `AUDIT.md` (b).

### Gate log (s13, selected)

| Frames | Level | Land rate | Pass | Note |
| ---: | --- | ---: | ---: | --- |
| 58,952 | L0 | 0.000 | FAIL | 40/40 crash |
| 109,128 | L0 | 1.000 | PASS → L1 | Deterministic gate; not a passed learning check |
| 159k–1.09M | L1 | 0.000 | FAIL | |
| 259,144 | (check on L0) | 0.000 | **learning check FAIL** | Should have stopped; did not |

### Learning curve vs first landing

Resumed `learning_curve.csv` (from step 9,772): **0** train landings; L0 phase is crash-only in the CSV. `first_landings.jsonl` still records one landing at 8,776 from the pre-resume session. Plot reflects the CSV, not the jsonl. Details: `AUDIT.md` (c).

## Phase 4 — Final evaluation

Protocol seeds **chosen before outcomes:** `1000300–1000499` (n=200), schedule `apollolander.starts.v1`, `max_steps=2000` for learned/random/untrained/PR4. Guidance re-validated at `max_steps=8000`, `action_repeat=2`.

| Agent | Landing rate | Wilson 95% | Notes |
| --- | ---: | --- | --- |
| trained_deterministic (s13 final) | **0.000** | [0, 0.019] | 200/200 crash |
| trained_stochastic | **0.000** | [0, 0.019] | 200/200 crash |
| random | **0.000** | [0, 0.019] | mostly timeout |
| untrained (eval loads cfg priors) | **0.000** | [0, 0.019] | v1, not L0 prior rate |
| PR #4 run A final.pt | **0.000** | [0, 0.019] | |
| hand-tuned guidance **REFERENCE ONLY** | **1.000** | [0.981, 1.000] | 200/200 perfect @ 8k steps |

Per-level frozen s13 **final** (after L1 training): **0%** on L0–L4 — L0 gate-pass checkpoint skill was **not** retained in `final.pt`.

JSON: `examples/apollolander/rl_curriculum_v3/results/CURR_touchdown_delta_s13/evaluation/final_eval_results.json`  
Eval diagnostic frames: **3,201,575** total in that file.

## Evidence paths (logs retained; interpretation corrected)

| Artifact | Path |
| --- | --- |
| Audit | `docs/rl_curriculum_v3/AUDIT.md` |
| L0 learning check (FAIL) | `…/CURR_touchdown_delta_s13/logs/l0_learning_check.json` |
| First s13 L0 landing ckpt | `…/checkpoints/first_land_L0_8776.pt` |
| L0 gate-pass ckpt | `…/gate_pass_L0_109128.pt` |
| Browser HUD videos (L0 gate seeds) | `/opt/cursor/artifacts/rl_curriculum_v3/gateL0_seed430011_landed.mp4` |
| Parity report | `docs/rl_curriculum_v3/PARITY_REPORT_V2.md` |

## Verified vs inferred

| Claim | Status |
| --- | --- |
| Terminal parity browser↔Node for all four categories | **Verified** |
| s13 L0 learning check passed / L0 learning is real | **False** — check failed; see `AUDIT.md` |
| Native L0 landings under prior-on deterministic gate | **Logged** (gate 40/40); **not** counted as genuine learning under owner rule |
| Target-task (v1) landing by trained NN | **Verified absent** |
| Family D failure diagnosis | **Supported** by rates + landing rule + action combinatorics |
| Prior-alone L0 rate on gate/baseline seeds | **Not measured** (cost in `AUDIT.md` (a); not run) |

## GPU (RTX 4080 Super) recommendation

Not justified by this run’s scientific outcome. Fix experimental validity (no human-coded priors, matched baselines, honor learning-check stop) before scaling compute. Physics remains CPU-bound in Node/JS.
