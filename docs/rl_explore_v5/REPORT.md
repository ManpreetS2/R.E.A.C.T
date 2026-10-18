# Explore v5 — why unguided agents almost never land

**Root cause (numbers):** A valid landing requires `lander.rotation == 0` **and** `lander.vel.y < 0.15` at the instant of pad-aligned contact (`game.js` 747–748). Across **all 65 pad-aligned crash contacts** in this study, the **sole** violated condition was always `rotation_nonzero` (65/65); `vy` was already safe every time. Per-frame random δθ ∈ {−10,0,+10} is a lazy reflecting walk on 19 angle bins with stationary **P(θ=0) = 1/19 ≈ 0.0526** (MC at ~180 steps: **0.055**). The original keyboard path rate-limits rotate to **once / 80 ms** (~4.8 physics frames at 60 Hz) and holding no key leaves `targetRotation` unchanged — behavior the v4 per-frame delta sampler does not mimic.

**Scientific status:** Diagnostics only (no PPO / no gradients). One legitimate native landing occurred under **L0-near + continuous thrust + delta + action_repeat=8 + untrained clean-init** (1/12 perfect). That supports a small follow-up train config (proposed below, **not run**).

Branch: `cursor/apollolander-rl-explore-v5` from clean-v4 `84a4f20`. PR #5 / #6 untouched. Upstream game files under `frontend/apollolander/upstream/` **unchanged**. Diagnostic host snapshot enriched only to record pre-`crash()` attitude (research host, not game physics). Reserved seeds unused. $0.

---

## 1. Landing predicate (unmodified upstream)

`frontend/apollolander/upstream/game.js`:

```739:751:frontend/apollolander/upstream/game.js
			if(line.landable) { 
				// and the lander's bottom is overlapping the line
				if(lander.bottom>=line.p1.y) { 
					
					// and the lander is completely within the line
					if((left>line.p1.x) && (right<line.p2.x)) {
						
						// and we're horizontal and moving slowly
						if((lander.rotation==0) && (lander.vel.y<0.15)) {
							setLanded(line);
						} else {
							setCrashed(); 
						} 
```

Perfect vs hard scoring (`setLanded`):

```591:600:frontend/apollolander/upstream/game.js
	if(lander.vel.y<0.075) { 
		points = 50 * multiplier; 
		// show message - "a perfect landing"; 
		infoDisplay.showGameInfo("YOU DID IT!\nPERFECT LANDING\n" + points + " POINTS");
		lander.fuel+=50;
	} else {
		points = 15 * multiplier; 
		// YOU LANDED HARD
		infoDisplay.showGameInfo("HARD LANDING<br>YOU ARE STRANDED<br>" + points + " POINTS");
```

**Conditions at contact:** (i) landable line, (ii) bottom on pad, (iii) feet fully inside pad x-range, (iv) `rotation == 0` exactly, (v) `vy < 0.15`. Perfect additionally needs `vy < 0.075`.

---

## 2. Player controls vs continuous / delta adapter

| Upstream control | Code | Rate / quantization |
| --- | --- | --- |
| Thrust key UP / space | `lander.thrust(1\|0)` (`game.js` 101–104) | Binary while held |
| Touch thrust | `lander.thrust(0..1)` (`game.js` 234) | Continuous |
| Keyboard rotate | `lander.rotate(±1)` → **±15°** on `targetRotation` (`Lander.js` 60–68) | **Min 80 ms** between changes |
| Touch / RL absolute | `lander.setRotation(angle)` (`Lander.js` 71–74) | Snap to **10°** in [−90,90] |
| Attitude dynamics | `rotation += (target−rotation)*0.3` (`Lander.js` 98–99) | Lerp each frame; non-integer mid-settle |

Game loop: **60 fps** (`game.js` 15–16).

**RL adapter (v3/v4):** `ContinuousThrustActorCritic` + `step_command` → `thrust∈[0,1]` and `setRotation` each physics step (or every `action_repeat` steps). Delta mode accumulates {−10,0,+10} into the commanded absolute angle (`continuous_policy.py` `ROTATION_DELTAS`, clean trainer / explore harness).

**Mismatch:** Keyboard play holds attitude by *not* calling `rotate` (idle). Per-frame uniform δθ samples a new tilt command at 60 Hz — ~12× faster than the 80 ms keyboard gate — so `rotation==0` at contact is rare unless hold is sampled for many consecutive decisions.

### Analytical + offline confirmation (0 physics frames)

`examples/apollolander/rl_explore_v5/results/EXPLORE_v5/rotation_hold_analysis.json`:

| Model | P(θ=0) |
| --- | ---: |
| Stationary lazy walk on 19 bins | **0.05263** (=1/19) |
| MC after 180 steps, p_hold=1/3 | **0.0554** (5000 trials) |
| Effective decisions if ar=8 (~22 decisions) | MC **~0.102** |
| Effective decisions if ar=16 (~11 decisions) | MC **~0.147** |

---

## 3. Near-miss definition (fixed before outcomes)

- **Pad-aligned contact:** `landable_contact ∧ within_pad` (feet fully on a landable pad).
- **Near-miss:** pad-aligned contact that is **not** a landing, with **exactly one** of `{rotation==0, vy<0.15}` failed, within tolerance `|rotation|≤10°` or `vy<0.30` respectively.
- Success is **only** native perfect/hard status — never shaped reward.

---

## 4–6. Empirical matrix (≤100k diagnostic frames)

Config: n=12 episodes/cell, `max_steps=400`, seeds from `530000+`, matched across comparisons. Policies: uniform random; untrained = `reset_parameters_clean` (orthogonal, zero bias, **no priors**). Open-loop soft-hold is **feasibility only**.

**Diagnostic frames used: 89,140 / 100,000** (remaining 10,860).

### Comparison table

| Start | Representation | Policy | Land (P/H) | Near | Pad-aligned | Crash | Timeout | Top violation |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| L0 | cont_delta_ar1 | random | 0 (0/0) | 1 | 6 | 6 | 6 | timeout_no_contact |
| L0 | cont_delta_ar4 | random | 0 | 0 | 2 | 2 | 10 | timeout_no_contact |
| L0 | cont_delta_ar8 | random | 0 | 0 | 2 | 2 | 10 | timeout_no_contact |
| L0 | cont_delta_ar16 | random | 0 | 0 | 3 | 3 | 9 | timeout_no_contact |
| L0 | disc4_delta_ar8 | random | 0 | 0 | 6 | 6 | 6 | timeout_no_contact |
| L0 | cont_absolute_ar8 | random | 0 | 0 | 1 | 1 | 11 | timeout_no_contact |
| L0 | cont_holdheavy_ar8 | random | 0 | 0 | 0 | 0 | 12 | timeout_no_contact |
| L0_near | cont_delta_ar1 | random | 0 | 1 | 9 | 9 | 3 | **rotation_nonzero** |
| L0_near | cont_delta_ar4 | random | 0 | 0 | 3 | 3 | 9 | timeout_no_contact |
| L0_near | cont_delta_ar8 | random | 0 | 0 | 4 | 4 | 8 | timeout_no_contact |
| L0_near | cont_delta_ar16 | random | 0 | 0 | 1 | 1 | 11 | timeout_no_contact |
| L0_near | disc4_delta_ar8 | random | 0 | 0 | 2 | 2 | 10 | timeout_no_contact |
| L0_near | cont_absolute_ar8 | random | 0 | 0 | 4 | 4 | 8 | timeout_no_contact |
| L0_near | cont_holdheavy_ar8 | random | 0 | 0 | 0 | 0 | 12 | timeout_no_contact |
| L0 | cont_delta_ar1 | untrained | 0 | 0 | 2 | 2 | 10 | timeout_no_contact |
| L0 | cont_delta_ar8 | untrained | 0 | 0 | 0 | 0 | 12 | timeout_no_contact |
| L0 | cont_holdheavy_ar8 | untrained | 0 | 0 | 3 | 3 | 9 | timeout_no_contact |
| L0_near | cont_delta_ar1 | untrained | 0 | 0 | 3 | 3 | 9 | timeout_no_contact |
| L0_near | **cont_delta_ar8** | **untrained** | **1 (1/0)** | **1** | **12** | 11 | 0 | **rotation_nonzero** |
| L0_near | cont_holdheavy_ar8 | untrained | 0 | 0 | 3 | 3 | 9 | timeout_no_contact |

Wilson 95% for the landing cell (1/12): rate **0.083**, CI **[0.015, 0.354]**.

### Violation census (all pad-aligned crashes)

| Condition | Count among pad-aligned crashes |
| --- | ---: |
| `rotation_nonzero` only | **65 / 65** |
| `vy_too_fast` | **0 / 65** |
| `not_within_pad` (among pad-aligned by definition) | 0 |

So once the craft is on the pad with feet inside, **attitude is the only blocker**. Timeouts dominate many cells because random thrust often prevents timely contact.

### Player mapping of representations

| Rep | Maps to original controls |
| --- | --- |
| cont_delta_ar{k} | Touch continuous thrust + `setRotation` ±10°/0, command held k frames (k=4≈80 ms keyboard gate) |
| disc4_delta_ar8 | Coarsened touch thrust {0,0.25,0.5,1} + delta setRotation ×8 |
| cont_absolute_ar8 | Touch absolute `setRotation` to a 10° bin, held 8 frames |
| cont_holdheavy_ar8 | Layout {−10,0,0,0,+10} → 60% hold by **action layout** (release arrows), not init bias |

### Open-loop feasibility (labeled, not a policy)

Soft thrust 0.22 + hold 0: **L0 8/8 land, L0-near 8/8 land** — task is physically solvable; exploration/control timing is the bottleneck.

### Documented landing event

- Cell: `L0_near` / `cont_delta_ar8` / `untrained`
- Seed: **548003** (non-reserved)
- Outcome: **perfect** (`rotation=0`, `vy≈0.019`, pad-aligned, designated)
- Frame: 274

---

## 7–10. Constraints honored

- No priors, no autopilot/demo/expert weights, no training.
- Open-loop only as labeled feasibility.
- Upstream `frontend/apollolander/upstream/` unmodified; scoring/gravity/collision unchanged.
- Seeds `2000000–2000015` unused; $0 spend.
- Research host records pre-`crash()` contact pose (otherwise `Lander.crash()` zeroes rotation and corrupts violation logs).

---

## Recommended next training config (**not run**)

Because a clean untrained policy already produced a **native perfect landing** on L0-near with `action_repeat=8` delta controls, one small PPO follow-up is justified:

| Knob | Value |
| --- | --- |
| Start | L0-near (3–6 px above pad, upright, low vel) |
| Actions | Continuous thrust + delta {−10,0,+10}, **action_repeat=8** |
| Init | `reset_parameters_clean` (orthogonal, zero bias); priors **off** |
| Baseline | Matched step-0 checkpoint, bit-exact equivalence check |
| Horizon | `max_steps=400` train + eval |
| Train budget | ≤ **250,000** physics frames |
| Diagnostic budget | ≤ **100,000** (step-0 + random + frozen evals) |
| Success | Frozen ckpt beats step-0 on fixed val seeds: Wilson non-overlap **or** two-proportion p&lt;0.01; never from one stochastic landing alone |

**Frame cost:** ~250k train + ~100k diagnostic ≈ **350k** total physics frames.

Rationale: L0-near + ar8 raised pad-aligned contact to **12/12** for untrained (vs sparse contact / timeouts on L0 ar1). Remaining failures are almost purely `rotation≠0` with already-safe `vy` — a learnable hold-attitude signal if landings/near-misses enter the buffer.

---

## Artifact paths

- Cells: `examples/apollolander/rl_explore_v5/results/EXPLORE_v5/logs/explore_cells.json`
- Full episodes: `…/explore_cells_full.json`
- Rotation analysis: `…/rotation_hold_analysis.json`
- Budget: `…/diagnostic_budget.json` (spent **89140**)
- Harness: `examples/apollolander/rl_explore_v5/run_explore_v5.py`
