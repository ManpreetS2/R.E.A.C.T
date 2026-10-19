# Baseline PPO report (before reward shaping)

**Branch:** `experiment/simple-gym-lunarlander`  
**Guide:** Hari (@harixganesh) — *Training an AI to land a rocket with reward shaping*  
**Date:** 2026-10-18

## Phase 1 — environment works

| Item | Result |
|------|--------|
| Env | `LunarLander-v3` (Gymnasium 1.4.0) |
| Random episodes (5) | rewards `[-273.4, -77.5, -333.2, -76.5, -159.6]`, mean **-184.0** |
| Random video | `videos/phase1_random/random_ep0-episode-0.mp4` |

All episodes crashed (terminal −100). Eight observations printed each episode.

## Phase 2 — native-reward PPO

| Item | Value |
|------|--------|
| Algo | Stable-Baselines3 `PPO("MlpPolicy")` |
| Network | 64×64 (pi + vf) |
| Timesteps | 1,000,000 |
| Parallel envs | 4 |
| Seed | 0 |
| Device | CPU |
| Wall time | **~4.1 minutes** |
| Final model | `models/ppo_baseline/ppo_lunar_final.zip` |
| Best checkpoint | `models/ppo_baseline/best/best_model.zip` |

Training curves:

- `outputs/ppo_baseline/learning_curve.png`
- `outputs/ppo_baseline/eval_curve.png`

During training, periodic eval peaked at mean **262.8**. Final logged eval: **241.8 ± 23.0**.

### Held-out evaluation (native reward, 20 episodes, seed 999)

| Model | Mean | Std | Min | Max | Solved (≥200) |
|-------|------|-----|-----|-----|----------------|
| Final | **223.1** | 90.3 | −74.8 | 296.2 | **18/20 (90%)** |
| Best | **250.1** | 22.1 | 216.8 | 296.2 | **20/20 (100%)** |

**First objective met:** genuine landings by a PPO policy (many episodes ≥200).  
**Tutorial goal met:** average native reward ≥200 over ≥10 episodes.

## Phase 3 — videos

| Clip | Path | Notes |
|------|------|-------|
| Random failure | `videos/random_policy/random_policy_ep0-episode-0.mp4` | reward −59 |
| Early (50k steps) | `videos/early_checkpoint/early_checkpoint_ep0-episode-0.mp4` | reward −1646 (authentic early failure) |
| Trained final | `videos/trained_final/trained_final_ep0-episode-0.mp4` | reward ~231 |
| Successful landing | `videos/successful_landing/landing_seed100-episode-0.mp4` | reward **216.95** |

## What we are *not* claiming yet

Reward-shaping experiments (A/B/C) have **not** been trained. Wrappers exist in `rewards.py` for Phase 4 after this baseline.

## Reproduce

```bash
source .venv/bin/activate
pip install -r experiments/simple_lunarlander/requirements.txt
python experiments/simple_lunarlander/scripts/random_play.py --episodes 5 --record-episode 0
python experiments/simple_lunarlander/scripts/train_ppo.py --timesteps 1000000 --run-name ppo_baseline
python experiments/simple_lunarlander/scripts/evaluate.py \
  --model experiments/simple_lunarlander/models/ppo_baseline/best/best_model.zip --episodes 20
```
