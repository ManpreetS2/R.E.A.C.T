# ApolloLander Gymnasium Research Edition

Wraps **Seb Lee-Delisle’s original ApolloLander** (unchanged under
`frontend/apollolander/upstream/`) with a minimal Gymnasium API, then trains
Stable-Baselines3 PPO from random weights on **numerical** observations.

MIT game · https://github.com/sebleedelisle/apollolander · see
`frontend/apollolander/THIRD_PARTY.md`.

This is **not** Gymnasium LunarLander and **not** the custom Node
`experiment/physics.js` simulator.

## Layout

| Path | Role |
|------|------|
| `env/apollo_env.py` | Gymnasium `ApolloLanderGym` |
| `env/host.py` | Static server + Playwright page |
| `env/starts.py` | Progressive research starts |
| `env/controllers.py` | no-op / random / reference (feasibility only) |
| `OBSERVATIONS.md` | Observation & action units |
| `REWARD_DEFINITIONS.md` | Training rewards A/B/C/D (D gated) |
| `scripts/` | Parity, start gate, train, evaluate |

## Quick start

```bash
# from repo root
.venv/bin/python experiments/apollo_gymnasium/scripts/parity_check.py
.venv/bin/python experiments/apollo_gymnasium/scripts/probe_starts.py
.venv/bin/python experiments/apollo_gymnasium/scripts/train_ppo.py \
  --start pilot_near --max-physics-frames 200000 --seed 0
.venv/bin/python experiments/apollo_gymnasium/scripts/evaluate.py \
  --start pilot_near --model experiments/apollo_gymnasium/models/ppo_pilot/final_model.zip
```

## Gates

1. Browser/headless bridge parity must pass.
2. Chosen start: **no-input fails**, reference guidance can land.
3. PPO pilot ≤ **1M** original physics frames; stop early if pipeline broken.
4. **Do not** start Experiments B/C/D until A lands on a nontrivial start.

## Credit

Original game © Seb Lee-Delisle, MIT License.
