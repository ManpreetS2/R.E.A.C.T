# Minecraft migration

LunarLander-v3 is the first environment. A Minecraft AI Civilization adapter can be added later without changing the analysis contracts, as long as it implements `EnvironmentAdapter` from `docs/INTERFACES.md` and writes the same SQLite tables.

This document does not change Minecraft, the simulator, or the shared interface file.

## What stays

- A controller revision is still a proposal. A simulated episode is still a separate row.
- Invalid controllers are rejected by `validate_policy`. The adapter still must not execute model-authored Python.
- Feedback conditions remain `no_feedback` and `numerical_reward`.
- Development seeds and held-out seeds remain disjoint, and the split remains part of the experiment id.
- The analysis still summarizes sessions, writes the same six figure types, and refuses to rank models.
- Adaptation remains in-context. A Minecraft run is not a weight update.
- Cost, tokens, latency, and errors stay on the attempt and error tables.

## What the environment adapter changes

| LunarLander-v3 | Minecraft adapter |
| --- | --- |
| `environment_id` such as `LunarLander-v3` | a new environment id, recorded on every experiment |
| Continuous or parameterised flight controller | a schema of civilization actions the adapter can validate |
| `success` means the lander met the environment landing rule | `success` means the civilization task met its own rule |
| `crashed` is a flight outcome, or null when unused | `crashed` may stay null when the task has no crash concept |
| `metrics.fuel_used` when the simulator reports it | task metrics such as resource or survival counts, still as floats |
| Episode seed is a simulator seed | episode seed is the world or scenario seed |

The reward column remains `episodes.total_reward`. Penalties remain negative rewards. If Minecraft uses a different primary score, map that score into `total_reward` inside the adapter and describe the mapping in the experiment notes. Do not add a second reward column that the report might silently ignore.

## What the figures mean after the move

- Reward versus revision still plots `total_reward`. The caption must say which Minecraft objective that number is.
- Landing success versus attempt becomes task success versus episode attempt. The axis title in the current figure says "Landing success" because that is the LunarLander outcome. A Minecraft report should say so in the caption until the axis title is generalized. The plotted field is already `episodes.success`, not a lander-specific column.
- Crash rate is omitted from interpretation when `crashed` is null. The rate is then undefined, not zero.
- Time to target still uses a reward threshold chosen before the run. A LunarLander threshold of 200 is not a Minecraft threshold.
- Invalid-controller rate still uses selected attempts that failed validation, including an action the schema does not allow.

## Seeds and judges

Treat each held-out world seed as an evaluation case. Building or tuning a policy on that seed during development is seed leakage. The report's seed check only sees seeds that were stored. Record the world seed on the episode row.

If a language model judges Minecraft progress, that judge is not the LunarLander success flag. See `docs/LIMITATIONS.md`. Store the judge identity in experiment metadata, freeze the judge prompt, and do not mark the log independently validated until judge agreement has been checked. The analysis will not invent that check.

## Integration order

1. Implement the adapter behind `EnvironmentAdapter` without changing `docs/INTERFACES.md` unless the contract version changes on purpose.
2. Add a config file beside the LunarLander configs, with its own environment id and disjoint seed pools.
3. Run a development split only.
4. Export the SQLite log and generate a preliminary report.
5. Read the exposure and seed diagnostics.
6. Run the held-out split only after the development protocol is frozen.
7. Mark `validation_status` independently validated only after that separate check.

Until those logs exist, the Minecraft section of a paper or blog stays a methods note, not a result.
