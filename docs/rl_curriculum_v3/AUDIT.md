# Curriculum v3 audit — claims vs evidence (s13)

**Verdict:** The earlier headline that “L0 learning is real” is **not supported**. `CURR_touchdown_delta_s13` used human-coded **output-layer init priors** that implement a soft-thrust + hold-attitude soft-drop; the frozen L0 basic learning check at 259,144 frames **failed** (0/40, `passed: false`); training continued because of an early-stop bug; the random/untrained baselines used for the check were **not** evaluated with the same priors/rotation mode as the trained policy.

No logs were deleted. No further training or diagnostic control runs were executed for this audit.

---

## (a) What `soft_thrust_prior` and `hold_attitude_prior` do

**Classification: output-layer (and std) initialization biases.**  
They are **not** residual policies, **not** action-space transforms, **not** runtime post-network action biases, and **not** loaded guidance parameters/traces.

Code (`src/rewardbench/rl/continuous_policy.py`):

```61:79:src/rewardbench/rl/continuous_policy.py
    def reset_parameters(self) -> None:
        for module in self.modules():
            if isinstance(module, nn.Linear):
                nn.init.orthogonal_(module.weight, gain=1.0)
                nn.init.constant_(module.bias, 0.0)
        nn.init.orthogonal_(self.thrust_mean.weight, gain=0.01)
        nn.init.orthogonal_(self.rotation_head.weight, gain=0.01)
        # Documented random-init priors (NOT guidance parameters / traces):
        # soft thrust ~0.22 and hold-attitude (delta 0) so L0 episodes can
        # occasionally contact upright before the policy collapses to hover.
        if self.soft_thrust_prior:
            nn.init.constant_(self.thrust_mean.bias, -1.25)  # sigmoid ≈ 0.22
            with torch.no_grad():
                self.thrust_log_std.fill_(-0.5)
        if self.hold_attitude_prior and self.rotation_mode == "delta":
            # ROTATION_DELTAS = (-10, 0, 10) → index 1 is hold.
            with torch.no_grad():
                self.rotation_head.bias.zero_()
                self.rotation_head.bias[1] = 2.5
```

| Flag | Effect at init |
| --- | --- |
| `soft_thrust_prior` | `thrust_mean.bias = -1.25` → deterministic thrust `sigmoid(-1.25) ≈ 0.22`; `thrust_log_std = -0.5` |
| `hold_attitude_prior` (delta mode only) | `rotation_head.bias = [0, 2.5, 0]` → argmax = hold (`Δrotation = 0`) |

Head weights use `gain=0.01`, so early deterministic actions are **bias-dominated**. s13 config enables both with `rotation_mode: delta` (`configs/CURR_touchdown_delta_s13.yaml` lines 30–32; `config_snapshot.yaml` matches). Checkpoint `step0.pt` still has exactly those biases (`thrust_mean.bias=-1.25`, `rotation_head.bias=[0,2.5,0]`, `thrust_log_std=-0.5`).

### Does the prior alone land at L0?

**Not measured in retained logs.** The flag `prior_solves_l0: true` in `l0_learning_check.json` is **not** an empirical rate. It is set solely from config:

```674:680:examples/apollolander/rl_curriculum_v3/train_curriculum.py
                prior_solves_l0 = bool(self.cfg.soft_thrust_prior and self.cfg.hold_attitude_prior)
                if prior_solves_l0:
                    ok = check["landing_rate"] >= 0.5
                    reasons.append("prior_solves_l0_require_retain_ge_0.5")
                check["passed"] = ok
                check["reasons"] = reasons
                check["prior_solves_l0"] = prior_solves_l0
```

| Seed set | Prior-alone (untrained NN + same priors/delta, deterministic) L0 landing rate |
| --- | --- |
| Gate seeds (`val_seed_start=430000`, n=40) | **Not in logs** |
| Baseline seeds (`seed_start=300000`, n=200) | **Not in logs** (baseline “untrained” cell used **different** policy — see (b)) |

**Cost to settle (a) — do not run:**

| Measurement | Episodes × horizon | Approx. physics frames |
| --- | ---: | ---: |
| Prior-only det on gate seeds | 40 × `max_steps=400` | ≤ 16,000 (likely ~7–10k if soft-drop terminates early; L0 check mean duration was 177) |
| Prior-only det on baseline seeds | 200 × 400 | ≤ 80,000 |
| Same at baseline’s 1200 horizon | 200 × 1200 | ≤ 240,000 |
| Clean **no-prior** train control to L0 check (`l0_learning_check_frames=250000`, one seed) | training only | **~250,000** train frames (+ ~40×400 gate diag) |

---

## (b) Was the “untrained network” baseline evaluated with the same priors and rotation mode?

**No. The comparison is invalid for s13.**

`measure_baselines.py` builds:

```160:164:examples/apollolander/rl_curriculum_v3/measure_baselines.py
    untrained = ContinuousThrustActorCritic(hidden=128).to(device)
    untrained.eval()
    # Fixed documented untrained init seed (not a training seed).
    torch.manual_seed(42)
    untrained.reset_parameters()
```

Defaults on `ContinuousThrustActorCritic`: `rotation_mode="absolute"`, `soft_thrust_prior=False`, `hold_attitude_prior=False` (`continuous_policy.py` lines 34–36). So the baseline untrained policy is **19-way absolute rotation, no soft-thrust/hold priors**.

s13 trained policy: `rotation_mode=delta`, both priors **true**.

Additional mismatch: baselines used `max_steps=1200` (`baseline_rates.json`); training/gates used `max_steps=400` (`CURR_touchdown_delta_s13.yaml` line 19). Baseline L0 untrained/random: **0/200**, all **timeout** at duration 1200 — not comparable to train episodes that crash/land inside 400 steps.

Those invalid baseline rows are what `l0_learning_check.json` embeds as `baseline_random` / `baseline_untrained`.

---

## (c) Gate 40/40 at 109k vs learning check 0/40 at 259k; plot vs `first_landings`

### Gate vs learning check

| Event | Frames | Level being trained | Frozen eval | Result |
| --- | ---: | --- | --- | --- |
| L0 gate | **109,128** | L0 | L0 val seeds 430000+, det, n=40 | **40/40** land (`gate_log.json`) → advance to L1 |
| L0 learning check | **259,144** | **L1** (since 109,128) | L0 val seeds, det, n=40 | **0/40** crash, `passed: false` |

Mechanism:

1. Gate success advances `level_idx` and continues PPO on **L1** (`maybe_gate` / `level_history.jsonl` advance at 109,128).
2. The learning check always re-evaluates **L0** with the **current** frozen weights (`train_curriculum.py` lines 644–649), regardless of current level.
3. After ~150k frames of L1 training, L0 skill is gone: check is 0/40 crashes (`l0_learning_check.json`). `final.pt` also shows **0%** on L0–L4 in final eval — L0 gate-pass skill was not retained.

So 40/40 at 109k and 0/40 at 259k are both consistent: a transient L0-capable checkpoint, then collapse under L1 updates. That does **not** establish learning above the prior (see (e)); the check’s own retain rule failed.

### Plot zero train landings vs `first_landings` at 8,776

- `logs/first_landings.jsonl` records one stochastic **training** landing at **8,776** (pre-resume session), and `checkpoints/first_land_L0_8776.pt` exists.
- `logs/resume_events.jsonl`: training was resumed from that checkpoint (`global_step: 8776`).
- `learning_curve.csv` starts at **9,772** with **0** `landed=True` rows over the whole file (2,991 rows). L0 segment in the CSV: **510 crashes, 0 landings**.
- `train_summary.json` has `first_landing_frames` all **null**: `load_checkpoint` restores weights/step/level but **not** `_first_landing_frames` (lines 235–250 vs init at 136), so the resume process never re-records the pre-resume landing into the summary.

Why the CSV misses the 8,776 landing: episode metrics are buffered and flushed to CSV only in `_flush_metrics` (on periodic checkpoints / end), not on the first-landing checkpoint path. The killed pre-resume session likely never flushed rows before 8,776; after resume, append starts with later episodes. The plot (`plot_runs.py` reads `learning_curve.csv`) therefore shows **0% train landing rate** and crash-dominated L0 — while `first_landings.jsonl` preserves the earlier one-off event.

---

## (d) Why training did not stop when the learning check failed

The brief required stop on L0 basic learning check failure. Code only breaks if the check fails **and** the trainer is still on level 0:

```684:686:examples/apollolander/rl_curriculum_v3/train_curriculum.py
                if not ok and self.level_idx == 0:
                    early_stop_reason = "l0_basic_learning_check_failed"
                    break
```

Timeline for s13:

1. L0 gate passed at 109,128 → `level_idx = 1`.
2. Check fired at 259,144 → `passed: false` (reasons include `prior_solves_l0_require_retain_ge_0.5`).
3. Because `level_idx == 1`, the `break` was **skipped**.
4. Training continued to **1,090,632** frames; `train_summary.json` has `"early_stop_reason": null`.

Contrast: s11/s12 failed the check while still on L0 and set `early_stop_reason: "l0_basic_learning_check_failed"`.

---

## (e) Under the owner’s rule — does any trained landing count as genuine learning?

**No — not as evidence of genuine learning from experience under a no-human-coded-guidance rule.**

Honest re-evaluation:

1. Soft-thrust + hold-attitude init is a **human-coded soft-drop / attitude-hold maneuver** wired into the network’s output layer. Calling it “not guidance” because it is not the sealed guidance controller does not satisfy a rule against human-coded guidance or scripted maneuver parts.
2. The L0 learning check — the run’s own criterion when priors are on — **failed** at 259k (0/40, retain ≥50% not met).
3. Stochastic training curve after resume shows **0** L0 landings; the single `first_landings` event is a rare sample under a prior-shaped action distribution, not a sustained learned policy.
4. Gate 40/40 is deterministic eval of a prior-dominated head (biases at `gate_pass_L0_109128.pt` still ≈ init: thrust bias −1.254 vs −1.25, hold bias 2.505 vs 2.5). That is not a demonstration of beating an matched untrained-prior baseline (never measured — (a)/(b)).
5. Target-task success (native land on normal `apollolander.starts.v1`) is **0/200**.

**What still stands:** parity V2; Family D / exploration diagnosis; s11/s12 early stops; s13 logs as an **invalidated** prior-contaminated run. **What does not stand:** “L0 learning is real,” or counting s13 gate/train landings as curriculum learning success.

---

## (f) Why diagnostic frames (~6.5M+) far exceeded the ~1M target

Approximate accounting (physics frames, diagnostics only — not training):

| Source | Frames | Notes |
| --- | ---: | --- |
| `baseline_rates.json` | **3,358,817** | 200 eps × 7 schedules × 2 modes; `max_steps=1200`; mostly full-horizon timeouts |
| Final eval `total_diagnostic_frames` | **3,201,575** | Includes guidance @ 8k steps (~1.16M) + invalid 2k guidance pass (400k) + learned/random/untrained/PR4 |
| s13 gate checks | **314,918** | Sum of `diagnostic_frames` in `gate_log.json` |
| s13 L0 learning check | **7,092** | |
| Parity traces | **~36,674** | REPORT |

**Total ≈ 6.9M** diagnostic frames.

**Why:** no hard diagnostic budget. Phase-2 baselines alone used 1200-step episodes that timeout for random/untrained (~3.36M). Final eval then spent another ~3.2M (especially guidance horizons). Training `max_steps` was 400, but diagnostics were not aligned to that. The ~1M diagnostic target was not enforced in code or ops.

---

## Report / PR corrections required (this audit)

- Remove or invert any headline that L0 learning is real / that gate 40/40 proves learning vs untrained.
- State priors are output-layer init biases implementing soft-drop + hold.
- State learning check **failed**; early-stop bug allowed continuation.
- State baseline comparison is invalid (mode/priors/horizon).
- Keep all result logs and checkpoints under `results/CURR_touchdown_delta_s13/` unchanged.
