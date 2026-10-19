# Experiment A — frozen baseline configuration

| Setting | Value |
|---------|--------|
| Run name | `ppo_baseline` |
| Env | `LunarLander-v3` |
| Reward | native only |
| Algo | SB3 PPO `MlpPolicy` |
| net_arch | pi=[64,64], vf=[64,64] |
| Timesteps | 1_000_000 |
| n_envs | 4 (`DummyVecEnv`) |
| Seed | 0 |
| Checkpoint freq | 50_000 env steps (÷ n_envs for callback) |
| EvalCallback freq | 25_000 |
| EvalCallback episodes | 10 |
| EvalCallback seed base | `seed + 10_000` = 10000 |
| EvalCallback reward | native |
| Best criterion | highest mean EvalCallback reward → `models/ppo_baseline/best/best_model.zip` |
| Final | `models/ppo_baseline/ppo_lunar_final.zip` |
| Wall time | ~246 s CPU |

**Not retrained for Phase 4.** Held-out Phase 4 test seeds start at **50000** (disjoint from 10000+).
