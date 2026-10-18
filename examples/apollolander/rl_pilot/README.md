# ApolloLander RL pilot (state-observation, NOT visual)

Genuine CPU-only PyTorch PPO from **randomly initialized** weights.

**Disclosure:** The policy uses **numerical state observations** and the repo reward
with **shaped terms** (progress/potential + fuel penalty). This is **NOT**
screenshot / pixel learning.

**Simulator:** **custom Node ApolloLander simulator**
(`frontend/apollolander/experiment/physics.js`) via `ApolloLanderAdapter`.
Do not call this the original browser game’s exact physics. Python-port
equivalence tests are **port vs Node only**, not upstream-game parity.

**Reserved seeds:** `2000000`–`2000015` inclusive are sealed — never train,
evaluate, render, reset, or inspect them (code guard + tests).

No pretrained policy, no imitation, and no use of
`demonstration_guidance_controller` for training (reference-only in eval).

## Setup

```bash
pip install -e '.[rl,environments,analysis,dev]'
# CPU torch: pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Requires Node.js for the custom Node simulator session (eval / footage / play).

## Quick commands

```bash
# Port vs Node equivalence + reserved-seed guard
PYTHONPATH=src python -m pytest tests/rl/ -q

# Throughput (report actual steps/sec; 1-5M is not required)
PYTHONPATH=src python examples/apollolander/rl_pilot/measure_throughput.py

# Train (env frozen + hashed before step 0; step0 checkpoint = random init)
PYTHONPATH=src python examples/apollolander/rl_pilot/train_ppo.py \
  --config examples/apollolander/rl_pilot/config.yaml

# Frozen-policy eval on Node adapter (dev + held-out; success rate + CI)
PYTHONPATH=src python examples/apollolander/rl_pilot/evaluate.py \
  --run-dir examples/apollolander/rl_pilot/results/ppo_pilot_v1 \
  --checkpoints step0 final

# Play / render any non-reserved seed
PYTHONPATH=src python examples/apollolander/rl_pilot/play.py \
  --checkpoint examples/apollolander/rl_pilot/results/ppo_pilot_v1/checkpoints/final.pt \
  --seed 1000000 --render
```

## Layout

| Path | Purpose |
| --- | --- |
| `config.yaml` | Frozen env + PPO hyperparameters + reserved-seed list |
| `landscape_map.json` | Fixed map dumped from custom Node simulator |
| `train_ppo.py` / `evaluate.py` / `play.py` / `render_footage.py` | Pilot scripts |
| `results/ppo_pilot_v1/` | Primary run (checkpoints incl. `step0`, logs, plots, eval, footage JSONs) |
| `results/sweep_*` / `ppo_pilot_v2_*` / `v3_*` | Additional runs (all reported) |

See `docs/RL_PILOT_REPORT.md` for measured steps/sec, total env steps, PPO
update/grad-step counts, held-out success rates with CIs, and limitations.
