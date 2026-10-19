# A/B/C/D execution manifest (preflight freeze)

**Status:** Ready for approval. **Do not execute the 12 PPO runs** without a separate GO.

## Study geometry

| Item | Value |
|------|------:|
| Conditions | A, B, C, D |
| Train seeds | 0, 1, 2 |
| Runs | **12** |
| Physics frames / run | **≤ 200 000** (hard guard) |
| Total train frames | **≤ 2 400 000** |
| Paid infrastructure | **None** |
| Episode max frames | 2000 |
| action_repeat | 4 |
| Start | `sh_contact` (`short_horizon.v1`) |
| Obs / actions | 10-D / `MultiDiscrete([5,3])` |

## Reward modes

| Cond | `reward_mode` | Notes |
|------|---------------|-------|
| A | `abcd_a` | A′ α=10, c=0.005 |
| B | `abcd_b` | A + hover +1 |
| C | `abcd_c` | γ-corrected Φ_C |
| D | `abcd_d` | terminals only (same ±100/40 scale) |

See `ABCD_REWARD_FREEZE.md`.

## Train start streams (`auto_seed_base`)

| | seed 0 | seed 1 | seed 2 |
|--|-------:|-------:|-------:|
| **A** | 900 000 | 910 000 | 920 000 |
| **B** | 930 000 | 940 000 | 950 000 |
| **C** | 960 000 | 970 000 | 980 000 |
| **D** | 990 000 | 1 000 000 | 1 010 000 |

Helper: `env.seeds.abcd_train_auto_seed_base(condition, train_seed)`.

## Evaluation pools (preregistered)

| Pool | Seeds | Use |
|------|-------|-----|
| `ABCD_AUDIT_SEEDS` | 55 000–55 029 | Reward audit only (done) |
| `ABCD_DEV_SEEDS` | 700 000–700 049 (n=50) | Checkpoint selection **only** |
| `ABCD_HELD_OUT_SEEDS` | 800 000–800 099 (n=100) | **Untouched** until after selection |

V3-40k remains a **historical reference**, not Condition A.

## Selection & reporting (frozen)

1. Checkpoints every **5 000** Gym steps + step0 + final.  
2. Select on DEV n=50: max native land rate → min timeout rate → min mean frames.  
3. Report **selected** and **final** on held-out n=100 for every (condition × train seed).  
4. Primary outcome: native (perfect+hard) land fraction on held-out.  
5. Also: perfect, hard, crash, timeout, reascent, duration, fuel.  
6. Per-seed rates + uncertainty **across the 3 training seeds** (not 300 pseudo-replicates).  
7. Paired start comparisons across conditions where applicable.  
8. Record 0% results honestly; no hidden retries / replacement.

## Paths (create before any launch)

```
experiments/apollo_gymnasium/
  models/abcd_{A,B,C,D}_seed{0,1,2}/
  outputs/abcd_{A,B,C,D}_seed{0,1,2}/
  logs/abcd_{A,B,C,D}_seed{0,1,2}/
```

`scripts/run_v5_train.sh` pattern: `mkdir -p` outputs/logs/models **before** `tee`; `set -o pipefail`.

## Reproducible train command (template — DO NOT RUN YET)

```bash
# Example: condition A, seed 0
mkdir -p experiments/apollo_gymnasium/{models,outputs,logs}/abcd_A_seed0
.venv/bin/python experiments/apollo_gymnasium/scripts/train_ppo.py \
  --run-name abcd_A_seed0 \
  --start-template sh_contact \
  --reward-mode abcd_a \
  --potential-scale 10.0 \
  --time-cost 0.005 \
  --timeout-as-terminated \
  --seed 0 \
  --action-repeat 4 \
  --episode-max-frames 2000 \
  --max-physics-frames 200000 \
  --auto-seed-base 900000 \
  --checkpoint-every-gym-steps 5000 \
  --port 20000
```

Port formula (suggested): `20000 + cond_index*10 + train_seed`.

## Budget guard

`PhysicsBudgetCallback` refuses the next Gym step when `frames + action_repeat > cap`.  
Unit-tested in `scripts/abcd_fairness_check.py`.

## Resume / recovery

- Each run writes `outputs/<run>/train_summary.json` with `actual_physics_frames`.  
- If a run dies mid-flight: **do not** silently continue past 200k; restart that run from random init with the same seed (document restart in the run log).  
- Never borrow frames from another condition/seed.

## Hashes

After any future training GO, record SHA-256 of step0, every checkpoint, final, `run_config.json`, and selection JSON in `outputs/abcd_study/FREEZE_MANIFEST.json`.

## Preflight artifacts (this freeze)

| File | Role |
|------|------|
| `ABCD_REWARD_FREEZE.md` | Formulas |
| `outputs/abcd_preflight/ABCD_REWARD_AUDIT.md` | Scale audit |
| `outputs/abcd_preflight/ABCD_FAIRNESS.json` | Fairness / leakage |
| `tests/test_abcd_rewards.py` | Unit tests |

**Experimental budget remaining for study training: 2.4M frames — unused.**
