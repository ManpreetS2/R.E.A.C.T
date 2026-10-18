# ApolloLander RL pilot (state-observation, not visual)

Genuine CPU-only PyTorch PPO training from **randomly initialized** weights.
No pretrained policy, no imitation, and no use of `demonstration_guidance_controller`
for training. Observation kind is explicitly:

> state-observation RL pilot, not visual learning

## Setup

```bash
pip install -e '.[rl,environments,analysis,dev]'
# CPU torch also: pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Requires Node.js for the original physics session (eval / footage / play).

## Quick commands

```bash
# Equivalence: Python physics port vs Node (must pass if using the port)
PYTHONPATH=src python -m pytest tests/rl/test_physics_equivalence.py -q

# Throughput
PYTHONPATH=src python examples/apollolander/rl_pilot/measure_throughput.py

# Train (config freezes env settings + hash before step 0)
PYTHONPATH=src python examples/apollolander/rl_pilot/train_ppo.py \
  --config examples/apollolander/rl_pilot/config.yaml

# Evaluate on Node adapter (dev + held-out)
PYTHONPATH=src python examples/apollolander/rl_pilot/evaluate.py \
  --run-dir examples/apollolander/rl_pilot/results/ppo_pilot_v1 \
  --checkpoints step0 final

# Play / render any seed
PYTHONPATH=src python examples/apollolander/rl_pilot/play.py \
  --checkpoint examples/apollolander/rl_pilot/results/ppo_pilot_v1/checkpoints/final.pt \
  --seed 1000000 --render
```

## Layout

| Path | Purpose |
| --- | --- |
| `config.yaml` | Frozen env + PPO hyperparameters |
| `landscape_map.json` | Fixed map dumped from Node (for Python port) |
| `train_ppo.py` / `evaluate.py` / `play.py` / `render_footage.py` | Pilot scripts |
| `runs/ppo_pilot_v1/` | Primary run (checkpoints, logs, plots, evaluation) |
| `runs/sweep_*` | Additional hyperparameter runs (reported honestly) |

See `docs/RL_PILOT_REPORT.md` for results, limitations, and next steps.
