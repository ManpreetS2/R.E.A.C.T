# Curriculum v3 report — ApolloLander progressive landing curriculum

**Outcomes first**

| Question | Answer |
| --- | --- |
| Evidence of learning vs random/untrained per level? | **Yes on L0 (seed 13):** frozen gate-pass policy reached **100%** native landings (40/40; Wilson **[0.912, 1.000]**) on L0 validation seeds, vs random/untrained **0%** on the same schedule. **No** further gated progress: L1 frozen landing rate stayed **0%**. |
| Highest level reached | **L1** (`curriculum_l1_v3`), after advancing from L0 at **109,128** frames (seed 13). Never passed the L1 ≥50% gate. |
| Frames to first trained landing | **L0:** seed 13 at **8,776**; seed 11 at **271,136**. **L1–L4 / v1:** never. |
| Success criterion (one verified native landing on **normal** `apollolander.starts.v1`, unseen seed, trained NN)? | **No.** Spot-check and final eval on seeds `1000300+` show **0** landings for trained final / gate-pass policies. |
| What failed | Absolute 19-way rotation → hover collapse (s11). Delta-only without soft-thrust prior → 0 landings (s12). Soft-thrust + hold-attitude prior solves L0 but does **not** transfer to L1+/v1 within remaining budget; PPO on L1 stayed at 0% gate landings. |
| Parity (V2) | **TESTED-PASS** for perfect, hard, crash, timeout (real `game.js` in Chromium vs Node host). |
| Random-policy landing rate per level | **0.000** (200 eps) on L0–L4, Family-D easy, and v1 (Wilson 95% ≈ **[0, 0.019]**). |
| Training frames | **1,991,752 / 2,000,000** (s11 500,736 + s12 400,384 + s13 1,090,632). |
| Diagnostic frames | **Parity traces ~36,674; baseline measure 3,358,817; gate/eval additional.** Baseline episode count overshot the ~1M diagnostic target — reported exactly; future runs must cut baseline `max_steps`/episodes. |
| Wall time (train) | s11 ~661 s + s12 ~115 s + s13 ~408 s ≈ **19.7 min** CPU train (plus baselines/parity/eval). |
| Desktop GPU justified? | **Partially.** JS physics is CPU-bound (~2–5k frames/s here); GPU helps **PPO update** throughput and larger nets, not the integrator. Justification: longer runs / more seeds to push L1→v1 after L0 is solved; not required to reproduce L0 gate-pass. |

---

## Branch / PR / SHA

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-curriculum-v3` |
| Base | `main` (draft PR; does **not** merge overnight-v2) |
| Forked from | `cursor/apollolander-rl-overnight-v2` @ `3e08dcb` |
| Upstream game | Seb Lee-Delisle MIT `0da09dc` — `frontend/apollolander/upstream/` **unchanged** |
| Hardware | This VM CPU only, $0 |

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
| Random rate | **0/200** landings on D-easy and on new L0–L4 (uniform random continuous thrust + rotation). |
| Action structure | Independent absolute 10° bins make holding upright for many steps probability ~`(1/19)^n` — landings almost never observed. |
| Reward (overnight D) | `step_cost` / hover ranking; without observed landings, PPO cannot reinforce touchdown. |
| Scripted solvability | Open-loop soft drop on L0: **100/100** perfect landings — task is solvable; exploration is the bottleneck. |

## Phase 3 — Progressive PPO

Reward frozen: `touchdown_v1` (`REWARD_TOUCHDOWN_V1.md`). Continuous thrust + rotation; GAE truncation bootstrap retained.

| Run | Seed | Frames | Result |
| --- | ---: | ---: | --- |
| `CURR_touchdown_s11` | 11 | 500,736 | 3 train L0 landings (first 271,136); frozen L0 check **40/40 timeouts** → early stop |
| `CURR_touchdown_delta_s12` | 12 | 400,384 | Delta rotation, no prior; **0** landings; L0 check fail |
| `CURR_touchdown_delta_s13` | 13 | 1,090,632 | Delta + soft-thrust/hold-attitude **init priors** (not guidance); L0 gate **PASS 100%** @ 109,128; stuck on L1 at 0% |

**Priors (documented):** `thrust_mean.bias=-1.25` (≈0.22 thrust), `rotation_head.bias[hold]=+2.5`. These are random-init biases, **not** guidance parameters/traces. Untrained deterministic with the same priors already solves L0; learning beyond L0 is the scientific target. L0 learning check for s13 requires **retaining ≥50%** rather than beating the prior.

### Gate log (s13, selected)

| Frames | Level | Land rate | Pass |
| ---: | --- | ---: | --- |
| 109,128 | L0 | 1.000 | **PASS** → advance L1 |
| 159k–1.09M | L1 | 0.000 | FAIL (many checks) |

## Phase 4 — Final evaluation

Protocol seeds **chosen before outcomes:** `1000300–1000499` (n=200), schedule `apollolander.starts.v1`, `max_steps=2000` for learned/random/untrained/PR4 (sufficient — they crash/timeout inside the horizon). Guidance re-validated at `max_steps=8000`, `action_repeat=2`.

| Agent | Landing rate | Wilson 95% | Notes |
| --- | ---: | --- | --- |
| trained_deterministic (s13 final) | **0.000** | [0, 0.019] | 200/200 crash |
| trained_stochastic | **0.000** | [0, 0.019] | 200/200 crash |
| random | **0.000** | [0, 0.019] | mostly timeout |
| untrained (same priors) | **0.000** | [0, 0.019] | |
| PR #4 run A final.pt | **0.000** | [0, 0.019] | |
| hand-tuned guidance **REFERENCE ONLY** | **1.000** | [0.981, 1.000] | 200/200 perfect @ 8k steps |

Per-level frozen s13 **final** (after L1 training): **0%** on L0–L4 — L0 skill from the gate-pass checkpoint was **not** retained in `final.pt`. Gate-pass L0 checkpoint still **100%** on L0 val (spot-check).

JSON: `examples/apollolander/rl_curriculum_v3/results/CURR_touchdown_delta_s13/evaluation/final_eval_results.json`  
Eval diagnostic frames (approx): **~2.0M** in the max_steps=2000 pass + **~1.1M** guidance re-run.

## Evidence paths (L0 success — not target-task success)

| Artifact | Path |
| --- | --- |
| First s13 L0 landing ckpt | `…/CURR_touchdown_delta_s13/checkpoints/first_land_L0_8776.pt` |
| L0 gate-pass ckpt | `…/gate_pass_L0_109128.pt` (sha256 `72b447b6…`) |
| s11 first landing | `…/CURR_touchdown_s11/checkpoints/first_land_L0_271136.pt` |
| Browser HUD videos (L0) | `/opt/cursor/artifacts/rl_curriculum_v3/gateL0_seed430011_landed.mp4` (+ hard landings) |
| Parity report | `docs/rl_curriculum_v3/PARITY_REPORT_V2.md` |

## Verified vs inferred

| Claim | Status |
| --- | --- |
| Terminal parity browser↔Node for all four categories | **Verified** |
| Native L0 landings by trained/gate-pass policy | **Verified** (gate eval + browser videos) |
| Target-task (v1) landing by trained NN | **Verified absent** in spot-checks; final JSON confirms when written |
| Family D failure diagnosis | **Supported** by rates + landing rule + action combinatorics |
| GPU would unlock v1 landing | **Inferred** — not demonstrated |

## GPU (RTX 4080 Super) recommendation

Worth it for **multi-seed curriculum continuation past L1** and faster PPO updates, with the understanding that **physics remains CPU-bound** in Node/JS. Not justified solely to reproduce L0 (already achieved on CPU). Pixel/visual RL remains premature until a state policy lands on v1.
