# Held-out evaluation (no model calls)

Freeze the final valid selected controller from a **completed** development
experiment, then score it on sealed ApolloLander research-mode held-out starts.

This path never calls `ModelClient.propose`. It is sealed evaluation evidence,
not an LLM learning result.

## Commands

```bash
# 1) Complete a development experiment (mock / offline example)
python -m rewardbench.run \
  --config configs/apollolander_offline_development_numerical.yaml \
  --mode mock

# 2) Freeze last_valid_selected controller and evaluate on held-out starts
python -m rewardbench.heldout \
  --database runs/apollolander_offline_numerical.sqlite \
  --source-config configs/apollolander_offline_development_numerical.yaml \
  --selection-rule last_valid_selected

# Paired no-feedback condition (same held-out seeds / starts)
python -m rewardbench.run \
  --config configs/apollolander_offline_development_nofeedback.yaml \
  --mode mock

python -m rewardbench.heldout \
  --database runs/apollolander_offline_nofeedback.sqlite \
  --source-config configs/apollolander_offline_development_nofeedback.yaml \
  --selection-rule last_valid_selected
```

You may pass `--source-experiment-id exp_...` instead of `--source-config`.

## Selection rule

Default: `last_valid_selected` — the selected valid attempt with the highest
`(revision_index, call_index)`. Held-out rewards are never used to pick the
controller.

## Artifacts

SQLite tables (same database file as development):

- `frozen_controllers` — parameters, SHA-256 hash, source attempt identity
- `heldout_evaluations` — sealed schedule metadata and status
- `heldout_episodes` — rewards, outcomes, initial states, optional replay path

Repeating the same evaluation fails closed; prior evidence is not replaced.
