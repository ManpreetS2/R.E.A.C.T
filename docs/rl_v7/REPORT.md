# ApolloLander R.E.A.C.T. V7 — Demonstration-Assisted Imitation + Optional PPO

**Label:** `demonstration-assisted` (expert demos for TRAINING ONLY; never at evaluation).

## Corrected milestone verdict (footage audit)

**Not accepted as a learned landing-maneuver milestone.**

On `apollolander.starts.l0_near_v6`, BC scored **40/40 perfect** vs untrained **0/40**, but a **trivial constant policy** (`thrust=0`, `rotation_delta=0`) also **lands 40/40** on the same seeds (**34 perfect + 6 hard**). L0-near spawns upright at ~3–6 px above the pad with low `vy`. BC’s eval actions are **100% delta=0** with **mean thrust ≈ 0.13** — stay-upright soft drop, not a descent/approach skill.

Prior v1 footage was **invalid visual proof**: `frames_png[::2]` dropped the terminal landing frame when the physics-frame count was even, so videos ended on `FLYING` at ALT 0. Fixed v2 videos show `LANDED` + perfect-landing message for ≥2 s after the native outcome. Host↔browser outcome parity holds on the audited seeds.

Full audit: `examples/apollolander/rl_v7/results/V7_imitation/audit/footage_audit.json`.

---

## Preregistration

- Seeds file: `examples/apollolander/rl_v7/preregistered/seeds.json`
- SHA256: `5a9f330be4d55473bbe77f5d3fa739f7a92e7225d31add5725decfe5d3ea6134`
- Committed before demo generation.

## Phase 0 — Translation feasibility

- Learner space: continuous thrust, delta {-10,0,+10}, action_repeat=8
- max_steps_v1=8000 (expert needs ~6k frames)
- V1 translated expert landings: 12/12 (rate=1.000)
- Fidelity (n=4): thrust MAE≈0.0046, rotation MAE≈0.19°, exact agreement≈0.984
- Replay bit-exact: 12/12; L0-near probe 10/10; no representation fallback

## Phase 1 — Demonstrations

- Attempts: 37; failures: 2; **kept: 35** (11 v1 + 24 L0-near), replay-verified
- Demo budget: 299757 / 300000 (target 50–100 not reached under cap)

## Phase 2 — Behavioral cloning

- Train/val by trajectory holdout: 28 / 7 trajectories
- Final val loss ≈ −0.224; val rot acc **0.987**; val thrust MSE ≈ 0.00235
- step0 sha256: `adfacc9bad94960380b4562211de203811ae880717e90d0ba9ba4a3df0e495e8`
- bc sha256: `92b495648420db31babff2e1ddf858470f6b9bcd9028a35b3a30173dc60a019e`
- Integrity (no controller at eval): True; BC env frames: 0

## Phase 3 — Independent gameplay (expert DISABLED)

- **Eval size:** **40** L0-near seeds `703000–703039` (not ≥100). Also untrained v1 n=40 and BC v1 n=23 under diag budget. Seeds **disjoint** from demo seeds (overlap=[]).
- L0-near: untrained 0/40 crash; BC **40/40 perfect**; McNemar b=40,c=0,p≈1.8e-12
- V1: untrained 0/40; BC 0/23
- **Post-audit trivial baseline (same 40 L0-near):** 34 perfect + 6 hard = **40/40 landings**

### BC action stats on L0-near eval

- mean thrust ≈ **0.126**; median ≈ 0.089; max ≈ 0.363
- rotation delta distribution: **{0: 584}** (all hold)

## Phase 4 — PPO from BC

- PPO frames: 249856 / 250000; sha256 `03df86ad681b7b56cbdcefc0942de87961bedc61983b19a34d42b7f54dea4a20`
- Same 40 L0-near: BC 40 perfect; PPO 39 perfect + 1 hard; McNemar on landed b=0,c=0 → preserves
- Does not imply from-scratch discovery

## Footage audit

### Bug in v1 videos

`render_trace_video` wrote `frames_png[::2]`. For 86 physics frames that kept indices 0,2,…,84 and **dropped frame 85 (LANDED)**. Old files retained as `*_v1_buggy.mp4`.

### HUD VS vs perfect/hard

Upstream (`frontend/apollolander/upstream/game.js:792`):

```js
infoDisplay.updateBoxInt('vertSpeed', (lander.vel.y*200));
```

Bridge HUD mirrors this (`browser_rl_bridge.html:259`): `VS = round(vy * 200)`.

- Perfect: `vy < 0.075` → HUD VS < 15 (`game.js:591`)
- Hard landable: `vy < 0.15` with `rotation==0` (`game.js:747`)
- **VS 10 ⇒ vy = 0.05 < 0.075 ⇒ actually perfect** (host `native_outcome.perfect=true`). Not hard.

Fuel 1000→999 during descent is consistent with near-zero thrust; after native perfect landing the bridge awards +50 fuel (v2 last frames show ~1049).

### v2 videos (post-landing hold ≥2 s; status becomes LANDED)

| File | SHA256 |
|---|---|
| `footage/bc_l0_seed703000_landed_v2_posthold.mp4` | `aca9c758caf6b56fa7e4e34f27d3a4715e798ff78112d58f247088c47c3473fb` |
| `footage/bc_l0_seed703001_landed_v2_posthold.mp4` | `6f1a58b0d76ff121a8ea0599703d9dcdbc118b16721fd3f139fb74ce6eb80d37` |
| `footage/bc_l0_seed703002_landed_v2_posthold.mp4` | `7a26dce8e5d267b958ea48cb2860ccbd6caa4d3c24bd8e83315da201f7b39bf3` |
| `footage/ppo_l0_seed703000_landed_v2_posthold.mp4` | `0e81c78c3fabdc19ed0fd31e62ae33f78716084c1014dbb79bf76a224fa539f9` |

Also under `/opt/cursor/artifacts/rl_v7/`. Host↔browser status **parity: matched** on all four (no physics divergence on these seeds).

### Budgets after audit

| Bucket | Cap | Spent |
|---|---:|---:|
| Demo + feasibility + replay | 300000 | 299757 |
| Diagnostics (incl. audit) | 200000 | 193493 |
| PPO fine-tune | 250000 | 249856 |
| BC supervised | 0 | 0 |

## Representation

Same learner space as V6: continuous thrust, delta{-10,0,+10}, ar=8. Expert absolute target quantized to one ±10/0 step per decision; thrust held.

## Artifacts

- Run: `examples/apollolander/rl_v7/results/V7_imitation`
- Audit: `…/audit/footage_audit.json`
- Script: `examples/apollolander/rl_v7/audit_footage_v7.py`
