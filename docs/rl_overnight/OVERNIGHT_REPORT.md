# Overnight RL report — ApolloLander (original upstream)

**Verdict (outcomes first):** Across **~18.0M** new physics frames of genuine CPU PPO
on the **verified original upstream** ApolloLander engine, **no trained network
achieved a verified native landing** on training, dev-validation, or held-out
test starts (`1000100–1000299`, n=200). This is a **negative result** with
infrastructure and evidence preserved. A hand-tuned guidance heuristic
(reference only) lands ~31/32 on curriculum-easy starts, proving the env can
classify native landings — the failure is learning, not the backend.

| Item | Value |
| --- | --- |
| Branch | `cursor/apollolander-rl-overnight-v2` |
| PR | https://github.com/ManpreetS2/R.E.A.C.T/pull/4 |
| Base pilot | `cursor/apollolander-rl-pilot-2f7b` @ `efb025f` |
| Upstream | Seb Lee-Delisle ApolloLander `0da09dc` (hashes MATCH) |
| Parity gate | **PASS** (Node-vm ↔ Chromium; exact terminals) |
| Physics budget used | ~18,020,352 frames (cap 30M) |
| Peak hardware | 4 CPU, ~15 GiB RAM, $0 |

---

## 1. Original-game integration

- **What ran:** Unmodified `frontend/apollolander/upstream/{Lander,Landscape,perlin,Vector2}.js`
  loaded in Node via `vm` (`frontend/apollolander/rl_overnight/upstream_engine_host.js`).
- **Collision/scoring:** Executable copies of `game.js` `checkCollisions` /
  `setLanded` / `setCrashed` living **outside** `upstream/`.
- **Browser path:** `browser_rl_bridge.html` + Playwright Chromium for parity and videos.
- **Label:** ORIGINAL upstream headless wrapper — **not** an unverified substitute.
- **Evidence:** `docs/rl_overnight/PARITY_REPORT.md`, `results/parity_raw.json`.
- **Custom physics.js vs upstream:** Bit-identical on flying trajectories @1e-9;
  one post-crash rotation mismatch (`lander.crash()` zeros rotation upstream).
  Pilot’s custom sim must not be called “original game”; overnight training used upstream.

**Action mapping (player controls only):**

| Action | API |
| --- | --- |
| Thrust ∈ [0,1] | `lander.thrust` (keyboard 0/1; touch continuous) |
| Rotation ∈ [-90,90]/10° | `lander.setRotation` |
| Not exposed | `abort`, key-rate-limited `rotate(±1)` (setRotation covers capability) |

---

## 2. Pilot failure analysis

See `docs/rl_overnight/PILOT_ROOT_CAUSE.md`.

**Proven:** GAE ignored timeout bootstrap; 32k steps/s was total÷continued-wall
inflation; action_repeat config=2 vs throughput bench=4; timeout (−25) ≪ crash (−100)
encourages hover; entropy did not collapse; train seeds did not overlap 0–31.

**Fix applied:** truncation bootstrap + KL/clipfrac/grad/value logging.

---

## 3. Completed runs

| Run ID | Family | Algo/config | Seed | n_envs | Physics frames | Wall (s) | Episodes | Best/final mean R | Land | Crash | Timeout | Checkpoint | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| smoke_A | A | PPO reproduce smoke | 0 | 4 | 16,384 | 3 | 0 | n/a | 0 | 0 | 0 | `results/smoke_A/checkpoints/final.pt` | done |
| A_reproduce_upstream_s0 | A | PPO lr3e-4 ent0.02 ar2 | 0 | 4 | 3,000,320 | 429 | 1416 | ≈−104 | 0 | 1395 | 21 | `.../A_reproduce_upstream_s0/checkpoints/final.pt` | done |
| B_stable_lowlr_s1 | B | PPO lr1e-4 ent0.05 | 1 | 4 | 3,000,320 | 431 | ~1505 | ≈−103 | 0 | 1493 | 12 | `.../B_stable_lowlr_s1/checkpoints/final.pt` | done |
| C_timeout_eq_crash_s2 | C | timeout=crash, sparse | 2 | 4 | 3,000,320 | 413 | 372 | −100 | 0 | 0 | 372 | `.../C_timeout_eq_crash_s2/checkpoints/final.pt` | done |
| C_sparse_s3 | C | sparse terminal only | 3 | 4 | 2,000,896 | 278 | 272 | ≈−25 | 0 | 36 | 236 | `.../C_sparse_s3/checkpoints/final.pt` | done |
| C_step_cost_s6 | C | step_cost + timeout=crash | 6 | 4 | 4,001,792 | 688 | 500 | −180 | 0 | 0 | 500 | `.../C_step_cost_s6/checkpoints/final.pt` | done |
| D_curriculum_easy_s7 | D | curriculum easy + step_cost | 7 | 4 | 3,000,320 | 431 | 926 | ≈−132 | 0 | 238 | 688 | `.../D_curriculum_easy_s7/checkpoints/final.pt` | done |

All policies: **random weight init**; no demos; no guidance in training.

---

## 4. Plots

Per-run under `examples/apollolander/rl_overnight/results/<run>/plots/` and
`/opt/cursor/artifacts/rl_overnight/`:

- `reward.png`, `outcomes.png`, `fuel.png`, `stability.png`

---

## 5. Videos

Original upstream renderer (Chromium bridge), manifests beside each file under
`/opt/cursor/artifacts/rl_overnight/` (not git). Seeds chosen before outcomes.
Replay outcomes matched env outcomes (`outcome_match: true`).

| File | Checkpoint | Seed | Native outcome |
| --- | --- | ---: | --- |
| `random_seed1000100.mp4` | random open-loop | 1000100 | (see manifest) |
| `A_step0_seed1000100.mp4` | A step0 | 1000100 | crashed |
| `A_step1500000_seed1000101.mp4` | A mid | 1000101 | crashed |
| `A_final_seed1000102.mp4` | A final | 1000102 | crashed |
| `A_final_fail_seed1000150.mp4` | A final | 1000150 | crashed |
| `D_final_seed5000.mp4` | D final | 5000 | crashed |

## 5b. Held-out test (n=200, seeds 1000100–1000299)

| Policy | Land (Wilson 95%) | Crash | Timeout | Mean R |
| --- | --- | ---: | ---: | ---: |
| random open-loop | 0.000 [0, 0.019] | 0.000 | 1.000 | −89.07 |
| untrained net | 0.000 [0, 0.019] | 0.520 | 0.480 | −93.47 |
| A step0 | 0.000 [0, 0.019] | 1.000 | 0.000 | −100.01 |
| A final | 0.000 [0, 0.019] | 1.000 | 0.000 | −101.96 |
| C_step_cost final | 0.000 [0, 0.019] | 0.000 | 1.000 | −104.40 |
| D curriculum final | 0.000 [0, 0.019] | 1.000 | 0.000 | −138.38 |

Pilot-comparison seeds `1000000–1000031` (not sealed test): A final land=0, crash=1.

---

## 6. Checkpoints & scripts

- Init + periodic + final `.pt` and `.sha256.json` in each run dir.
- Train: `examples/apollolander/rl_overnight/train.py`
- Eval: `examples/apollolander/rl_overnight/evaluate.py`
- Videos: `examples/apollolander/rl_overnight/record_videos.py`
- Parity: `examples/apollolander/rl_overnight/parity_check.py`
- Held-out test seeds **frozen before eval:** `1000100–1000299`
- Sealed never-touch: `2000000–2000015`
- Pilot comparison only (not sealed test): `1000000–1000031`

---

## 7. Scientific conclusion

1. **Did any net learn to land?** **No.** Zero native landings in ~18M frames
   across A/B/C/D on the original engine.
2. **Generalization?** N/A — no successful policy to transfer. Dev-val and
   held-out rates are 0 where measured.
3. **Did shaping mislead?** **Yes, in the pilot and Family A/B:** timeout ≪ crash
   produced hover/timeout modes. Family C equalizing timeout to crash or adding
   step cost removed cheap hover rewards but still yielded **no landings**
   (agents timed out paying the full cost, or crashed without contacting the pad
   correctly). Shaped return alone never indicated success.
4. **Parallel training:** Upstream-vm ~9–12k phys frames/s; with PPO ~5–7k/s at
   `n_envs=4`. Two trainers on 4 cores remained productive; three + evals
   oversubscribed.
5. **Unresolved / next:**
   - Sparse exact landing under Discrete(95) may need ≫30M frames or continuous actions.
   - Curriculum easy starts still failed — try denser success bonus on first pad
     contact, or continuous thrust/rotation matching touch controls.
   - GPU handoff: accelerate PPO updates only; JS physics stays CPU
     (`docs/rl_overnight/WINDOWS_GPU_HANDOFF.md`).
   - Screenshot/pixel RL proposed after a state policy can land.

**Guidance (REFERENCE ONLY, not a trained net):** 31/32 landings on curriculum-easy
seeds with a hand heuristic — confirms verifier/env, not that RL learned.

---

## 8. Verified vs inferred

| Claim | Status |
| --- | --- |
| Upstream file hashes = GitHub `0da09dc` | **Verified** |
| Node-vm ↔ browser parity | **Verified PASS** |
| GAE timeout bootstrap bug in pilot | **Verified** |
| 0 RL landings this overnight | **Verified** (train logs + evals) |
| Hovering encouraged by timeout≪crash | **Verified** (reward def + episode mix) |
| Need ≫30M frames or different action space | **Inferred** |
| Pixel RL will succeed next | **Speculative** — not claimed |
